"""Legacy EndTurn repeats must not consume the range's twenty-turn budget."""
import unittest
from contextlib import closing
import sqlite3

import test_shooting_range as fixtures
import test_multi_account as network_fixtures
from tio import battle_snapshot
from tio.arena_service import ArenaService
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.transport import encode_initial_frame
from tio.locations import LocationStore, SHOOTING_RANGE, center
from tio.shooting_range import CREATE_REQUEST


class RangeTurnRepeatTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.RangeTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.start()
        self.arena = self.case.arena
        self.room_id = self.case.room.room_id

    def skip(self, actor=0):
        reply = self.arena.end_turn(42, encode_end_turn(actor))
        return self.arena.finished_turn_packets(42, reply)

    def advance(self):
        self.arena.advance_turn(self.room_id, 60)

    def assert_repeat_preserves_turn(self):
        turn = self.arena._turns[self.room_id]
        field = self.arena._fields[self.room_id]
        actor = field.actor(self.case.identity)
        round_number = field._ability_turns[self.case.identity]
        for _ in range(3):
            self.assertEqual(self.skip(), ())
            self.assertEqual(self.arena._turns.get(self.room_id), turn)
            self.assertEqual(field.actor(self.case.identity), actor)
            self.assertEqual(field._ability_turns[self.case.identity], round_number)
        self.assertGreater(actor.action_points, 0)

    def test_triple_repeat_preserves_new_turn_and_displayed_ap(self):
        self.assertIn(b'\x39', self.skip())
        self.advance()
        self.assert_repeat_preserves_turn()

    def test_repeat_before_next_turn_does_not_finish_twice(self):
        self.skip()
        self.assertEqual(self.skip(self.case.identity), ())
        self.advance()
        self.assert_repeat_preserves_turn()

    def test_slow_next_turn_renews_repeat_protection(self):
        self.skip()
        self.case.now[0] += 3
        self.advance()
        self.assert_repeat_preserves_turn()

    def test_timeout_then_late_skip_preserves_next_turn(self):
        self.case.now[0] = self.arena._turns[self.room_id][2]
        for owner, reply in self.arena.expire_turns():
            self.arena.finished_turn_packets(owner, reply)
        self.advance()
        self.assert_repeat_preserves_turn()

    def test_deliberate_skip_after_repeat_window_still_works(self):
        self.skip()
        self.advance()
        self.case.now[0] += 1.01
        reply = self.arena.end_turn(42, encode_end_turn(self.case.identity), received_at=self.case.now[0])
        self.assertIn(b'\x39', self.arena.finished_turn_packets(42, reply))
        self.assertNotIn(self.room_id, self.arena._turns)

    def test_forged_actor_is_rejected_inside_repeat_window(self):
        self.skip()
        self.advance()
        turn = self.arena._turns[self.room_id]
        with self.assertRaises(ValueError):
            self.skip(min(self.case.field.practice.targets))
        self.assertEqual(self.arena._turns[self.room_id], turn)

    def test_repeats_do_not_extend_the_blocking_window(self):
        self.skip()
        self.advance()
        for _ in range(2):
            self.case.now[0] += .4
            self.assertEqual(self.skip(), ())
        self.case.now[0] += .21
        self.assertIn(b'\x39', self.skip())

    def test_one_received_batch_stays_protected_while_checkpoint_work_is_slow(self):
        self.skip()
        self.advance()
        received_at = self.case.now[0] + .2
        turn = self.arena._turns[self.room_id]
        actor = self.case.field.actor(self.case.identity)
        for _ in range(3):
            # Journal/SQLite work can delay dispatch after recv() returned.
            self.case.now[0] += .6
            reply = self.arena.end_turn(42, encode_end_turn(), received_at=received_at)
            self.assertEqual(self.arena.finished_turn_packets(42, reply), ())
            self.assertEqual(self.arena._turns.get(self.room_id), turn)
            self.assertEqual(self.case.field.actor(self.case.identity), actor)

    def test_batched_repeat_received_before_completion_is_ignored(self):
        received_at = self.case.now[0]
        self.case.now[0] += .5
        self.skip()
        reply = self.arena.end_turn(42, encode_end_turn(), received_at=received_at)
        self.assertEqual(self.arena.finished_turn_packets(42, reply), ())

    def test_twenty_real_turns_survive_triple_repeats(self):
        for number in range(1, 21):
            self.assertEqual(self.case.field._ability_turns[self.case.identity], number)
            if number > 1:
                self.assert_repeat_preserves_turn()
            self.case.now[0] += 1.01
            self.skip()
            result = self.arena.finish_training(42, self.case.path, 'alice')
            if number < 20:
                self.assertFalse(result)
                self.advance()
            else:
                self.assertEqual(result[-1][:1], b'\x4c')
                self.assertFalse(self.arena.rooms.snapshot())

    def test_restore_rebases_repeat_window_to_new_monotonic_clock(self):
        self.skip()
        self.advance()
        saved = battle_snapshot.dumps(self.arena, clock=lambda: 100., wall=lambda: 1000.)
        self.case.now[0] = 500.
        self.arena, _ = battle_snapshot.loads(
            saved, clock=lambda: self.case.now[0], wall=lambda: 1000.4)
        self.assert_repeat_preserves_turn()
        self.case.now[0] += .61
        self.assertIn(b'\x39', self.skip())

    def test_old_snapshot_initializes_missing_repeat_state(self):
        old = ArenaService(clock=lambda: 100.)
        old.__dict__.pop('_end_turn_fences', None)
        saved = battle_snapshot.dumps(old, clock=lambda: 100., wall=lambda: 1000.)
        restored, _ = battle_snapshot.loads(saved, clock=lambda: 500., wall=lambda: 1000.)
        self.assertEqual(restored._end_turn_fences, {})

    def test_disconnect_releases_repeat_state(self):
        self.skip()
        self.arena.disconnect(42)
        self.assertEqual(self.arena._end_turn_fences, {})


