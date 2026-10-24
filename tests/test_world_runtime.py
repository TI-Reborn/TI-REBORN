"""Authenticated native world requests and SQLite online prison sessions.

These are local backend/transport checks, not real game-client or VPS proof.
"""
from collections import deque
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from server.accounts import Accounts
from server.presence import Presence
from server.training_arena import TrainingArena
from server import world_runtime as runtime
from tio import battle_checkpoints, battle_settlement, ranked
from tio import world_completion as world
from tio.battle_rewards import settle
from tio.character_identity import alias
from tio.characters import CharacterStore
from tio.db_transaction import transaction
from tio.locations import LocationStore, center, town_packets
from tio.owned_pets import OwnedPetStore
from tio.player_statistics import settle_statistics
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.player_top100 import decode_ratings, encode_request
from tio.protocol.presence import Player
from tio.protocol.system_message import decode_current_town, encode_open_town_view
from tio.protocol.town_info import decode_town_info
from tio.wallets import WalletStore


class Session:
    pass


def saved_world(case, names=('Alice', 'Bob')):
    """Use production account, character, roster, wallet and location schemas."""
    temporary = tempfile.TemporaryDirectory()
    case.addCleanup(temporary.cleanup)
    case.path = Path(temporary.name)/'players.sqlite3'
    accounts = Accounts(case.path)
    for name in names:
        accounts.create(name.lower(), 'World-test-password-123', character=name)
    case.characters = CharacterStore(case.path)
    case.locations = LocationStore(case.path, clock=lambda: 0)
    source = json.loads((world.ROOT/'evidence/owned_pet_trial.json').read_text())
    case.pet = decode_pet_info(bytes.fromhex(source['packet_hex']), human_equipment=True)
    case.pets = OwnedPetStore(case.path)
    for name in names:
        case.pets.ensure(name.lower(), encode_pet_info(case.pet), encode_item_list(1, ()), human=True)
        WalletStore(case.path).ensure(name.lower())
        with transaction(case.path) as db:
            LocationStore._save(db, name.lower(), 3, *center(3))


def session_for(case, account):
    session = Session()
    session.database = case.path
    session.account = account
    session.locations = case.locations
    session.probe_character_id = 1
    session.probe_character_name = account.title().encode()
    session.arena = None
    session.router = None
    session.owned_pet_probe = False
    return session


