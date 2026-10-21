"""Shared native TrueSkill with transient filler seats and human opponents."""
from contextlib import closing
from dataclasses import replace
import sqlite3,unittest
from unittest.mock import patch
from server.ranked_bots import incomplete_groups
from server.team_arena import TeamArena
from server.battle_journal import BattleJournal
from tio.matchmaking import SearchTicket
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.battle_turn import encode_end_turn
from tio import ranked
import test_ranked as fixture
from test_ranked_squads import join


class RankedBotsTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RankedServerTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.case=self.base.case;self.hub=self.base.hub;self.path=self.base.path
        for s in self.case.sessions[:2]:
            store=OwnedPetStore(self.path);pet=decode_pet_info(store.list(s.account)[0][1],human_equipment=True)
            for i in (2,3,4):store.ensure(s.account,encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':i,'0x8c44a6':0})),encode_item_list(i,()),human=True)

    def start(self,a=1,b=1,journal=False):
        if journal:self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:1000)
        before={s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]}
        self.case.send(0,join(range(1,a+1)));self.assertFalse(self.hub.battles)
        replies=self.case.send(1,join(range(1,b+1)))
        self.assertFalse(any(p[0]==0xf0 for p in replies),replies)
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2]);battle=self.hub.battles[owners[0]]
        self.assertIs(battle,self.hub.battles[owners[1]])
        self.assertEqual(len(battle['bots']),8-a-b);self.assertEqual(len(battle['field']._actors),8)
        self.assertEqual(battle['field'].scene_metadata['profile'],'trueskill_contest')
        for side in (0,1):self.assertEqual(sum(battle['field'].teams[v.owner_id]==side for v in battle['field']._actors.values()),4)
        self.assertEqual(before,{s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]})
        for i in (0,1):self.case.send(i,b'\x36')
        self.hub.tick();return owners,battle

    def test_two_single_fighters_get_three_bots_each_without_persistent_assets(self):
        owners,battle=self.start();combat=battle['field'].combat
        self.assertEqual(set(battle['reward_roster']),set(owners))
        self.assertEqual(set(battle['reward_bot_roster']),battle['bots'])
        self.assertEqual([len(t) for t in battle['ranked_teams']],[1,1])
        for a in battle['field']._actors.values():
            if a.owner_id in battle['bots']:
                self.assertNotIn(a.actor_id,combat.persistence)
                self.assertEqual(decode_item_list(combat.inventories[a.actor_id])[1],())
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('select account from wallets order by account').fetchall(),[('alice',),('bob',),('carol',),('dave',)])

    def test_mismatched_squads_are_kept_intact_and_only_missing_seats_are_filled(self):
        owners,battle=self.start(4,1)
        self.assertEqual(len(battle['field'].actor_ids(owners[0])),4)
        self.assertEqual(len(battle['field'].actor_ids(owners[1])),1)
        self.assertEqual({battle['field'].teams[b] for b in battle['bots']},{1})

    def test_two_three_fighter_squads_get_one_bot_each(self):self.start(3,3)

    def test_full_real_teams_need_no_bots_and_remain_rated(self):
        owners,battle=self.start(4,4);self.assertFalse(battle['bots'])
        battle['ranked_winner']=0;self.assertIsNotNone(self.hub.ranked_report(battle))

    def test_single_search_still_requires_a_real_opponent_and_cancel_clears_it(self):
        self.case.send(0,join((1,)));self.case.now=600;self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.case.send(0,b'\xc6\x23');self.assertFalse(self.hub.ranked_waiting)

    def test_bot_battle_exit_does_not_change_any_trueskill_rating(self):
        snapshots={s.account:ranked.snapshot(self.path,s.account) for s in self.case.sessions[:2]}
        owners,battle=self.start();self.case.send(0,b'\x2a\1');self.hub.tick()
        self.assertTrue(battle['finished']);self.assertIsNone(self.hub.ranked_report(battle))
        self.assertEqual(snapshots,{s.account:ranked.snapshot(self.path,s.account) for s in self.case.sessions[:2]})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute("select 1 from sqlite_master where name='ranked_matches'").fetchone())
            self.assertEqual(db.execute('select count(*) from battle_rewards').fetchone()[0],2)

    def test_bot_turns_move_and_do_not_stall_points_or_turn_rotation(self):
        owners,battle=self.start();field=battle['field'];initial=dict(field._actors)
        for _ in range(20):
            turn=battle['arena']._turns.get(battle['room'].room_id)
            if turn:
                i=owners.index(turn[0]);self.case.now+=1.1;self.case.send(i,encode_end_turn())
            self.hub.tick();self.assertFalse(battle.get('faulted'))
            if all(field._ability_turns[a.actor_id]>0 for a in initial.values() if a.owner_id in battle['bots']):break
        else:self.fail('Not every bot received its turn')
        self.assertTrue(any((a.x,a.y)!=(initial[i].x,initial[i].y) for i,a in field._actors.items() if a.owner_id in battle['bots']))
        self.assertGreater(sum(battle['points'].scores),0)

    def test_saved_bots_reconnect_without_duplicate_seats_or_consumption(self):
        owners,battle=self.start(journal=True);ids=set(battle['field']._actors);bots=set(battle['bots'])
        restored=TeamArena(clock=lambda:self.case.now);restored.journal=BattleJournal(restored,self.path,wall=lambda:1001)
        self.assertEqual(restored.journal.recover(),[battle['match_id']]);self.case.hub=restored
        for i in (0,1):self.assertTrue(restored.resume(self.case.sessions[i]));self.case.send(i,b'\x36')
        active=restored.battles[owners[0]];self.assertEqual(set(active['field']._actors),ids);self.assertEqual(active['bots'],bots)
        self.assertEqual(len(active['humans']),2)

    def test_bot_turn_advances_flag_scores_exactly_once(self):
        owners,battle=self.start();arena=battle['arena'];room=battle['room']
        arena._turns.pop(room.room_id,None)
        battle['ranked_side']=1;battle['ranked_cursors']=[1,0]
        battle['point_turn_pending']=False;battle['points'].scores=[0,0]
        def skip_bot(service,room_id,owner):
            service.begin_turn_packets(owner,service._fields[room_id].living_actor_ids(owner),40)
            service.end_turn(owner,encode_end_turn())
        with patch('tio.training_bot.play_turn',side_effect=skip_bot):
            self.hub.tick();self.assertTrue(battle['point_turn_pending'])
            self.assertEqual(battle['points'].scores,[0,0])
            self.hub.tick();self.assertEqual(battle['points'].scores,[5,5])
            self.hub.tick();self.assertEqual(battle['points'].scores,[5,5])

    def test_plain_bot_tickets_never_copy_bonus_flags_or_equipment_selections(self):
        from server.ranked_bots import fill_seats
        from types import SimpleNamespace
        class Ticket(SearchTicket):pass
        a=Ticket(1,(7,8),(10,11),0);a.__dict__['flags']=(1,0);a.__dict__['selections']=((7,((4,301),),0),)
        b=SearchTicket(2,(1,),(10,),1);hub=SimpleNamespace(players={1:None,2:None},battles={})
        seats=[(1,0,self.path,'alice',a,False),(2,1,self.path,'bob',b,False)];teams=[[1],[2]]
        bots=fill_seats(hub,seats,teams);self.assertEqual(len(bots),5)
        for _,_,_,_,t,is_bot in seats:
            if is_bot:self.assertFalse(getattr(t,'flags',(0,0))[0]);self.assertFalse(getattr(t,'selections',()))

    def test_incomplete_selection_prefers_more_real_fighters(self):
        a,b,c=[SearchTicket(i,tuple(range(n)),(4,)*n,i) for i,n in ((1,2),(2,1),(3,1))]
        states={(2,1):((a,),(b,)),(2,2):((a,),(b,c))}
        self.assertEqual(incomplete_groups(states,lambda t:0),((a,),(b,c)))
        self.assertIsNone(incomplete_groups({(2,0):((a,),())},lambda t:0))

if __name__=='__main__':unittest.main()
