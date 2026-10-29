from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from server.accounts import Accounts
from tio.characters import CharacterStore
from tio.db_transaction import transaction
from tio.locations import LocationStore, MAP_SPEED, TURN_LEAD, center, movement_packet, stop_packet
from tio.protocol.map_route import route_words
from tio.roads import ROADS, leg_index, path_length, point_along
from tio.protocol.world_bootstrap import encode_open_map_view, encode_restore_city_controls
from tio.party_travel import PartyLocations, PartyTravel
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import PetInfo, decode_pet_info, encode_pet_info
from tio.pve_contracts import ContractStore
from tio.travel_party import PartyStore


class PartyTravelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_folder = tempfile.TemporaryDirectory()
        cls.seed_path = Path(cls.seed_folder.name) / 'registered.db'
        accounts = Accounts(cls.seed_path)
        for login in ('alice', 'bravo', 'charlie', 'delta'):
            accounts.create(login, 'LocalContracts123!')
        characters = CharacterStore(cls.seed_path)
        LocationStore(cls.seed_path)
        source = json.loads((Path(__file__).resolve().parents[1] / 'evidence/owned_pet_trial.json').read_text())
        fields = decode_pet_info(bytes.fromhex(source['packet_hex']), human_equipment=True).fields
        for login in ('alice', 'bravo', 'charlie', 'delta'):
            characters.create(login, CharacterCreateRequest(login.title().encode(), 0, (1, 0, 0, 0)))
        with closing(sqlite3.connect(cls.seed_path)) as db, db:
            # New creation supplies the current owned-pet schema and starters.
            # These route fixtures represent established, fixed two-fighter saves.
            for login in ('alice', 'bravo', 'charlie', 'delta'):
                db.execute('DELETE FROM owned_pets WHERE account=?', (login,))
                db.execute('UPDATE character_onboarding SET completed=1 WHERE account=?', (login,))
                db.execute('INSERT INTO character_locations VALUES (?,?,?,?)', (login, 3, None, None))
                for actor in (1, 2):
                    saved = {**fields, '0x8c43eb': actor, '0x8c4ab1': 100, '0x8c44a6': actor}
                    db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',
                               (login, actor, 1, encode_pet_info(PetInfo(True, saved)), encode_item_list(actor, ())))

    @classmethod
    def tearDownClass(cls):
        cls.seed_folder.cleanup()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'local.db'
        shutil.copyfile(self.seed_path, self.path)
        self.now = 1000.0
        self.clock = lambda: self.now
        self.parties = PartyStore(self.path, clock=self.clock)
        self.contracts = ContractStore(self.path, clock=self.clock, party_store=self.parties)
        self.travel = PartyTravel(self.path, self.parties, self.contracts, clock=self.clock)
        self.locations = PartyLocations(LocationStore(self.path, clock=self.clock), self.travel)

    @staticmethod
    def packet(x, y):
        return struct.pack('<Bii', 0x1b, x, y)

    def group(self, members=('alice', 'bravo'), *, ready=True):
        leader = members[0]
        self.parties.create(leader, (1, 2))
        for owner in members[1:]:
            invitation = self.parties.invite(leader, owner)
            self.parties.accept(owner, invitation['id'], (1,))
        if ready:
            for owner in members:
                self.parties.ready(owner, True)
        return self.parties.info(leader)

    def accept(self, leader='alice', template='camp'):
        return self.contracts.accept(self.parties.info(leader), leader, template, 'test-' + leader)

    @staticmethod
    def announced(character_id, route, driven):
        # Moving 1D packets from the current point toward the end of the road
        # leg the client drives next, one per route word (header, dashes); a
        # contract marker is not a public location, so the final field is 0.
        path = json.loads(route[9])
        ahead = path[leg_index(path, driven + TURN_LEAD * MAP_SPEED) + 1]
        position = point_along(path, driven)
        return tuple(movement_packet(character_id, *map(round, position), destination=tuple(map(round, ahead)),
                                     route=word) for word in route_words(path))

    def saved_locations(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM character_locations ORDER BY account').fetchall()

    def test_two_and_four_real_players_follow_one_shared_route(self):
        for members in (('alice', 'bravo'), ('alice', 'bravo', 'charlie', 'delta')):
            with self.subTest(members=members):
                room = self.group(members)
                self.travel.travel('alice', self.packet(-220, -280))
                route = self.travel.route(room['id'])
                self.assertIsNotNone(route)
                self.assertEqual(route[:2], center(3))
                self.assertEqual(route[2:4], (-220, -280))
                path = json.loads(route[9])
                self.assertEqual(path, [list(p) for p in ROADS.plan(center(3), (-220, -280))])
                self.assertAlmostEqual(route[5]-route[4], path_length(path)/MAP_SPEED)
                self.now = (route[4] + route[5]) / 2
                expected = point_along(path, path_length(path) / 2)
                for owner in members:
                    for actual, wanted in zip(self.travel.point(owner)[0], expected):
                        self.assertAlmostEqual(actual, wanted)
                    self.assertEqual(self.locations.position(owner), tuple(round(v) for v in expected))
                    self.assertIsNone(self.locations.current(owner))
                    self.assertTrue(self.locations.travelling(owner))
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM travel_party_journeys').fetchone()[0], 1)
                    self.assertEqual(db.execute('SELECT count(*) FROM map_journeys').fetchone()[0], 0)
                self.now = route[5] + 1
                self.travel.arrive('bravo')
                self.travel.travel('alice', self.packet(*center(3)))
                back = self.travel.route(room['id'])
                self.now = back[5] + 1
                self.travel.arrive('alice')
                self.parties.disband('alice')

    def test_only_leader_can_create_or_redirect_group_route(self):
        room = self.group()
        with self.assertRaises(ValueError):
            self.travel.travel('bravo', self.packet(-220, -280))
        self.assertIsNone(self.travel.route(room['id']))
        self.travel.travel('alice', self.packet(-220, -280))
        route = self.travel.route(room['id'])
        self.now += 1
        with self.assertRaises(ValueError):
            self.travel.travel('bravo', self.packet(-230, -270))
        self.assertEqual(self.travel.route(room['id']), route)
        point = self.travel.point('alice')[0]
        self.travel.travel('alice', self.packet(-230, -270))
        new = self.travel.route(room['id'])
        self.assertEqual(new[:2], point)
        self.assertEqual(new[2:4], (-230, -270))
        self.assertNotEqual(new[6], route[6])
        self.assertEqual(self.travel.point('alice')[0], self.travel.point('bravo')[0])

    def test_departure_requires_two_players_online_and_fresh_readiness(self):
        self.parties.create('alice', (1,))
        self.parties.ready('alice', True)
        with self.assertRaises(ValueError):
            self.travel.travel('alice', self.packet(-220, -280))
        invitation = self.parties.invite('alice', 'bravo')
        self.parties.accept('bravo', invitation['id'])
        with self.assertRaises(ValueError):
            self.travel.travel('alice', self.packet(-220, -280))
        self.parties.ready('alice', True)
        self.parties.ready('bravo', True)
        self.parties.set_online('bravo', False)
        with self.assertRaises(ValueError):
            self.travel.travel('alice', self.packet(-220, -280))
        self.parties.set_online('bravo', True)
        with self.assertRaises(ValueError):
            self.travel.travel('alice', self.packet(-220, -280))
        for owner in ('alice', 'bravo'):
            self.parties.ready(owner, True)
        self.travel.travel('alice', self.packet(-220, -280))
        self.assertTrue(self.locations.travelling('bravo'))

    def test_busy_malformed_and_out_of_bounds_actions_preserve_state(self):
        room = self.group()
        saved = self.saved_locations()
        for packet, busy in ((b'\x1b', False), (self.packet(-999, 0), False),
                             (self.packet(0, 0), True), (b'\x1c' + bytes(8), False)):
            with self.subTest(packet=packet, busy=busy), self.assertRaises(ValueError):
                self.travel.travel('alice', packet, busy=busy)
            self.assertEqual(self.parties.info('alice'), room)
            self.assertEqual(self.saved_locations(), saved)
            self.assertIsNone(self.travel.route(room['id']))

    def test_departure_revalidates_member_location_after_readiness(self):
        room = self.group()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE character_locations SET town_id=2 WHERE account=?', ('bravo',))
        saved = self.saved_locations()
        with self.assertRaises(ValueError):
            self.travel.travel('alice', self.packet(-220, -280))
        self.assertEqual(self.saved_locations(), saved)
        self.assertEqual(self.parties.info('alice'), room)
        self.assertIsNone(self.travel.route(room['id']))

    def test_departure_revalidates_selected_fighter_ownership_after_readiness(self):
        room = self.group()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM owned_pets WHERE account=? AND pet_id=?', ('alice', 2))
        saved = self.saved_locations()
        with self.assertRaises(ValueError):
            self.travel.travel('alice', self.packet(-220, -280))
        self.assertEqual(self.saved_locations(), saved)
        self.assertEqual(self.parties.info('alice'), room)
        self.assertIsNone(self.travel.route(room['id']))

    def test_departure_revalidates_selected_fighter_health_after_readiness(self):
        room = self.group()
        with closing(sqlite3.connect(self.path)) as db, db:
            raw = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=?',
                             ('bravo', 1)).fetchone()[0]
            pet = decode_pet_info(raw, human_equipment=True)
            raw = encode_pet_info(PetInfo(True, {**pet.fields, '0x8c4ab1': 0}))
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?', (raw, 'bravo', 1))
        saved = self.saved_locations()
        with self.assertRaises(ValueError):
            self.travel.travel('alice', self.packet(-220, -280))
        self.assertEqual(self.saved_locations(), saved)
        self.assertEqual(self.parties.info('alice'), room)
        self.assertIsNone(self.travel.route(room['id']))

    def test_city_arrival_updates_every_member_and_allows_new_assembly(self):
        room = self.group()
        self.travel.travel('alice', self.packet(*center(2)))
        route = self.travel.route(room['id'])
        self.assertEqual(route[7], 2)
        self.now = route[5] - 0.01
        self.assertFalse(self.travel.arrive('bravo'))
        self.now = route[5]
        self.assertTrue(self.travel.arrive('bravo'))
        self.assertFalse(self.travel.arrive('alice'))
        self.assertIsNone(self.travel.route(room['id']))
        arrived = self.parties.info('alice')
        self.assertEqual(arrived['state'], 'city')
        self.assertEqual(arrived['town_id'], 2)
        self.assertFalse(any(member['ready'] for member in arrived['members']))
        for owner in ('alice', 'bravo'):
            self.assertEqual(self.locations.current(owner), 2)
            self.assertEqual(self.locations.position(owner), center(2))
            self.parties.ready(owner, True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE character_locations SET town_id=?,x=?,y=? WHERE account=?',
                       (2, *center(2), 'charlie'))
        invitation = self.parties.invite('alice', 'charlie')
        self.parties.accept('charlie', invitation['id'])
        self.assertEqual(len(self.parties.info('alice')['members']), 3)

    def test_private_contract_target_is_shared_only_with_its_exact_roster(self):
        room = self.group()
        contract = self.accept()
        target = contract['target']
        self.assertEqual(self.contracts.target_for('alice'), target)
        self.assertEqual(self.contracts.target_for('bravo'), target)
        self.assertIsNone(self.contracts.target_for('charlie'))
        self.travel.travel('alice', self.packet(target['bounds'][0] + 1, target['bounds'][1] + 1))
        route = self.travel.route(room['id'])
        self.assertEqual(route[2:4], (target['x'], target['y']))
        self.assertEqual(route[8], contract['id'])
        self.assertIsNone(route[7])
        self.assertEqual(self.contracts.get(contract['id'])['state'], 'travelling')
        self.now = route[5]
        self.assertTrue(self.travel.arrive('bravo'))
        self.assertEqual(self.contracts.get(contract['id'])['state'], 'arrived')
        self.assertEqual(self.parties.info('alice')['state'], 'at_target')
        for owner in ('alice', 'bravo'):
            self.assertIsNone(self.locations.current(owner))
            self.assertEqual(self.locations.position(owner), (target['x'], target['y']))
        self.assertFalse(self.travel.arrive('alice'))

    def test_reaching_another_partys_hidden_coordinates_does_not_admit_its_contract(self):
        first = self.group()
        foreign = self.group(('charlie', 'delta'))
        contract = self.accept('charlie', 'depot')
        target = contract['target']
        self.travel.travel('alice', self.packet(target['x'], target['y']))
        route = self.travel.route(first['id'])
        self.assertIsNone(route[8])
        self.assertIsNone(route[7])
        self.now = route[5]
        self.travel.arrive('alice')
        self.assertIsNone(self.contracts.target_for('alice'))
        self.assertIsNone(self.contracts.active(first['id']))
        self.assertEqual(self.contracts.active(foreign['id'])['state'], 'accepted')
        self.assertEqual(self.parties.info('charlie')['state'], 'city')

    def test_restart_and_reconnect_keep_route_position_destination_and_contract(self):
        room = self.group()
        contract = self.accept()
        target = contract['target']
        self.travel.travel('alice', self.packet(target['x'], target['y']))
        route = self.travel.route(room['id'])
        self.now += 3
        position = self.travel.point('alice')[0]
        self.parties.set_online('bravo', False)
        reopened = PartyStore(self.path, clock=self.clock)
        reopened.reset_online()
        contracts = ContractStore(self.path, clock=self.clock, party_store=reopened)
        travel = PartyTravel(self.path, reopened, contracts, clock=self.clock)
        locations = PartyLocations(LocationStore(self.path, clock=self.clock), travel)
        self.assertEqual(travel.route(room['id']), route)
        self.assertEqual(travel.point('bravo')[0], position)
        reopened.set_online('bravo', True)
        packets = locations.resume('bravo', 202)
        self.assertEqual(packets[0][0], 0xf0)
        self.assertEqual(packets[1], encode_open_map_view())
        self.assertEqual(packets[2:], self.announced(202, route, 3 * MAP_SPEED))
        self.assertEqual(locations.refresh('bravo', 202), ())
        self.now = route[5] + 1
        travel.arrive('bravo')
        self.assertEqual(contracts.get(contract['id'])['state'], 'arrived')
        self.assertEqual(travel.point('alice')[0], travel.point('bravo')[0])

    def test_route_creation_rolls_back_all_members_and_contract_on_transition_failure(self):
        room = self.group()
        contract = self.accept()
        saved = self.saved_locations()
        with patch.object(self.contracts, 'transition', side_effect=RuntimeError('injected contract write failure')):
            with self.assertRaises(RuntimeError):
                self.travel.travel('alice', self.packet(contract['target']['x'], contract['target']['y']))
        self.assertEqual(self.saved_locations(), saved)
        self.assertEqual(self.parties.info('alice'), room)
        self.assertEqual(self.contracts.get(contract['id'])['state'], 'accepted')
        self.assertIsNone(self.travel.route(room['id']))

    def test_arrival_rolls_back_locations_route_and_state_on_contract_failure(self):
        room = self.group()
        contract = self.accept()
        self.travel.travel('alice', self.packet(contract['target']['x'], contract['target']['y']))
        route = self.travel.route(room['id'])
        room = self.parties.info('alice')
        saved = self.saved_locations()
        self.now = route[5] + 1
        with patch.object(self.contracts, 'transition', side_effect=RuntimeError('injected arrival failure')):
            with self.assertRaises(RuntimeError):
                self.travel.arrive('bravo')
        self.assertEqual(self.saved_locations(), saved)
        self.assertEqual(self.parties.info('alice'), room)
        self.assertEqual(self.travel.route(room['id']), route)
        self.assertEqual(self.contracts.get(contract['id'])['state'], 'travelling')
        self.assertTrue(self.travel.arrive('alice'))
        self.assertEqual(self.contracts.get(contract['id'])['state'], 'arrived')

    def test_full_route_creation_participates_in_outer_gameplay_rollback(self):
        room = self.group()
        saved = self.saved_locations()
        with self.assertRaises(RuntimeError):
            with transaction(self.path):
                self.travel.travel('alice', self.packet(-220, -280))
                self.assertIsNotNone(self.travel.route(room['id']))
                raise RuntimeError('injected enclosing action failure')
        self.assertEqual(self.saved_locations(), saved)
        self.assertEqual(self.parties.info('alice'), room)
        self.assertIsNone(self.travel.route(room['id']))

    def test_session_adapter_projects_route_packets_and_final_stop_for_each_client(self):
        room = self.group()
        self.locations.refresh('alice', 101)
        self.locations.refresh('bravo', 202)
        packets = self.locations.travel('alice', self.packet(-220, -280), 101)
        self.assertEqual([packet[0] for packet in packets[:3]], [0xf0, 0xee, 0x1d])
        other = self.locations.refresh('bravo', 202)
        self.assertEqual([packet[0] for packet in other[:3]], [0xf0, 0xee, 0x1d])
        self.assertEqual(packets[1], encode_open_map_view())
        self.assertEqual(other[1], encode_open_map_view())
        route = self.travel.route(room['id'])
        self.assertEqual(packets[2:], self.announced(101, route, 0))
        self.assertEqual(other[2:], self.announced(202, route, 0))
        # Later refreshes send only the next turn, never the dashes again.
        self.now += .5
        for owner, character_id in (('alice', 101), ('bravo', 202)):
            for packet in self.locations.refresh(owner, character_id):
                self.assertEqual(struct.unpack_from('<I', packet, 13)[0], 0)
        self.now = route[5] + 1
        for owner, character_id in (('alice', 101), ('bravo', 202)):
            packets = self.locations.refresh(owner, character_id)
            self.assertEqual(packets, (stop_packet(character_id, -220, -280),))
            self.assertEqual(self.locations.refresh(owner, character_id), ())

    def test_reconnect_at_contract_target_opens_map_before_stop_without_repeated_departure(self):
        room = self.group()
        contract = self.accept()
        target = contract['target']
        self.travel.travel('alice', self.packet(target['x'], target['y']))
        self.now = self.travel.route(room['id'])[5] + 1
        self.travel.arrive('bravo')
        saved = self.saved_locations()
        adapter = PartyLocations(LocationStore(self.path, clock=self.clock), self.travel)
        for owner, character_id in (('alice', 101), ('bravo', 202)):
            packets = adapter.resume(owner, character_id)
            self.assertEqual([packet[0] for packet in packets], [0xf0, 0xee, 0x1e])
            self.assertEqual(packets[1], encode_open_map_view())
            self.assertEqual(packets[2], stop_packet(character_id, target['x'], target['y']))
            self.assertEqual(adapter.refresh(owner, character_id), ())
        self.assertEqual(self.saved_locations(), saved)
        self.assertEqual(self.contracts.get(contract['id'])['state'], 'arrived')

    def test_return_to_city_restores_native_controls_before_opening_city_for_both_members(self):
        from tio.protocol.system_message import encode_current_town, encode_open_town_view
        room = self.group()
        self.locations.travel('alice', self.packet(-220, -280), 101)
        self.locations.refresh('bravo', 202)
        self.now = self.travel.route(room['id'])[5] + 1
        self.locations.refresh('alice', 101)
        self.locations.refresh('bravo', 202)
        self.locations.travel('alice', self.packet(*center(3)), 101)
        self.locations.refresh('bravo', 202)
        self.now = self.travel.route(room['id'])[5] + 1
        for owner, character_id in (('alice', 101), ('bravo', 202)):
            packets = self.locations.refresh(owner, character_id)
            self.assertEqual(packets[0], stop_packet(character_id, *center(3)))
            self.assertEqual(packets[-3:], (encode_current_town(3),
                encode_restore_city_controls(), encode_open_town_view()))
            self.assertEqual(self.locations.refresh(owner, character_id), ())
        self.assertEqual(self.parties.info('alice')['state'], 'city')


if __name__ == '__main__':
    unittest.main()
