"""Original inner boundary, authoritative squad checks and shared departure."""
from dataclasses import replace
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tio.battle_state import BattleActor, BattleField
from tio.protocol.arena import decode_battle_settings_body
from tio.arena_service import ArenaService
from tio.shooting_range import ShootingRangeService
from tio.wallets import WalletStore
from server.battle_journal import BattleJournal
import test_battle_finish as private_fixture
import test_shared_team_arena as fixture


class EdgeRuleTests(unittest.TestCase):
    def test_all_four_native_edges_and_dead_reserves(self):
        for x, y in ((1, 5), (8, 5), (5, 1), (5, 10)):
            with self.subTest(cell=(x, y)):
                field = BattleField(10, 12, (
                    BattleActor(1, 11, x, y, 0, 10, 10),
                    BattleActor(2, 11, 4, 4, 0, 0, 10),
                    BattleActor(3, 22, 5, 5, 0, 10, 10)), step_cost=1)
                self.assertTrue(field.can_exit(11))
                self.assertFalse(field.can_exit(22))

    def test_one_living_member_interior_blocks_entire_own_squad(self):
        field = BattleField(10, 12, (
            BattleActor(1, 11, 1, 5, 3, 10, 10),
            BattleActor(2, 11, 4, 4, 3, 10, 10)), step_cost=1)
        self.assertFalse(field.can_exit(11))

    def test_private_scene_setting_and_exit_gate(self):
        arena = ArenaService(clock=lambda: 0)
        scene = private_fixture.BattleFinishTests().scene(100, 100)
        _, packets = arena.start_survival(7, b'Alice', scene)
        settings = next(p for p in packets if p[0] == 0x6c)
        self.assertEqual(decode_battle_settings_body(settings[1:]).exit_zone, 1)
        arena.member_loaded(7, b'\x36')
        scene.field._actors[1] = replace(scene.field.actor(1), x=4, y=5)
        with self.assertRaises(ValueError):
            arena.leave(7, b'\x2a\x01')
        self.assertTrue(arena.rooms.snapshot())
        scene.field._actors[1] = replace(scene.field.actor(1), x=1)
        arena.leave(7, b'\x2a\x01')
        self.assertFalse(arena.rooms.snapshot())

    def test_practice_lobby_enables_same_native_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ShootingRangeService(Path(folder) / 'range.sqlite3', ArenaService(), None)
            packet = service.settings('alice', b'Alice', 1)
            self.assertEqual(decode_battle_settings_body(packet[1:]).exit_zone, 1)


class SharedExitTests(unittest.TestCase):
    setUpClass = classmethod(fixture.SharedTeamTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.SharedTeamTests.tearDownClass.__func__)
    setUp = fixture.SharedTeamTests.setUp
    send = fixture.SharedTeamTests.send
    create = fixture.SharedTeamTests.create

    def battle(self):
        for index in (0, 1):
            self.create(index, 1)
            self.send(index, b'\x2e')
        owners = [self.hub.identities[s] for s in self.sessions[:2]]
        battle = self.hub.battles[owners[0]]
        for index in (0, 1):
            self.send(index, b'\x36')
        return battle, owners

    def test_scene_and_reconnect_enable_native_exit(self):
        battle, owners = self.battle()
        for owner in owners:
            self.hub.queues[owner].clear()
            self.hub.send_scene(owner, reconnect=True)
            settings = next(p for p in self.hub.queues[owner] if p[0] == 0x6c)
            self.assertEqual(decode_battle_settings_body(settings[1:]).exit_zone, 1)

    def test_interior_request_keeps_both_players_then_edge_retires_only_owner(self):
        battle, owners = self.battle()
        field = battle['field']
        identity = field.actor_ids(owners[0])[0]
        field._actors[identity] = replace(field.actor(identity), x=5, y=5)
        self.send(0, b'\x2a\x01')
        self.assertIn(owners[0], self.hub.battles)
        self.assertIn(owners[1], self.hub.battles)
        field._actors[identity] = replace(field.actor(identity), x=1, y=5)
        self.send(0, b'\x2a\x01')
        self.assertNotIn(owners[0], self.hub.battles)
        self.assertIs(self.hub.battles[owners[1]], battle)
        self.assertFalse(field.actor_ids(owners[0]))
        self.assertTrue(field.actor_ids(owners[1]))
        wallet = WalletStore(self.path).ensure('alice')
        self.hub.handle(self.sessions[0], b'\x2a\x01')
        self.assertEqual(WalletStore(self.path).ensure('alice'), wallet)

    def test_checkpoint_failure_restores_both_squads_and_departure_receipt(self):
        battle, owners = self.battle()
        self.hub.journal = BattleJournal(self.hub, self.path, wall=lambda: 1000)
        field = battle['field']
        identity = field.actor_ids(owners[0])[0]
        with self.hub.journal.unit(battle):
            field._actors[identity] = replace(field.actor(identity), x=1, y=5)
        before = dict(field._actors)
        wallet = WalletStore(self.path).ensure('alice')
        with patch('tio.battle_checkpoints.save', side_effect=sqlite3.OperationalError('disk I/O error')):
            with self.assertRaises(sqlite3.OperationalError):
                self.hub.battle_action(owners[0], b'\x2a\x01')
        self.assertEqual(self.hub.battles[owners[0]]['field']._actors, before)
        self.assertIs(self.hub.battles[owners[0]], self.hub.battles[owners[1]])
        self.assertEqual(WalletStore(self.path).ensure('alice'), wallet)


if __name__ == '__main__':
    unittest.main()
