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
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
import test_ranked as fixture


def join(ids):
    return b'\xc6\x21'+bytes(2)+struct.pack('<I',len(ids))+b''.join(struct.pack('<II',i,0)+b'\0' for i in ids)


def move_to_exit(battle, owner):
    field=battle['field']
    for y,identity in enumerate(field.actor_ids(owner),2):
        field._actors[identity]=replace(field.actor(identity),x=1,y=y)


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

    def start(self,journal=False):
        before={s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]}
        if journal:self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:1000)
        self.case.send(0,join((1,2,3,4)));self.assertFalse(self.hub.battles)
        replies=self.case.send(1,join((1,2,3,4)))
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2])
        self.assertIn(owners[0],self.hub.battles,[p[13:-2].decode('utf-16-le',errors='replace') for p in replies if p[:5]==b'\xf0\x8a\x01\x00\x00'])
        battle=self.hub.battles[owners[0]]
        self.assertFalse(battle['bots']);self.assertEqual(len(battle['humans']),2)
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
        move_to_exit(battle,owners[0])
        self.case.send(0,b'\x2a\x01');self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,wins,losses FROM ranked_players ORDER BY account').fetchall(),
                             [('alice',0,1),('bob',1,0)])
            self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone(),(1,))
        old=ranked.snapshot(self.path,'bob');self.hub.tick();self.assertEqual(old,ranked.snapshot(self.path,'bob'))

    def test_three_and_one_solo_tickets_do_not_fill_a_team_against_four(self):
        self.case.send(0,join((1,2,3,4)))
        self.case.send(1,join((1,2,3)))
        self.assertFalse(bool(self.hub.battles))
        self.case.send(2,join((1,)))
        self.assertFalse(bool(self.hub.battles));self.assertEqual(len(self.hub.ranked_waiting),3)

    def test_every_living_fighter_can_act_during_the_owners_turn(self):
        owners,battle=self.start()
        field=battle['field'];room=battle['room'].room_id
        actors=field.living_actor_ids(owners[0]);opponents=field.living_actor_ids(owners[1])
        self.assertEqual(battle['arena']._turns[room][1],set(actors))
        self.assertTrue(all(field.actor(i).action_points>0 for i in actors))
        self.assertTrue(all(field.actor(i).action_points==0 for i in opponents))
        self.case.send(0,encode_end_turn(actors[-1]));self.hub.tick()
        self.assertEqual(battle['arena']._turns[room][1],set(opponents))

    def assert_equal_duel(self,count):
        fixture.reserve_fighters(self.path,self.case.sessions[2],count)
        owners=tuple(self.hub.identity(s) for s in self.case.sessions[:3])
        squad=tuple(range(1,count+1))
        self.case.send(0,join(squad))
        other_size=(2,1,4,3)[count-1]
        self.case.send(1,join(tuple(range(1,other_size+1))))
        self.assertFalse(bool(self.hub.battles))
        self.case.send(2,join(squad))
        battle=self.hub.battles.get(owners[0])
        self.assertIsNotNone(battle)
        self.assertEqual(battle['humans'],{owners[0],owners[2]})
        self.assertEqual(set(self.hub.ranked_waiting),{owners[1]})
        self.assertFalse(battle['bots'])
        self.assertEqual(battle['room'].request.soldiers_count_01,count)
        for index in (0,2):self.case.send(index,b'\x36')
        self.hub.tick()
        field=battle['field'];room=battle['room'].room_id
        self.assertEqual(len(field._actors),2*count)
        self.assertEqual(battle['arena']._turns[room][1],set(field.actor_ids(owners[0])))

    def test_one_fighter_duel_skips_a_two_fighter_opponent(self):
        self.assert_equal_duel(1)

    def test_two_fighter_duel_skips_a_one_fighter_opponent(self):
        self.assert_equal_duel(2)

    def test_three_fighter_duel_skips_a_four_fighter_opponent(self):
        self.assert_equal_duel(3)

    def test_four_fighter_duel_skips_a_three_fighter_opponent(self):
        self.assert_equal_duel(4)

    def test_both_clients_get_captured_flag_score_and_income(self):
        owners,battle=self.start()
        field=battle['field'];points=battle['points']
        identity=field.actor_ids(owners[0])[0];x,y=points.positions[2]
        field._actors[identity]=replace(field.actor(identity),x=x,y=y)
        for owner in owners:self.hub.queues[owner].clear()
        first=self.case.send(0,encode_end_turn(identity));self.hub.tick()
        for index,replies in enumerate((first,())):
            packets=(*replies,*self.hub.queues[owners[index]])
            latest=[p for p in packets if p[:2]==b'\xc6\x16'][-1]
            self.assertEqual(struct.unpack('<7I',latest[2:]),(2,1,10,10,2,5,5))
            text='Флаги — ваша команда {}, противник {}'.format(*((2,1) if index==0 else (1,2)))
            self.assertTrue(any(p[:1]==b'\x22' and p[5]==3 and text.encode('utf-16-le') in p for p in packets))

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
        move_to_exit(active,owners[0])
        self.case.send(0,b'\x2a\x01');restored.tick();restored.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone(),(1,))
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone(),(2,))

    def test_expiring_both_ranked_reconnects_keeps_the_first_result(self):
        owners, battle = self.start(journal=True)
        for session in self.case.sessions[:2]:
            self.assertTrue(self.hub.disconnect(session))
        self.case.now += 181
        self.hub.tick()
        self.assertEqual(len(self.hub.battles), 0)
        self.assertFalse(self.hub.offline)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,result FROM battle_rewards WHERE match_id=? ORDER BY account',
                                        (battle['match_id'],)).fetchall(), [('alice', 0), ('bob', 1)])
            self.assertEqual(db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone(), (0,))

    def test_two_native_exits_before_tick_keep_the_first_result(self):
        owners, battle = self.start(journal=True)
        for owner in owners:
            move_to_exit(battle, owner)
        for index in (0, 1):
            self.case.send(index, b'\x2a\x01')
        self.assertEqual(len(self.hub.battles), 0)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,result FROM battle_rewards WHERE match_id=? ORDER BY account',
                                        (battle['match_id'],)).fetchall(), [('alice', 0), ('bob', 1)])


if __name__=='__main__':unittest.main()