class WorldStandingsRuntimeTests(unittest.TestCase):
    def setUp(self):
        saved_world(self, ('Alice', 'Bob', 'Carol'))
        self.characters.create('alice', CharacterCreateRequest(b'AliceTwo', 0, (0,0,0,0)))
        self.secondary = alias('alice', 2)
        self.pets.ensure(self.secondary, encode_pet_info(self.pet), encode_item_list(1, ()), human=True)
        WalletStore(self.path).ensure(self.secondary)
        # Persist actual reward receipts and statistics through their stores.
        for owner, kills, damage, points, xp, wins in (
                ('alice', 3, 10, 300, 100, 1),
                ('bob', 1, 100, 30, 900, 2),
                ('carol', 0, 20, -30, 10, 0)):
            with transaction(self.path) as db:
                row = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1', (owner,)).fetchone()
                pet = decode_pet_info(bytes(row[0]), human_equipment=True)
                raw = encode_pet_info(replace(pet, fields={**pet.fields,
                    '0x8c4bbc':1, '0x8c4bd0':points & 0xffffffff, '0x8c4b05':xp, '0x8c4aef':1}))
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1', (raw, owner))
                settle_statistics(db, owner, 'statistics-'+owner, 1 if wins else 0,
                    ({'kills':kills, 'losses':int(not wins), 'damage_dealt':damage,
                      'damage_received':7}, {1:[kills, int(not wins)]}), now=0)
            for index in range(max(1, wins)):
                settle(self.path, owner, f'reward-{owner}-{index}', 1 if wins else 0, now=0)
        with transaction(self.path) as db:
            ranked.settle(db, 'earned-league-match',
                {'teams':[[('alice', ranked.MU, ranked.SIGMA)],
                          [('bob', ranked.MU, ranked.SIGMA)]], 'winner':None}, now=0)
            # Stored league/skill values are fixtures for the routing selectors;
            # ranked inference and promotion rules have their own tests.
            db.execute("UPDATE ranked_players SET league=1,skill=250 WHERE account='alice'")
            db.execute("UPDATE ranked_players SET league=2,skill=150 WHERE account='bob'")
        self.presence = Presence()
        self.alice = session_for(self, 'alice')
        self.bob = session_for(self, 'bob')
        for index, session in enumerate((self.alice, self.bob), 1):
            self.presence.players[session] = (3, Player(100+index, session.probe_character_name))
            self.presence.queues[session] = deque()
            self.presence.messages[session] = deque()

    def test_nine_native_selectors_private_dispatch_real_offline_owners_read_only(self):
        before = self.path.read_bytes()
        expected = {0:b'Alice', 1:b'Bob', 2:b'Bob', 3:b'Alice',
                    4:b'Bob', 5:b'Alice', 6:None, 7:b'Bob', 8:b'Alice'}
        for selector in range(9):
            with self.subTest(selector=selector), patch('server.world_runtime.time.monotonic', return_value=10+selector):
                self.assertTrue(self.presence.handle(self.alice, encode_request(selector)))
                packets = tuple(self.presence.messages[self.alice])
                self.presence.messages[self.alice].clear()
                self.assertEqual(len(packets), 1)
                actual, rows = decode_ratings(packets[0])
                self.assertEqual(actual, selector)
                self.assertEqual(rows[0].name if rows else None, expected[selector])
                if selector < 6:
                    self.assertEqual({r.name for r in rows}, {b'Alice', b'AliceTwo', b'Bob', b'Carol'})
                self.assertFalse(self.presence.messages[self.bob])
                self.assertFalse(self.presence.queues[self.alice])
                self.assertNotIn(self.secondary.encode(), packets[0])
                self.assertNotIn(b'World-test-password', packets[0])
        self.assertEqual(self.path.read_bytes(), before)

    def test_rate_is_per_authenticated_connection_and_exact_boundary(self):
        with patch('server.world_runtime.time.monotonic', return_value=10):
            self.assertEqual(len(runtime.standings(self.alice, encode_request(0))), 1)
            self.assertEqual(runtime.standings(self.alice, encode_request(1)), ())
            self.assertEqual(len(runtime.standings(self.bob, encode_request(1))), 1)
        with patch('server.world_runtime.time.monotonic', return_value=10.249):
            self.assertEqual(runtime.standings(self.alice, encode_request(2)), ())
        with patch('server.world_runtime.time.monotonic', return_value=10.25):
            self.assertEqual(decode_ratings(runtime.standings(self.alice, encode_request(2))[0])[0], 2)

    def test_malformed_requests_return_native_private_error_without_consuming_valid_rate(self):
        before = self.path.read_bytes()
        for raw in (b'\xa4', b'\xa4\x09', b'\xa4\xff', b'\xa4\0\0'):
            with self.subTest(raw=raw), patch('server.world_runtime.time.monotonic', return_value=20):
                self.assertTrue(self.presence.handle(self.alice, raw))
                error, = self.presence.messages[self.alice]
                self.presence.messages[self.alice].clear()
                self.assertEqual(error[:5], b'\xf0'+struct.pack('<I', 394))
                self.assertFalse(self.presence.messages[self.bob])
                self.assertFalse(hasattr(self.alice, '_world_standings_at'))
        with patch('server.world_runtime.time.monotonic', return_value=20):
            self.assertEqual(len(runtime.standings(self.alice, encode_request(0))), 1)
            self.assertEqual(len(runtime.standings(self.alice, b'\xa4')), 1)
            self.assertEqual(runtime.standings(self.alice, encode_request(0)), ())
        self.assertEqual(self.path.read_bytes(), before)

    def test_standings_remain_available_during_authoritative_battle_binding(self):
        battle_checkpoints.initialise(self.path)
        with transaction(self.path) as db:
            battle_checkpoints.save(db, 'real-bound-match', '{}', {'alice':1001, 'bob':1002}, now=0)
        before = self.path.read_bytes()
        with patch('server.world_runtime.time.monotonic', return_value=30):
            self.assertTrue(self.presence.handle(self.alice, encode_request(0)))
        self.assertEqual(decode_ratings(self.presence.messages[self.alice][0])[1][0].name, b'Alice')
        self.assertFalse(self.presence.messages[self.bob])
        self.assertEqual(self.path.read_bytes(), before)


