"""Request-local reuse must not retain another account's mutable game state."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import patch

import test_ability_learning as ability_fixture
import test_party_travel as party_fixture
from tio import passive_stats,weapon_proficiency,party_travel,character_identity
from tio.characters import CharacterStore
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.abilities import AbilityEntry,encode_abilities
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.pet_info import decode_pet_info,encode_pet_info


class RosterReadTests(unittest.TestCase):
    setUp=ability_fixture.AbilityLearningTests.setUp

    def rows(self,db,account='alice'):
        return db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)).fetchall()

    def profiles(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            for owner in (1,2):
                db.execute('INSERT OR REPLACE INTO ability_states VALUES (?,?,1,?)',('alice',owner,encode_abilities(owner,())))

    def test_batch_matches_single_projection_with_one_rule_load_and_no_inventory_reread(self):
        self.profiles()
        with closing(sqlite3.connect(self.path)) as db:
            rows=self.rows(db)
            expected=[(i,h,passive_stats.project_saved_pet(db,'alice',i,p,bool(h)),inv) for i,h,p,inv in rows]
            statements=[];db.set_trace_callback(statements.append)
            with patch.object(weapon_proficiency,'ProficiencyRules',wraps=weapon_proficiency.ProficiencyRules) as rules,patch.object(passive_stats,'_catalog',wraps=passive_stats._catalog) as catalog:
                result=passive_stats.project_saved_roster(db,'alice',rows)
            self.assertEqual(result,expected);self.assertEqual(rules.call_count,1);self.assertEqual(catalog.call_count,1)
            self.assertFalse(any('SELECT inventory_packet' in s for s in statements))
            self.assertEqual(sum('sqlite_master' in s for s in statements),1)

    def test_next_request_and_overlapping_account_pet_ids_are_fresh(self):
        store=OwnedPetStore(self.path);before=store.list('alice');bob=store.list('bob')
        with closing(sqlite3.connect(self.path)) as db,db:
            raw=self.rows(db)[0][2];pet=decode_pet_info(raw,human_equipment=True)
            changed=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4ab1':1}))
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(changed,'alice'))
            db.execute('INSERT OR REPLACE INTO ability_states VALUES (?,1,1,?)',('alice',encode_abilities(1,(AbilityEntry(1,1,0,1),))))
        after=store.list('alice')
        self.assertNotEqual(after,before);self.assertEqual(store.list('bob'),bob)
        self.assertEqual(decode_pet_info(after[0][1],human_equipment=True).fields['0x8c4ab1'],1)
        self.assertGreater(decode_pet_info(after[0][1],human_equipment=True).fields['0x8c4a07'],decode_pet_info(before[0][1],human_equipment=True).fields['0x8c4a07'])

    def test_corrupt_profile_rejected_and_sync_writes_rolled_back(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT OR REPLACE INTO ability_states VALUES (?,1,1,?)',('alice',encode_abilities(99,())))
            before=db.execute('SELECT * FROM owned_pets ORDER BY account,pet_id').fetchall()
        with self.assertRaisesRegex(ValueError,'Invalid saved skill profile'):OwnedPetStore(self.path).list('alice')
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT * FROM owned_pets ORDER BY account,pet_id').fetchall(),before)

    def test_empty_and_legacy_rosters_do_not_require_ability_schema(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('DROP TABLE ability_states');rows=self.rows(db)
            expected=[(i,h,passive_stats.project_saved_pet(db,'alice',i,p,bool(h)),inv) for i,h,p,inv in rows]
            self.assertEqual(passive_stats.project_saved_roster(db,'alice',rows),expected)
            with patch.object(weapon_proficiency,'ProficiencyRules',side_effect=AssertionError('Empty roster')):
                self.assertEqual(passive_stats.project_saved_roster(db,'alice',[]),[])


class PartyReadTests(unittest.TestCase):
    setUpClass=classmethod(party_fixture.PartyTravelTests.setUpClass.__func__)
    tearDownClass=classmethod(party_fixture.PartyTravelTests.tearDownClass.__func__)
    setUp=party_fixture.PartyTravelTests.setUp
    group=party_fixture.PartyTravelTests.group
    packet=staticmethod(party_fixture.PartyTravelTests.packet)

    def test_four_members_one_join_preserves_order_and_empty_selection(self):
        room=self.group(('alice','bravo','charlie','delta'))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('DELETE FROM travel_party_selected WHERE owner=?',('bravo',))
            statements=[];db.set_trace_callback(statements.append)
            snapshot=self.parties.snapshot(room['id'],connection=db)
        self.assertEqual([m['owner'] for m in snapshot['members']],['alice','bravo','charlie','delta'])
        self.assertEqual([m['selected'] for m in snapshot['members']],[(1,2),(),(1,),(1,)])
        self.assertEqual(sum(s.lstrip().upper().startswith('SELECT') for s in statements),2)

    def test_idle_city_refresh_uses_one_info_and_no_writer(self):
        self.group()
        with patch.object(self.parties,'info',wraps=self.parties.info) as info,patch.object(party_travel,'transaction',side_effect=AssertionError('Idle refresh must be read-only')):
            self.assertEqual(self.locations.refresh('alice',101),())
        self.assertEqual(info.call_count,1)

    def test_travelling_refresh_uses_one_info_and_no_writer_until_due(self):
        self.group();self.travel.travel('alice',self.packet(-220,-280))
        self.now+=1
        with patch.object(self.parties,'info',wraps=self.parties.info) as info,patch.object(party_travel,'transaction',side_effect=AssertionError('Not due')):
            self.locations.refresh('bravo',202)
        self.assertEqual(info.call_count,1)
        self.assertIsNone(self.locations.current('bravo'))

    def test_due_hint_cannot_arrive_a_route_that_changed_before_writer(self):
        room=self.group();self.travel.travel('alice',self.packet(-220,-280))
        self.now=self.travel.route(room['id'])[5]+1;original=self.travel.arrive
        def changed(owner):
            with transaction(self.path) as db:db.execute('UPDATE travel_party_journeys SET arrives=? WHERE party_id=?',(self.now+100,room['id']))
            return original(owner)
        with patch.object(self.travel,'arrive',side_effect=changed):self.locations.refresh('bravo',202)
        self.assertEqual(self.parties.info('bravo')['state'],'travelling')
        self.assertTrue(self.travel.route(room['id']));self.assertIsNone(self.locations.current('bravo'))

    def test_alias_identity_uses_supplied_snapshot_and_still_rejects_missing_mapping(self):
        CharacterStore(self.path).create('alice',CharacterCreateRequest(b'AliceSecond',0,(1,0,0,0)))
        owner=character_identity.alias('alice',2)
        with transaction(self.path) as db:
            with patch.object(character_identity,'connect',side_effect=AssertionError('Second connection')):
                self.assertIsNone(self.parties.info(owner,connection=db))
                db.execute('DELETE FROM character_identities WHERE owner=?',(owner,))
                with self.assertRaises(ValueError):self.parties.info(owner,connection=db)
