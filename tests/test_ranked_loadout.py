"""Native nonempty selections, real mixed squads, temporary gear and recovery."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import struct
import unittest
from unittest.mock import patch

import test_ranked as fixture
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import decode_item_list,encode_item_list,ItemRecord
from tio.protocol.ranked import decode_join
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_turn import encode_end_turn
from tio.weapon_proficiency import SAVED,BASE,bits,number
from tio.combat_completion import settlement_health
from tio.ranked_loadout import extra


def join(ids=(1,),equipment=(),bonus=0,token=False):
    return b'\xc6\x21'+bytes((int(token),0))+struct.pack('<I',len(ids))+b''.join(
        struct.pack('<II',i,len(equipment))+b''.join(struct.pack('<II',template,slot) for slot,template in equipment)+bytes((bonus,)) for i in ids)


class RankedLoadoutTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RankedServerTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.case=self.base.case;self.path=self.base.path;self.hub=self.base.hub

    def clone(self,index,count,level=4):
        from tio.level_progression import FLOORS
        store=OwnedPetStore(self.path);account=self.case.sessions[index].account
        original=decode_pet_info(store.list(account)[0][1],human_equipment=True)
        for i in range(1,count+1):
            fields={**original.fields,'0x8c43eb':i,'0x8c44a6':0,'0x8c4aef':level,'0x8c4b05':FLOORS[level-1],
                    '0x8c4a07':85+(level-1)*5,'0x8c4ab1':85+(level-1)*5}
            for key in (*SAVED,*BASE):fields[key]=bits(180)
            pet=encode_pet_info(replace(original,fields=fields))
            if i==1:
                with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(pet,account))
            else:store.ensure(account,pet,encode_item_list(i,()),human=True)

    def start(self,left,right,*,journal=False):
        if journal:self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:1000)
        self.case.send(0,left);self.case.send(1,right)
        self.assertTrue(self.hub.battles)
        battle=next(iter(self.hub.battles.values()))
        for i in (0,1):self.case.send(i,b'\x36')
        self.hub.tick();return battle

    def test_native_template_then_slot_and_validation(self):
        self.assertEqual(decode_join(join(equipment=((0,208),(4,301)),bonus=2)),((0,0),((1,((0,208),(4,301)),2),)))
        for e in (((0,208),(0,211)),((1,208),),((9,301),)):
            with self.assertRaises(ValueError):decode_join(join(equipment=e))
        for e in (((0,301),),((4,208),),((0,65500),),((0,255),)):
            self.assertTrue(any(p[0]==0xf0 for p in self.case.send(0,join(equipment=e))))
            self.assertFalse(self.hub.ranked_waiting)

    def test_loaned_weapon_fires_and_consumption_never_persists(self):
        before={s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]}
        b=self.start(join(equipment=((0,208),(2,210),(3,212),(4,301)),bonus=1),join(bonus=2))
        f=b['field'];combat=f.combat;owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2]);a=f.actor_ids(owners[0])[0];v=f.actor_ids(owners[1])[0]
        self.assertEqual(combat.ranked_bonuses[a],(1,40))
        f.blocked=frozenset();f.transparent_obstacles=frozenset()
        f._actors[a]=replace(f.actor(a),x=3,y=3);f._actors[v]=replace(f.actor(v),x=4,y=3)
        self.hub.snapshot(b)
        for q in self.hub.queues.values():q.clear()
        with patch('tio.combat_rolls.burst',return_value=(30,True,False)):
            replies=self.case.send(0,encode_attack_request(AttackRequest(a,4,3)))
        result=next(decode_attack_result(p) for p in replies if p[0]==0x4b)
        self.assertEqual(result.hits[0].additional_damage,1)
        self.assertEqual(combat.ranked_remainders[a,1],200)
        for s in self.case.sessions[:2]:self.assertEqual(before[s.account][0][2],OwnedPetStore(self.path).list(s.account)[0][2])
        self.case.send(0,b'\x2a\1');self.hub.tick()
        for s in self.case.sessions[:2]:self.assertEqual(decode_item_list(OwnedPetStore(self.path).list(s.account)[0][2])[1],())

    def test_cross_band_scaling_wounds_and_saved_proficiency(self):
        self.clone(0,1,20);self.clone(1,1,4)
        b=self.start(join(equipment=((4,301),),bonus=2),join())
        f=b['field'];combat=f.combat;i=f.actor_ids(self.hub.identities[self.case.sessions[0]])[0]
        self.assertEqual(combat.ranked_limits[i],106)
        self.assertEqual(combat.enhancement_caps[i],10)
        self.assertEqual(f.actor(i).max_health,125) # 6th-level HP110 + three-band15
        self.assertEqual(settlement_health(combat,i),180)
        f._actors[i]=replace(f.actor(i),health=100)
        self.assertEqual(settlement_health(combat,i),155)
        f._actors[i]=replace(f.actor(i),health=0);self.assertEqual(settlement_health(combat,i),0)
        raw=OwnedPetStore(self.path).list('alice')[0][1];saved=decode_pet_info(raw,human_equipment=True).fields
        self.assertEqual(saved['0x8c4aef'],20);self.assertEqual(number(saved[SAVED[0]]),180)

    def test_mixed_bands_inside_one_selected_squad(self):
        self.clone(0,2,4);self.clone(1,2,4)
        self.clone(0,1,20)
        b=self.start(join((1,2)),join((1,2)))
        self.assertEqual(len(b['field']._actors),4)
        self.assertEqual(set(b['field'].combat.ranked_limits.values()),{106})

    def test_four_vs_two_plus_two_alternates_single_actor_and_all_receipts(self):
        for index,count in ((0,4),(1,2),(2,2)):self.clone(index,count)
        self.case.send(0,join((1,2,3,4)));self.case.send(1,join((1,2)));self.assertFalse(self.hub.battles)
        self.case.send(2,join((1,2)));b=next(iter(self.hub.battles.values()));f=b['field']
        self.assertEqual(len(b['humans']),3);self.assertEqual(len(b['room'].members),3)
        for i in (0,1,2):self.case.send(i,b'\x36')
        self.hub.tick();seen=[]
        for n in range(8):
            owner,ids,deadline=b['arena']._turns[b['room'].room_id];self.assertEqual(len(ids),1)
            identity=next(iter(ids));seen.append(identity);self.assertEqual(f.teams[owner],n%2)
            inactive=[i for i in f.actor_ids(owner) if i!=identity]
            if inactive:
                replies=self.case.send(self.case.sessions.index(self.hub.players[owner]),encode_attack_request(AttackRequest(inactive[0],1,1)))
                self.assertTrue(any(p[0]==0xf0 for p in replies))
            self.case.now+=2
            self.case.send(self.case.sessions.index(self.hub.players[owner]),encode_end_turn());self.hub.tick()
        self.assertEqual(len(set(seen)),8)
        self.case.send(1,b'\x2a\1');self.hub.tick();self.assertFalse(b['finished'])
        self.assertNotIn('ranked_winner',b)
        b['points'].scores=[1000,0];self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,wins,losses FROM ranked_players ORDER BY account').fetchall(),[('alice',1,0),('bob',0,1),('carol',0,1)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ranked_matches').fetchone()[0],1)

    def test_fractional_bonus_accumulates_separately(self):
        c=type('C',(),{'ranked_bonuses':{1:(1,55),2:(2,55)}})();remainders={}
        self.assertEqual(extra(c,1,1,40,remainders),2)
        self.assertEqual(extra(c,1,1,51,remainders),3)
        self.assertEqual(extra(c,2,2,40,remainders),2)
        self.assertEqual(extra(c,1,2,1000,remainders),0)

    def test_daily_token_does_not_stack_and_refund_is_idempotent(self):
        from tio.ranked_tokens import status,consume,refund
        with closing(sqlite3.connect(self.path)) as db,db:
            self.assertEqual(status(db,'alice',now=100),( 'alice',1))
            self.assertEqual(status(db,'alice',now=200000)[1],1)
            with patch('tio.ranked_tokens.time.time',return_value=100):
                consume(db,'one',['alice']);consume(db,'one',['alice'])
            self.assertEqual(db.execute("SELECT balance FROM ranked_tokens WHERE login='alice'").fetchone()[0],0)
            stamp=db.execute("SELECT granted_at FROM ranked_tokens WHERE login='alice'").fetchone()[0]
            self.assertEqual(status(db,'alice',now=stamp+86399)[1],0)
            self.assertEqual(status(db,'alice',now=stamp+86400)[1],1)
            refund(db,'one');refund(db,'one')
            self.assertEqual(status(db,'alice')[1],2)

    def test_cancelled_or_changed_owned_slot_is_revalidated_at_match(self):
        self.case.send(0,join(equipment=((4,301),)))
        item=ItemRecord(77,302,bytes(2),1,1,16,(300,)*3,bytes(4),None,bytes(3))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=1",(encode_item_list(1,(item,)),))
        self.case.send(1,join());self.assertFalse(self.hub.battles)
        self.assertEqual(decode_item_list(OwnedPetStore(self.path).list('alice')[0][2])[1],(item,))

    def test_token_queue_cancel_start_and_loading_timeout_refund(self):
        self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:1000)
        self.case.send(0,join(equipment=((4,301),),token=True));self.case.send(0,b'\xc6\x23')
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT balance FROM ranked_tokens WHERE login='alice'").fetchone()[0],1)
        self.case.send(0,join(equipment=((4,301),),token=True));self.case.send(1,join())
        b=next(iter(self.hub.battles.values()));f=b['field'];a=f.actor_ids(self.hub.identities[self.case.sessions[0]])[0]
        self.assertEqual(f.combat.ranked_bonuses[a],(0,25))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT balance FROM ranked_tokens WHERE login='alice'").fetchone()[0],0)
        self.case.now=61;self.hub.tick();self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT balance FROM ranked_tokens WHERE login='alice'").fetchone()[0],1)

    def test_gear_and_fractional_state_survive_restart(self):
        b=self.start(join(equipment=((4,301),),bonus=1),join(),journal=True)
        a=b['field'].actor_ids(self.hub.identities[self.case.sessions[0]])[0]
        with self.hub.journal.unit(b):b['field'].combat.ranked_remainders[a,1]=999
        restored=TeamArena(clock=lambda:0);restored.journal=BattleJournal(restored,self.path,wall=lambda:1000)
        self.assertEqual(restored.journal.recover(),[b['match_id']]);new=next(iter(restored.battles.values()))
        self.assertEqual(new['field'].combat.ranked_remainders[a,1],999)
        self.assertEqual(new['field'].combat.persistent_inventory(new['field'].combat.inventories[a]),encode_item_list(a,()))


if __name__=='__main__':unittest.main()