class WorldPrisonRuntimeTests(unittest.TestCase):
    def setUp(self):
        saved_world(self)
        self.alice = session_for(self, 'alice')
        self.bob = session_for(self, 'bob')

    def state(self, owner='alice'):
        with closing(sqlite3.connect(self.path)) as db:
            return world.prison_state(db, owner)

    def sentence(self, seconds=100, operation='trusted-sentence'):
        with transaction(self.path) as db:
            return world.sentence(db, 'alice', seconds, operation)

    def row(self, query, parameters=()):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(query, parameters).fetchone()

    def test_offline_reconnect_stale_disconnect_and_release_packets(self):
        with transaction(self.path) as db:
            LocationStore._save(db, 'alice', 18, -120, 80)
        self.sentence()
        self.assertEqual(decode_town_info(runtime.heartbeat(self.alice, now=100)[0]).town_id,10)
        token = self.alice._prison_token
        self.assertTrue(token.startswith('session:'))
        self.assertGreaterEqual(len(token), 50)
        self.assertEqual(runtime.heartbeat(self.alice, now=120, active=False), ())
        self.assertEqual(self.state(), {'remaining':80, 'town_id':10})
        self.assertEqual(self.row("SELECT token,last_tick FROM world_prison WHERE account='alice'"), (None, None))
        reconnected = session_for(self, 'alice')
        self.assertEqual(decode_town_info(runtime.heartbeat(reconnected, now=1000)[0]).town_id,10)
        self.assertNotEqual(reconnected._prison_token, token)
        self.assertEqual(self.state()['remaining'], 80)
        self.assertEqual(runtime.heartbeat(self.alice, now=1010, active=False), ())
        self.assertEqual(self.row("SELECT token FROM world_prison WHERE account='alice'")[0], reconnected._prison_token)
        self.assertEqual(runtime.heartbeat(reconnected, now=1030), ())
        self.assertEqual(self.state()['remaining'], 50)
        # A server stall over the accepted heartbeat gap is not online credit.
        self.assertEqual(runtime.heartbeat(reconnected, now=1200), ())
        self.assertEqual(self.state()['remaining'], 50)
        packets = runtime.heartbeat(reconnected, now=1250)
        self.assertEqual(len(packets), 3)
        self.assertEqual(decode_town_info(packets[0]).town_id, 18)
        self.assertEqual(decode_current_town(packets[1]), 18)
        self.assertEqual(packets[2], encode_open_town_view())
        self.assertEqual(self.state(), {'remaining':0, 'town_id':18})
        self.assertEqual(self.row("SELECT town_id,x,y FROM character_locations WHERE account='alice'"), (18, -120, 80))
        self.assertEqual(runtime.heartbeat(reconnected, now=1251), ())
        self.assertIsNone(self.state('bob'))

    def test_clock_backwards_never_charges_twice_and_gap_limit_is_inclusive(self):
        self.sentence()
        runtime.heartbeat(self.alice, now=100)
        runtime.heartbeat(self.alice, now=90)
        self.assertEqual(self.state()['remaining'], 100)
        self.assertEqual(self.row("SELECT last_tick FROM world_prison WHERE account='alice'")[0], 100)
        runtime.heartbeat(self.alice, now=160)
        self.assertEqual(self.state()['remaining'], 40)
        runtime.heartbeat(self.alice, now=221)
        self.assertEqual(self.state()['remaining'], 40)

    def test_disconnect_can_finish_sentence_without_emitting_offline_city_packets(self):
        self.sentence(5)
        presence = Presence()
        runtime.heartbeat(self.alice, now=100)
        with patch('server.world_runtime.time.time', return_value=105):
            presence.disconnect(self.alice)
        self.assertEqual(self.state(), {'remaining':0, 'town_id':3})
        self.assertEqual(self.locations.current('alice'), 3)
        self.assertEqual(self.row("SELECT token,last_tick FROM world_prison WHERE account='alice'"), (None, None))
        self.assertEqual(runtime.heartbeat(self.alice, now=1000), ())

    def test_presence_sync_queues_release_only_for_prisoner_and_updates_actual_town(self):
        self.sentence(10)
        presence = Presence()
        with patch('server.world_runtime.time.time', return_value=100), patch('server.presence.time.monotonic', return_value=0):
            presence.sync(self.alice)
            presence.sync(self.bob)
        self.assertEqual(presence.players[self.alice][0], 10)
        self.assertEqual(presence.players[self.bob][0], 3)
        initial=tuple(presence.messages[self.alice])
        self.assertEqual(len(initial),3)
        self.assertEqual(decode_town_info(initial[0]).town_id,10)
        self.assertEqual(decode_current_town(initial[1]),10)
        self.assertFalse(presence.messages[self.bob])
        presence.messages[self.alice].clear()
        with patch('server.world_runtime.time.time', return_value=110), patch('server.presence.time.monotonic', return_value=1):
            presence.sync(self.alice)
        packets = tuple(presence.messages[self.alice])
        self.assertEqual(len(packets), 3)
        self.assertEqual(decode_current_town(packets[1]), 3)
        self.assertEqual(presence.players[self.alice][0], 3)
        self.assertFalse(presence.messages[self.bob])

    def test_authenticated_guard_blocks_prisoner_until_actual_online_completion(self):
        self.sentence(10)
        with self.assertRaisesRegex(ValueError, 'Prison'):
            runtime.require_unjailed(self.alice)
        runtime.require_unjailed(self.bob)
        # Advancing real/server time without heartbeats is insufficient.
        with patch('server.world_runtime.time.time', return_value=100000):
            with self.assertRaises(ValueError):
                runtime.require_unjailed(self.alice)
        runtime.heartbeat(self.alice, now=100)
        runtime.heartbeat(self.alice, now=110)
        runtime.require_unjailed(self.alice)

    def test_sentence_is_idempotent_cancels_journey_and_preserves_other_saved_owner(self):
        packet = b'\x1b'+struct.pack('<ii', *center(18))
        self.locations.travel('alice', packet, 1)
        self.assertTrue(self.locations.travelling('alice'))
        before = self.row("SELECT town_id,x,y FROM character_locations WHERE account='bob'")
        first = self.sentence(10)
        self.assertEqual(self.sentence(10), first)
        self.assertFalse(self.locations.travelling('alice'))
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.sentence(11)
        self.assertEqual(self.state()['remaining'], 10)
        self.assertEqual(self.row("SELECT COUNT(*) FROM world_prison_operations")[0], 1)
        self.assertEqual(self.row("SELECT town_id,x,y FROM character_locations WHERE account='bob'"), before)

    def test_active_and_quarantined_checkpoint_leases_block_trusted_sentence_atomically(self):
        battle_checkpoints.initialise(self.path)
        for status in ('active', 'quarantined'):
            with self.subTest(status=status):
                with transaction(self.path) as db:
                    battle_checkpoints.save(db, 'saved-battle', '{}', {'alice':1001}, status=status, now=0)
                before = self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'authoritative battle'):
                    self.sentence()
                self.assertIsNone(self.state())
                self.assertEqual(self.locations.current('alice'), 3)
                self.assertEqual(self.path.read_bytes(), before)
                with transaction(self.path) as db:
                    battle_checkpoints.delete(db, 'saved-battle')
        self.assertEqual(self.sentence()['town_id'], 10)

    def test_pending_real_settlement_outbox_blocks_sentence_until_job_is_removed(self):
        battle_settlement.enqueue(self.path, 'pending-real-report', [('alice', 1, {})])
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'authoritative battle'):
            self.sentence()
        self.assertIsNone(self.state())
        self.assertEqual(self.path.read_bytes(), before)
        battle_settlement.apply(self.path, 'pending-real-report', 'alice')
        self.assertIsNone(self.row("SELECT 1 FROM battle_settlement_jobs WHERE account='alice'"))
        self.assertEqual(self.sentence()['town_id'], 10)

    def test_heartbeat_joins_existing_gameplay_transaction_and_rolls_back_release(self):
        self.sentence(10)
        runtime.heartbeat(self.alice, now=100)
        with self.assertRaisesRegex(RuntimeError, 'rollback release'):
            with transaction(self.path):
                packets = runtime.heartbeat(self.alice, now=110)
                self.assertEqual(decode_current_town(packets[1]), 3)
                raise RuntimeError('rollback release')
        self.assertEqual(self.state(), {'remaining':10, 'town_id':10})
        self.assertEqual(self.locations.current('alice'), 10)
        packets = runtime.heartbeat(self.alice, now=110)
        self.assertEqual(decode_current_town(packets[1]), 3)
        self.assertEqual(self.state()['remaining'], 0)

    def test_sentence_and_online_clock_belong_to_selected_saved_character_owner(self):
        self.characters.create('alice', CharacterCreateRequest(b'AliceTwo', 0, (0,0,0,0)))
        secondary = self.characters.owner('alice', 2)
        selected = session_for(self, secondary)
        with transaction(self.path) as db:
            LocationStore._save(db, secondary, 18, *center(18))
            world.sentence(db, secondary, 10, 'secondary-sentence')
        self.assertEqual(self.locations.current(secondary), 10)
        self.assertEqual(self.locations.current('alice'), 3)
        runtime.require_unjailed(self.alice)
        with self.assertRaises(ValueError):
            runtime.require_unjailed(selected)
        self.assertEqual(runtime.heartbeat(self.alice, now=100), ())
        self.assertEqual(self.state(secondary)['remaining'], 10)
        runtime.heartbeat(selected, now=100)
        packets = runtime.heartbeat(selected, now=110)
        self.assertEqual(decode_current_town(packets[1]), 18)
        self.assertIsNone(self.state('alice'))
        self.assertEqual(self.locations.current('alice'), 3)
        runtime.require_unjailed(selected)

    def test_unselected_or_unconfigured_session_does_not_create_prison_token_or_data(self):
        before = self.path.read_bytes()
        for session in (Session(), session_for(self, 'bob')):
            self.assertEqual(runtime.heartbeat(session, now=100), ())
            self.assertFalse(hasattr(session, '_prison_token'))
        unselected = session_for(self, '')
        self.assertEqual(runtime.heartbeat(unselected, now=100), ())
        self.assertFalse(hasattr(unselected, '_prison_token'))
        self.assertEqual(self.path.read_bytes(), before)


