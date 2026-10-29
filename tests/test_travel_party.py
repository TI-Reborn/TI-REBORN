import concurrent.futures
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio import character_identity
from tio.characters import CharacterStore
from tio.db_transaction import transaction
from tio.locations import LocationStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import PetInfo, decode_pet_info, encode_pet_info
from tio.travel_party import PartyStore


class TravelPartyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'state.db'
        self.now = 1000.0
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE accounts(login TEXT PRIMARY KEY,salt BLOB,digest BLOB,iterations INTEGER)')
            db.executemany('INSERT INTO accounts VALUES (?,X\'01\',X\'02\',600000)',
                           ((login,) for login in ('alice', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot')))
        self.characters = CharacterStore(self.path)
        LocationStore(self.path)
        seed = json.loads((Path(__file__).resolve().parents[1] / 'evidence/owned_pet_trial.json').read_text())
        self.fields = decode_pet_info(bytes.fromhex(seed['packet_hex']), human_equipment=True).fields
        for login in ('alice', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot'):
            self.characters.create(login, CharacterCreateRequest(login.title().encode(), 0, (1, 0, 0, 0)))
            self.seed_pets(login)
        # Creation now initializes the real three-column wallet and starter
        # roster. Party tests use established city characters with fixed saves.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE wallets SET credits=? WHERE account=?', (12345, 'alice'))
        self.party = PartyStore(self.path, clock=lambda: self.now, invitation_ttl=120)

    def seed_pets(self, owner):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR REPLACE INTO character_locations VALUES (?,?,?,?)', (owner, 3, None, None))
            db.execute('UPDATE character_onboarding SET completed=1 WHERE account=?', (owner,))
            for identity in (1, 2, 3):
                fields = {**self.fields, '0x8c43eb': identity, '0x8c4ab1': 100, '0x8c44a6': 1 if identity == 1 else 0}
                db.execute('INSERT OR REPLACE INTO owned_pets VALUES (?,?,?,?,?)',
                           (owner, identity, 1, encode_pet_info(PetInfo(True, fields)), encode_item_list(identity, ())))

    def alias(self, login):
        self.characters.create(login, CharacterCreateRequest((login.title() + 'Two').encode(), 0, (1, 0, 0, 0)))
        owner = character_identity.alias(login, 2)
        self.seed_pets(owner)
        return owner

    def join(self, owner, leader='alice', selected=(1,)):
        invitation = self.party.invite(leader, owner)
        return self.party.accept(owner, invitation['id'], selected)

    @staticmethod
    def member(room, owner):
        return next(member for member in room['members'] if member['owner'] == owner)

    def test_requires_registered_login_saved_character_and_owned_alias(self):
        for owner in ('missing', '@character:alice:2', '', None):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                self.party.create(owner)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO characters VALUES (?,?,?,?,?)', ('unregistered', 1, b'Unknown', 'unknown', b'raw'))
        with self.assertRaises(ValueError):
            self.party.create('unregistered')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM characters WHERE account=?', ('delta',))
        with self.assertRaises(ValueError):
            self.party.create('delta')
        self.assertIsNone(self.party.info('alice'))

    def test_one_human_login_cannot_join_twice_or_switch_save_owner(self):
        other = self.alias('alice')
        room = self.party.create(other, (2, 1))
        self.assertEqual(room['leader'], other)
        self.assertEqual(self.member(room, other)['login'], 'alice')
        self.assertTrue(self.party.blocked_login('alice'))
        self.assertIsNone(self.party.info('alice'))
        for call in (lambda: self.party.create('alice'), lambda: self.party.select('alice', (3,)),
                     lambda: self.party.invite(other, 'alice')):
            with self.assertRaises(ValueError):
                call()
        self.party.disband(other)
        self.assertFalse(self.party.blocked_login('alice'))

    def test_selection_has_owned_live_unique_actor_ids_and_is_atomic(self):
        initial = self.party.create('alice')
        self.assertEqual(self.member(initial, 'alice')['selected'], (1,))
        self.party.ready('alice', True)
        initial = self.party.info('alice')
        for ids in ((), (1, 1), (True,), ('1',), (-1,), (1, 2, 3), (999,)):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.party.select('alice', ids)
            self.assertEqual(self.party.info('alice'), initial)
        fields = {**self.fields, '0x8c43eb': 3, '0x8c4ab1': 0}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=3',
                       (encode_pet_info(PetInfo(True, fields)), 'alice'))
        with self.assertRaises(ValueError):
            self.party.select('alice', (3,))
        room = self.party.select('alice', (2, 1))
        self.assertEqual(self.member(room, 'alice')['selected'], (2, 1))
        self.assertFalse(self.member(room, 'alice')['ready'])

    def test_invitation_requires_target_consent_exact_character_and_is_consumed(self):
        other = self.alias('bravo')
        self.party.create('alice')
        invitation = self.party.invite('alice', other)
        self.assertEqual(len(self.party.info('alice')['members']), 1)
        self.assertEqual(self.party.invitations('bravo'), ())
        self.assertEqual(self.party.invitations(other), (invitation,))
        for wrong in ('charlie', 'bravo'):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.party.accept(wrong, invitation['id'])
        room = self.party.accept(other, invitation['id'], (1, 2))
        self.assertEqual(len(room['members']), 2)
        self.assertEqual(self.member(room, other)['selected'], (1, 2))
        self.assertEqual(self.party.invitations(other), ())
        with self.assertRaises(ValueError):
            self.party.accept(other, invitation['id'])

    def test_invitation_ttl_renew_decline_and_wrong_recipient(self):
        self.party.create('alice')
        invitation = self.party.invite('alice', 'bravo')
        self.now += 120
        self.assertEqual(self.party.invitations('bravo'), ())
        with self.assertRaises(ValueError):
            self.party.accept('bravo', invitation['id'])
        renewed = self.party.invite('alice', 'bravo')
        self.assertEqual(renewed['id'], invitation['id'])
        self.assertGreater(renewed['expires_at'], invitation['expires_at'])
        with self.assertRaises(ValueError):
            self.party.decline('charlie', renewed['id'])
        self.assertTrue(self.party.decline('bravo', renewed['id']))
        self.assertFalse(self.party.decline('bravo', renewed['id']))

    def test_assembly_rechecks_same_city_and_no_journey(self):
        self.party.create('alice')
        invitation = self.party.invite('alice', 'bravo')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE character_locations SET town_id=2 WHERE account=?', ('bravo',))
        with self.assertRaises(ValueError):
            self.party.accept('bravo', invitation['id'])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE character_locations SET town_id=3 WHERE account=?', ('bravo',))
            db.execute('INSERT INTO map_journeys(account,x,y,tx,ty,started,arrives) VALUES (?,?,?,?,?,?,?)', ('bravo', 0, 0, 1, 1, 1000, 1010))
        with self.assertRaises(ValueError):
            self.party.accept('bravo', invitation['id'])
        with self.assertRaises(ValueError):
            self.party.create('bravo')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM map_journeys WHERE account=?', ('bravo',))
            db.execute('UPDATE character_locations SET town_id=-1 WHERE account=?', ('alice',))
        with self.assertRaises(ValueError):
            self.party.accept('bravo', invitation['id'])
        self.assertIsNone(self.party.info('bravo'))

    def test_only_leader_can_manage_and_leadership_invalidates_invites(self):
        self.party.create('alice')
        self.join('bravo')
        invitation = self.party.invite('alice', 'charlie')
        for call in (lambda: self.party.invite('bravo', 'delta'), lambda: self.party.kick('bravo', 'alice'),
                     lambda: self.party.transfer('bravo', 'alice'), lambda: self.party.disband('bravo')):
            with self.assertRaises(ValueError):
                call()
        self.party.ready('alice', True)
        self.party.ready('bravo', True)
        with self.assertRaises(ValueError):
            self.party.leave('alice')
        room = self.party.transfer('alice', 'bravo')
        self.assertEqual(room['leader'], 'bravo')
        self.assertFalse(any(member['ready'] for member in room['members']))
        with self.assertRaises(ValueError):
            self.party.accept('charlie', invitation['id'])
        room = self.party.leave('alice')
        self.assertEqual([member['owner'] for member in room['members']], ['bravo'])
        self.assertIsNone(self.party.leave('bravo'))

    def test_membership_and_selection_changes_require_fresh_readiness(self):
        self.party.create('alice', (1,))
        self.party.ready('alice', True)
        room = self.join('bravo')
        self.assertFalse(any(member['ready'] for member in room['members']))
        for owner in ('alice', 'bravo'):
            self.party.ready(owner, True)
        room = self.party.select('bravo', (2,))
        self.assertFalse(any(member['ready'] for member in room['members']))
        self.party.ready('alice', True)
        room = self.party.kick('alice', 'bravo')
        self.assertFalse(self.member(room, 'alice')['ready'])
        self.assertFalse(self.party.blocked_login('bravo'))

    def test_disconnect_reopen_and_explicit_restart_revoke_consent(self):
        self.party.create('alice', (2, 1))
        self.join('bravo')
        self.party.ready('alice', True)
        self.party.ready('bravo', True)
        previous = self.party.info('alice')
        reopened = PartyStore(self.path, clock=lambda: self.now)
        self.assertEqual(reopened.info('alice'), previous)
        room = reopened.set_online('bravo', False)
        self.assertEqual(self.member(room, 'alice')['selected'], (2, 1))
        self.assertFalse(self.member(room, 'bravo')['online'])
        self.assertFalse(any(member['ready'] for member in room['members']))
        with self.assertRaises(ValueError):
            reopened.ready('bravo', True)
        room = reopened.set_online('bravo', True)
        self.assertFalse(self.member(room, 'bravo')['ready'])
        reopened.ready('alice', True)
        reopened.reset_online()
        room = reopened.info('alice')
        self.assertFalse(any(member['online'] or member['ready'] for member in room['members']))
        self.assertEqual(len(room['members']), 2)

    def test_state_compare_and_set_and_active_roster_is_locked(self):
        room = self.party.create('alice')
        self.join('bravo')
        room = self.party.change_state(room['id'], 'travelling', 'city')
        with self.assertRaises(ValueError):
            self.party.change_state(room['id'], 'battle', 'city')
        self.assertEqual(self.party.info('alice'), room)
        for call in (lambda: self.party.select('alice', (2,)), lambda: self.party.kick('alice', 'bravo'),
                     lambda: self.party.transfer('alice', 'bravo'), lambda: self.party.leave('bravo'),
                     lambda: self.party.disband('alice'), lambda: self.party.invite('alice', 'delta')):
            with self.assertRaises(ValueError):
                call()
        room = self.party.change_state(room['id'], 'at_target', 'travelling')
        self.party.ready('bravo', True)
        room = self.party.change_state(room['id'], 'city', 'at_target')
        self.assertFalse(any(member['ready'] for member in room['members']))

    def test_departure_validator_uses_live_saved_location_route_and_selection(self):
        room = self.party.create('alice', (1,))
        with self.assertRaises(ValueError):
            self.party.validate_departure(room['id'])
        self.join('bravo')
        with self.assertRaises(ValueError):
            self.party.validate_departure(room['id'])
        for owner in ('alice', 'bravo'):
            self.party.ready(owner, True)
        room = self.party.info('alice')
        self.assertEqual(self.party.validate_departure(room['id']), room)
        with transaction(self.path) as db:
            self.assertEqual(self.party.validate_departure(room['id'], db), room)
            db.execute('INSERT INTO map_journeys(account,x,y,tx,ty,started,arrives) VALUES (?,?,?,?,?,?,?)', ('bravo', 0, 0, 1, 1, 1000, 1010))
            with self.assertRaises(ValueError):
                self.party.validate_departure(room['id'], db)
            db.execute('DELETE FROM map_journeys WHERE account=?', ('bravo',))
            db.execute('DELETE FROM owned_pets WHERE account=? AND pet_id=?', ('bravo', 1))
            with self.assertRaises(ValueError):
                self.party.validate_departure(room['id'], db)
        self.assertEqual(self.party.info('alice'), room)

    def test_concurrent_invitation_accepts_cannot_exceed_four_players(self):
        self.party.create('alice')
        self.join('bravo')
        self.join('charlie')
        invitations = {owner: self.party.invite('alice', owner)['id'] for owner in ('delta', 'echo', 'foxtrot')}

        def accept(owner):
            try:
                PartyStore(self.path, clock=lambda: self.now).accept(owner, invitations[owner])
                return True
            except ValueError:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = tuple(pool.map(accept, invitations))
        self.assertEqual(sum(results), 1)
        room = self.party.info('alice')
        self.assertEqual(len(room['members']), 4)
        self.assertEqual(len({member['login'] for member in room['members']}), 4)

    def test_concurrent_alias_joins_cannot_put_same_login_in_two_groups(self):
        alias = self.alias('charlie')
        first = self.party.create('alice')
        second = self.party.create('bravo')
        invitations = [('charlie', self.party.invite('alice', 'charlie')['id']),
                       (alias, self.party.invite('bravo', alias)['id'])]

        def accept(invitation):
            try:
                PartyStore(self.path, clock=lambda: self.now).accept(*invitation)
                return True
            except ValueError:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(accept, invitations))
        self.assertEqual(sum(results), 1)
        joined = self.party.snapshot(first['id'])['members'] + self.party.snapshot(second['id'])['members']
        self.assertEqual(sum(member['login'] == 'charlie' for member in joined), 1)

    def test_actions_participate_in_outer_transaction_and_rollback_together(self):
        with self.assertRaises(RuntimeError):
            with transaction(self.path) as db:
                room = self.party.create('alice')
                self.join('bravo')
                self.party.change_state(room['id'], 'travelling', 'city', db)
                db.execute('UPDATE wallets SET credits=1 WHERE account=?', ('alice',))
                self.assertEqual(self.party.info('bravo')['state'], 'travelling')
                raise RuntimeError('fail shared gameplay action')
        self.assertIsNone(self.party.info('alice'))
        self.assertIsNone(self.party.info('bravo'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT credits FROM wallets WHERE account=?', ('alice',)).fetchone()[0], 12345)

    def test_group_operations_preserve_all_existing_account_save_and_inventory_rows(self):
        tables = ('accounts', 'characters', 'character_identities', 'owned_pets', 'character_locations', 'map_journeys', 'wallets')

        def snapshot():
            with closing(sqlite3.connect(self.path)) as db:
                return {table: db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall() for table in tables}

        before = snapshot()
        self.party.create('alice', (2,))
        self.join('bravo', selected=(3,))
        self.party.ready('bravo', True)
        self.party.select('alice', (1, 3))
        self.party.set_online('bravo', False)
        self.party.transfer('alice', 'bravo')
        self.party.disband('bravo')
        self.assertEqual(snapshot(), before)
        with closing(sqlite3.connect(self.path)) as db:
            for table in ('travel_party_groups', 'travel_party_members', 'travel_party_selected', 'travel_party_invitations'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
