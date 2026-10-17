"""Bot credit rates, persisted settlements and shared authoritative activity."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import unittest
from types import SimpleNamespace

import test_reward_policy as policy_fixture
import test_shared_team_arena as shared_fixture
from tio.battle_rewards import receipt,settle
from tio.battle_settlement import pack,unpack
from tio.reward_policy import RewardContext,calculate
from tio.wallets import WalletStore


class BotCreditPolicyTests(unittest.TestCase):
    setUp=policy_fixture.RewardPolicyTests.setUp
    award=policy_fixture.RewardPolicyTests.award
    context=policy_fixture.RewardPolicyTests.context

    def bot_context(self,active=True):
        return RewardContext((1,),((0x60000001,(1,)),),active)

    def test_bot_outcomes_are_half_human_rate_rounded_down(self):
        for result,expected in ((1,50),(0,12),(2,25)):
            self.assertEqual(self.award('bot'+str(result),result,reward_context=self.bot_context()),(expected,0))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reward_pairs').fetchone()[0],0)
            audit=json.loads(db.execute("SELECT calculation FROM battle_rewards WHERE match_id='bot1'").fetchone()[0])
        self.assertEqual((audit['credit_factor'],audit['progression_repeat']),('1/2','1'))
        self.assertEqual(audit['opponents'],[])
        self.assertEqual(audit['bot_opponents'][0]['owner'],0x60000001)

    def test_fresh_mixed_team_and_wall_rates(self):
        for count,expected,factor in ((1,75,'3/4'),(3,62,'5/8')):
            context=RewardContext((1,),(('enemy'+str(count),(1,)),)+tuple((0x60000001+i,(1,)) for i in range(count)),True)
            self.assertEqual(self.award('mixed'+str(count),reward_context=context),(expected,0))
            with closing(sqlite3.connect(self.path)) as db:
                audit=json.loads(db.execute('SELECT calculation FROM battle_rewards WHERE match_id=?',('mixed'+str(count),)).fetchone()[0])
            self.assertEqual(audit['credit_factor'],factor)

    def test_repeated_human_pair_stays_discounted_in_mixed_match(self):
        for i in range(3):self.award('pvp'+str(i),now=100)
        ctx=RewardContext((1,),(('bob',(1,)),(0x60000001,(1,))),True)
        self.assertEqual(self.award('mixed',reward_context=ctx,now=101),(50,0))
        with closing(sqlite3.connect(self.path)) as db:
            audit=json.loads(db.execute("SELECT calculation FROM battle_rewards WHERE match_id='mixed'").fetchone()[0])
        self.assertEqual(audit['progression_repeat'],'1/2')
        self.assertEqual(audit['bot_credit_factor'],'3/4')

    def test_bot_ids_are_not_repeated_human_accounts(self):
        for i in range(8):
            self.assertEqual(self.award(str(i),reward_context=self.bot_context(),now=100+i),(50,0))

    def test_afk_escape_training_stay_zero(self):
        self.assertEqual(self.award('afk',reward_context=self.bot_context(False)),(0,0))
        self.assertEqual(self.award('escape',reward_context=self.bot_context(),escaped=True),(0,0))
        self.assertEqual(self.award('training',reward_context=None),(0,0))

    def test_rank_strength_and_city_modifiers_still_apply(self):
        with closing(sqlite3.connect(self.path)) as db:
            for i,(level,enemy,rank,town,expected) in enumerate(((10,10,20,None,76),(20,1,0,None,39),(1,20,0,None,57),(4,4,0,2,218))):
                ctx=RewardContext((level,),((0x60000001,(enemy,)),),True,town)
                gross,_=calculate(db,'alice',str(i),1,ctx,rank,now=100)
                self.assertEqual(gross,expected)

    def test_concurrent_retry_credits_wallet_once(self):
        ctx=self.bot_context()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:self.award('once',reward_context=ctx),range(8)))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10050)
        self.award('once',reward_context=self.context())
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10050)

    def test_outbox_roundtrip_preserves_integer_identity_and_frozen_levels(self):
        ctx=RewardContext((2,),(('bob',(2,)),(0x60000001,(1,3))),True,3)
        result,kwargs=unpack(pack(1,dict(reward_context=ctx)))
        self.assertEqual(kwargs['reward_context'],ctx)
        self.assertIs(type(kwargs['reward_context'].opponents[1][0]),int)
        self.assertEqual(self.award('outbox',result,**kwargs),(77,0))

    def test_premium_and_rental_apply_to_reduced_gross(self):
        from tio import premium
        from tio.owned_pets import OwnedPetStore
        OwnedPetStore(self.path)
        premium.purchase(self.path,'alice',premium.encode_purchase(1,premium.OFFERS[1][1]),now=100)
        self.assertEqual(self.award('premium',reward_context=self.bot_context(),rental_units=(4,),now=101),(75,67))

    def test_invalid_bot_identifiers_are_rejected(self):
        with closing(sqlite3.connect(self.path)) as db:
            for identity in (True,0,-1,0x100000000,None):
                with self.assertRaises(ValueError):
                    calculate(db,'alice','invalid',1,RewardContext((1,),((identity,(1,)),),True),0)


class SharedBotCreditTests(unittest.TestCase):
    setUp=shared_fixture.SharedTeamTests.setUp
    send=shared_fixture.SharedTeamTests.send
    create=shared_fixture.SharedTeamTests.create
    paired=shared_fixture.SharedTeamTests.paired
    open_battle=shared_fixture.SharedTeamTests.open_battle

    def solo(self):
        self.send(0,b'\xba\3\0\1');self.now=60;self.hub.tick()
        owner=self.hub.identities[self.sessions[0]];battle=self.hub.battles[owner]
        field=battle['field'];field.blocked=frozenset();field.doors.states={}
        for i,actor in field._actors.items():
            field._actors[i]=replace(actor,x=5,y=5 if actor.owner_id==owner else 6,health=100,max_health=100)
        self.send(0,b'\x36');self.hub.tick()
        return owner,battle

    def test_solo_authoritative_attack_earns_half_win_reward(self):
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        owner,battle=self.solo();field=battle['field'];attacker=field.actor_ids(owner)[0]
        bot=next(iter(battle['bots']));victim=field.actor_ids(bot)[0]
        field.combat.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a)
        self.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        self.assertIn(owner,battle['reward_damage'])
        field._actors[victim]=replace(field.actor(victim),health=0)
        self.hub.tick();self.hub.tick()
        self.assertEqual(receipt(self.path,'alice',battle['match_id']),(50,0))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10050)
        # The native result window and wallet packet carry the same award.
        from tio.protocol.asset_count import decode_asset_count
        packets=tuple(self.hub.queues[owner])
        result=next(p for p in packets if p[:1]==b'\x4c')
        self.assertEqual(int.from_bytes(result[20:24],'little'),50)
        self.assertEqual(next(decode_asset_count(p).credits for p in packets if p[:2]==b'\xc8\x39'),10050)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account FROM battle_rewards').fetchall(),[('alice',)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reward_pairs').fetchone()[0],0)

    def test_starting_bot_levels_and_teams_survive_death_and_snapshot(self):
        from tio.battle_snapshot import dumps,loads
        owner,battle=self.solo();frozen=dict(battle['reward_bot_roster']);field=battle['field']
        victim=field.actor_ids(next(iter(battle['bots'])))[0]
        field._actors[victim]=replace(field.actor(victim),health=0)
        ctx=self.hub.settlement_inputs(battle,owner)['reward_context']
        self.assertEqual(ctx.opponents,tuple((b,ls) for b,(ls,team) in frozen.items()))
        restored=loads(dumps(battle))[0]
        self.assertEqual(restored['reward_bot_roster'],frozen)

    def test_allied_bots_are_excluded_from_enemy_factor(self):
        owners,battle=self.open_battle()
        ctx=self.hub.settlement_inputs(battle,owners[0])['reward_context']
        bots={b for b,_ in ctx.opponents if type(b)is int}
        self.assertEqual(bots,{b for b in battle['bots'] if not battle['field'].allied(b,owners[0])})
        self.assertEqual(len(ctx.opponents),2)

    def test_hazard_damage_to_bot_counts_but_friendly_damage_does_not(self):
        owners,battle=self.open_battle();field=battle['field'];owner=owners[0]
        ally=next(b for b in battle['bots'] if field.allied(b,owner))
        enemy=next(b for b in battle['bots'] if not field.allied(b,owner))
        field.combat.hazard_damage[(owner,ally)]=10
        self.hub.hazard_activity(battle,{})
        self.assertNotIn(owner,battle['reward_damage'])
        field.combat.hazard_damage[(owner,enemy)]=10
        self.hub.hazard_activity(battle,{})
        self.assertIn(owner,battle['reward_damage'])

    def test_supporting_active_bot_qualifies_human_healer(self):
        owners,battle=self.open_battle();owner=owners[0]
        ally=next(b for b in battle['bots'] if battle['field'].allied(b,owner))
        battle['reward_damage'].add(ally);battle['reward_support'].add((owner,ally))
        self.assertTrue(self.hub.settlement_inputs(battle,owner)['reward_context'].active)


if __name__=='__main__':unittest.main()