class TrainingTownProjectionRuntimeTests(unittest.TestCase):
    def setUp(self):
        saved_world(self)
        self.session = session_for(self, 'alice')
        self.now = 100
        self.training = TrainingArena()
        self.training.lock = threading.RLock()
        self.training.init_training(self.path, wall=lambda: self.now)
        self.session.router = Session()
        self.session.router.team_arena = self.training

    def test_current_training_town_keeps_permanent_registration_and_location_band(self):
        for town, band, cap in ((19,(4,6),10), (20,(7,10),15), (21,(11,15),20), (22,(16,20),25)):
            with self.subTest(town=town):
                with transaction(self.path) as db:
                    LocationStore._save(db, 'alice', town, *center(town))
                original = town_packets(town, clock=lambda: self.now)[0]
                projected = runtime.project_town(self.session, original)
                self.assertEqual(projected[:len(original)-2], original[:-2])
                self.assertEqual(projected[len(original)-2], 1)
                body = projected[len(original)-1:-1]
                phase, utc = struct.unpack_from('<II', body)
                self.assertEqual((phase, utc), (1, 100))
                self.assertEqual(body[8], 1)
                self.assertEqual(struct.unpack_from('<II', body, 9), (100, 0))
                self.assertEqual(tuple(body[17:22]), (*band, *band, cap))
                self.assertEqual(body[22:], b'\0\0')
                self.assertEqual(projected[-1], original[-1])
        event = self.training.training_events[19]
        self.now = event['starts']+1801
        with transaction(self.path) as db:
            LocationStore._save(db, 'alice', 19, *center(19))
        projected = runtime.project_town(self.session, town_packets(19, clock=lambda: self.now)[0])
        self.assertEqual(struct.unpack_from('<I', projected, len(town_packets(19)[0])-1)[0], 1)

    def test_ordinary_packets_and_missing_training_adapter_are_preserved(self):
        for raw in (*town_packets(3), b'\xc8\x2d', b'\xc8\x2d\x13', b'\x9e'):
            self.assertEqual(runtime.project_town(self.session, raw), raw)
        raw = town_packets(19)[0]
        self.session.router = None
        self.assertEqual(runtime.project_town(self.session, raw), raw)
        self.session.router = Session()
        self.session.router.team_arena = Session()
        self.assertEqual(runtime.project_town(self.session, raw), raw)

    def test_training_schedule_is_projected_only_for_actual_recipient_town(self):
        before = self.path.read_bytes()
        for town in (19,20,21,22):
            raw = town_packets(town)[0]
            self.assertEqual(runtime.project_town(self.session, raw), raw)
        self.assertEqual(self.training.training_events, {})
        self.assertEqual(self.path.read_bytes(), before)
        with transaction(self.path) as db:
            LocationStore._save(db, 'alice', 19, *center(19))
        foreign = town_packets(20)[0]
        self.assertEqual(runtime.project_town(self.session, foreign), foreign)
        current = town_packets(19)[0]
        self.assertNotEqual(runtime.project_town(self.session, current), current)
        self.assertEqual(set(self.training.training_events), {19})