class RangeTurnNetworkTests(unittest.TestCase):
    def test_two_tcp_accounts_keep_twenty_turns_despite_batched_repeats(self):
        case = network_fixtures.MultiAccountTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        LocationStore(case.config.database)
        with closing(sqlite3.connect(case.config.database)) as db, db:
            for name in ('alice', 'bob'):
                LocationStore._save(db, name, SHOOTING_RANGE, *center(SHOOTING_RANGE))
        case.start()
        peers = []
        sessions = []
        now = [100.]
        for name in ('alice', 'bob'):
            peer = case.handoff(case.begin(name))
            case.enter(peer, name.title())
            session = case.server.multi.active_accounts[name]
            session.arena._clock = lambda: now[0]
            peer.send(CREATE_REQUEST)
            peer.until(b'\x25')
            peer.send(b'\x2e\0')
            peer.until(b'\x41', max_packets=256)
            peer.send(b'\x36')
            peer.until(b'\x38', max_packets=256)
            peers.append(peer)
            sessions.append(session)
        for number in range(1, 21):
            for peer, session in zip(peers, sessions):
                arena = session.arena
                room = arena.rooms.snapshot()[0]
                field = arena._fields[room.room_id]
                actor_id = field.actor_ids(room.owner_id)[0]
                self.assertEqual(field._ability_turns[actor_id], number)
                if number > 1:
                    turn = arena._turns[room.room_id]
                    actor = field.actor(actor_id)
                    # One receive() can contain all three old client frames.
                    peer.sock.sendall(b''.join(encode_initial_frame(encode_end_turn(), peer.outbound)
                                               for _ in range(3)))
                    rows = case.exchange_inventory_requests(peer, [])
                    self.assertNotIn(b'\x39', rows)
                    self.assertFalse(any(p[:1] in (b'\x38', b'\x4c') for p in rows))
                    self.assertEqual(arena._turns.get(room.room_id), turn)
                    self.assertEqual(field.actor(actor_id), actor)
            now[0] += 1.01
            for peer in peers:
                peer.send(encode_end_turn())
                peer.until(b'\x4c' if number == 20 else b'\x38', max_packets=256)
        self.assertTrue(all(not session.arena.rooms.snapshot() for session in sessions))
        self.assertIsNot(sessions[0].arena, sessions[1].arena)


if __name__ == '__main__':
    unittest.main()
