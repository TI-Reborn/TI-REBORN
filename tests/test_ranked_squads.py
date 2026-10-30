"""Original C6 packets with two independent human accounts and saved squads."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import struct
import unittest

from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import ranked
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
import test_ranked as fixture
from battle_exit_fixture import place_squad_at_edge


def join(ids):
    return b'\xc6\x21'+bytes(2)+struct.pack('<I',len(ids))+b''.join(struct.pack('<II',i,0)+b'\0' for i in ids)


class RankedSquadTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RankedServerTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.case=self.base.case;self.path=self.base.path;self.hub=self.base.hub
        for session in self.case.sessions[:2]:
            store=OwnedPetStore(self.path);raw=store.list(session.account)[0][1]
            pet=decode_pet_info(raw,human_equipment=True)
            for identity in (2,3,4):
                # The fourth fighter is a reserve outside the old three-slot
                # barracks selection. Only the native C6 packet selects it.
                fields={**pet.fields,'0x8c43eb':identity,'0x8c44a6':0}
                store.ensure(session.account,encode_pet_info(replace(pet,fields=fields)),encode_item_list(identity,()),human=True)

    def start(self,count=4,journal=False):
        before={s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]}
        if journal:self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:1000)
        self.case.send(0,join(range(1,count+1)));self.assertFalse(self.hub.battles)
        replies=self.case.send(1,join(range(1,count+1)))
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2])
        self.assertIn(owners[0],self.hub.battles,[p[13:-2].decode('utf-16-le',errors='replace') for p in replies if p[:5]==b'\xf0\x8a\x01\x00\x00'])
        battle=self.hub.battles[owners[0]]
        self.assertEqual(len(battle['bots']),8-2*count);self.assertEqual(len(battle['humans']),2)
        self.assertEqual(battle['field'].scene_metadata['profile'],'trueskill_contest')
        self.assertEqual(battle['points'].positions,tuple(battle['field'].scene_metadata['control_points']))
        self.assertEqual(len(battle['field']._actors),8)
        self.assertEqual(battle['room'].request.soldiers_count_01,4)
        self.assertTrue(any(p[:2]==b'\xc6\x04' for p in replies))
        self.assertEqual(before,{s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]})
        for index in (0,1):self.case.send(index,b'\x36')
        self.hub.tick()
        return owners,battle

    def test_four_real_saved_fighters_scene_and_native_exit_updates_only_two_players_once(self):
        owners,battle=self.start()
        for owner in owners:
            local={battle['field'].combat.storage_ids[i] for i in battle['field'].actor_ids(owner)}
            self.assertEqual(local,{1,2,3,4})
        place_squad_at_edge(battle['field'],owners[0])
        self.case.send(0,b'\x2a\x01');self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,wins,losses FROM ranked_players ORDER BY account').fetchall(),
                             [('alice',0,1),('bob',1,0)])
            self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone(),(1,))
        old=ranked.snapshot(self.path,'bob');self.hub.tick();self.assertEqual(old,ranked.snapshot(self.path,'bob'))

    def test_three_selected_native_fighters_are_supported_as_well(self):
        self.start(count=3)

    def test_mismatched_counts_start_without_trimming_and_late_cancel_preserves_match(self):
        self.case.send(0,join((1,2,3,4)))
        self.case.send(1,join((1,2,3)))
        battle=next(iter(self.hub.battles.values()));self.assertEqual(len(battle['field']._actors),8)
        self.assertEqual(len(battle['bots']),1);self.assertFalse(self.hub.ranked_waiting)
        self.case.send(1,b'\xc6\x23');self.assertFalse(battle['finished'])

    def test_two_character_slots_of_same_login_cannot_be_ranked_opponents(self):
        from tio.character_identity import alias,initialise
        from wallet_fixture import fund_wallet
        owner=alias('alice',2)
        with closing(sqlite3.connect(self.path)) as db,db:
            initialise(db);db.execute('INSERT INTO character_identities VALUES (?,?,?)',('alice',2,owner))
        fund_wallet(self.path,owner,credits=10_000,gold=0)
        for identity,pet,inventory in OwnedPetStore(self.path).list('bob'):
            OwnedPetStore(self.path).ensure(owner,pet,inventory,human=True)
        with closing(sqlite3.connect(self.path)) as db,db:
            self.case.sessions[1].locations._save(db,owner,2,-367,-424)
        self.case.sessions[1].account=owner
        self.case.send(0,join((1,2,3,4)));self.case.send(1,join((1,2,3,4)))
        self.assertFalse(self.hub.battles);self.assertEqual(len(self.hub.ranked_waiting),2)

    def test_foreign_wounded_out_of_range_or_changed_fourth_pet_cannot_enter(self):
        self.assertTrue(any(p[0]==0xf0 for p in self.case.send(0,join((1,2,3,999)))))
        store=OwnedPetStore(self.path);raw=store.list('alice')[3][1]
        parsed=decode_pet_info(raw,human_equipment=True)
        for fields in ({'0x8c4ab1':1},{'0x8c4aef':3}):
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=4",
                           (encode_pet_info(replace(parsed,fields={**parsed.fields,**fields})),))
            self.assertTrue(any(p[0]==0xf0 for p in self.case.send(0,join((1,2,3,4)))))
            self.assertFalse(self.hub.battles)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=4",(raw,))
        self.case.send(0,join((1,2,3,4)))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=4",
                       (encode_pet_info(replace(parsed,fields={**parsed.fields,'0x8c4aef':7})),))
        self.case.send(1,join((1,2,3,4)));self.assertFalse(self.hub.battles)

    def test_four_fighters_checkpoint_restart_disconnect_result_once(self):
        owners,battle=self.start(journal=True)
        restored=TeamArena(clock=lambda:self.case.now);restored.journal=BattleJournal(restored,self.path,wall=lambda:1001)
        self.assertEqual(restored.journal.recover(),[battle['match_id']])
        active=restored.battles[owners[0]];self.assertEqual(len(active['field']._actors),8)
        self.case.hub=restored
        for index in (0,1):self.assertTrue(restored.resume(self.case.sessions[index]));self.case.send(index,b'\x36')
        place_squad_at_edge(active['field'],owners[0])
        self.case.send(0,b'\x2a\x01');restored.tick();restored.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone(),(1,))
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone(),(2,))


if __name__=='__main__':unittest.main()