class TownRateRuntimeTests(unittest.TestCase):
    @staticmethod
    def native_bits(values):
        return struct.unpack('<III', struct.pack('<fff', *(float(Fraction(value)) for value in values)))

    def test_native_float_order_and_carry_policy_for_outpost_and_dynamic_detroit(self):
        outpost = decode_town_info(town_packets(4, clock=lambda:3599)[0])
        self.assertEqual(outpost.unknown_float_bits, self.native_bits((0, '3/4', 1)))
        self.assertEqual(outpost.unknown_bools, (0,0,0))
        observed = set()
        for now in (0,3600,7200,10800):
            with self.subTest(now=now):
                factors = world.city_coefficients(18, now=now)
                packet = town_packets(18, clock=lambda:now)[0]
                native = decode_town_info(packet)
                self.assertEqual(native.unknown_float_bits, self.native_bits(
                    (factors['influence'], factors['experience'], factors['profit'])))
                self.assertEqual(native.unknown_bools, (0,1,0))
                observed.add(native.unknown_float_bits)
        self.assertGreater(len(observed), 1)

    def test_sparse_hour_refresh_sends_only_towninfo_without_writes_or_reopening_menus(self):
        saved_world(self)
        self.now = 3599
        locations = LocationStore(self.path, clock=lambda:self.now)
        with transaction(self.path) as db:
            for account in ('alice','bob'):
                LocationStore._save(db, account, 18, *center(18))
        before = self.path.read_bytes()
        self.assertEqual(locations.refresh('alice',1), ())
        self.assertEqual(locations.refresh('bob',2), ())
        self.assertEqual(locations.refresh('alice',1), ())
        self.now = 3601
        packet, = locations.refresh('alice',1)
        self.assertEqual(packet[:2], b'\xc8\x2d')
        self.assertEqual(packet, town_packets(18, clock=lambda:self.now)[0])
        self.assertEqual(locations.refresh('alice',1), ())
        self.assertEqual(locations.refresh('bob',2), (packet,))
        self.assertEqual(locations.current('alice'), 18)
        self.assertEqual(locations.current('bob'), 18)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
