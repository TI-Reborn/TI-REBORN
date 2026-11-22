"""TrueSkill human-only queue and legacy transient-bot helpers."""
from dataclasses import replace
import unittest
from server.ranked_bots import incomplete_groups
from tio.matchmaking import SearchTicket
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
import test_ranked as fixture
from test_ranked_squads import join


class RankedBotsTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.RankedServerTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.case=self.base.case;self.hub=self.base.hub;self.path=self.base.path
        for s in self.case.sessions[:2]:
            store=OwnedPetStore(self.path);pet=decode_pet_info(store.list(s.account)[0][1],human_equipment=True)
            for i in (2,3,4):store.ensure(s.account,encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':i,'0x8c44a6':0})),encode_item_list(i,()),human=True)

    def start(self):
        before={s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]}
        self.case.send(0,join((1,2,3,4)));self.assertFalse(self.hub.battles)
        replies=self.case.send(1,join((1,2,3,4)))
        self.assertFalse(any(p[0]==0xf0 for p in replies),replies)
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2]);battle=self.hub.battles[owners[0]]
        self.assertIs(battle,self.hub.battles[owners[1]])
        self.assertFalse(battle['bots']);self.assertEqual(len(battle['field']._actors),8)
        self.assertEqual(battle['field'].scene_metadata['profile'],'trueskill_contest')
        for side in (0,1):self.assertEqual(sum(battle['field'].teams[v.owner_id]==side for v in battle['field']._actors.values()),4)
        self.assertEqual(before,{s.account:OwnedPetStore(self.path).list(s.account) for s in self.case.sessions[:2]})
        for i in (0,1):self.case.send(i,b'\x36')
        self.hub.tick();return owners,battle

    def test_incomplete_teams_stay_queued_without_bot_filler(self):
        for count_a,count_b in ((1,2),(4,1),(3,4)):
            self.case.send(0,join(range(1,count_a+1)))
            self.case.send(1,join(range(1,count_b+1)))
            self.assertFalse(bool(self.hub.battles));self.assertEqual(len(self.hub.ranked_waiting),2)
            for index in (0,1):self.case.send(index,b'\xc6\x23')

    def test_full_real_teams_need_no_bots_and_remain_rated(self):
        owners,battle=self.start();self.assertFalse(battle['bots'])
        battle['ranked_winner']=0;self.assertIsNotNone(self.hub.ranked_report(battle))

    def test_single_search_still_requires_a_real_opponent_and_cancel_clears_it(self):
        self.case.send(0,join((1,)));self.case.now=600;self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.case.send(0,b'\xc6\x23');self.assertFalse(self.hub.ranked_waiting)

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
