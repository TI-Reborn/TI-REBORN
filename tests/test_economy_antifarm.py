"""Account-pair progression limits in the real settlement transaction."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tio import battle_settlement, premium
from tio.battle_rewards import settle
from tio.level_progression import XP, MAX_XP
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.reward_policy import RewardContext
from tio.wallets import WalletStore
from test_weapon_proficiency import profile


class EconomyAntifarmTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'state.sqlite3'
        self.store=OwnedPetStore(self.path)
        for account in ('alice','bob','carol'):
            WalletStore(self.path).ensure(account)
            pet=decode_pet_info(profile(),human_equipment=True)
            packet=encode_pet_info(replace(pet,fields={**pet.fields,
                '0x8c4bbc':1,'0x8c4bd0':0,XP:0}))
            self.store.ensure(account,packet,encode_item_list(1,()),human=True)

    def context(self,account='alice',*,active=True,opponents=None):
        return RewardContext((1,),opponents or ((('bob' if account=='alice' else 'alice'),(1,)),),active)

    def award(self,match,account='alice',*,result=1,xp=100,earned=2,now=100,**kwargs):
        context=kwargs.pop('reward_context',self.context(account))
        return settle(self.path,account,match,result,experience_report={1:xp},
                      rank_report={1:(earned,False)},reward_context=context,now=now,**kwargs)

    def audit(self,match,account='alice'):
        with closing(sqlite3.connect(self.path)) as db:
            credit,calculation=db.execute('SELECT credits,calculation FROM battle_rewards WHERE account=? AND match_id=?',
                                         (account,match)).fetchone()
            xp=db.execute('SELECT gain FROM experience_battle_audit WHERE account=? AND match_id=?',(account,match)).fetchone()[0]
            rank=db.execute('SELECT earned FROM rank_battle_audit WHERE account=? AND match_id=?',(account,match)).fetchone()[0]
        return credit,xp,rank,json.loads(calculation)

    def test_repeated_distinct_matches_discount_positive_progression_and_share_pairs(self):
        for index,factor in enumerate((1,1,1,.5,.5,.5,.25,.25)):
            self.award(str(index),now=100+index)
            # The second participant settles much later, with the same frozen
            # pair factor rather than another pair-history charge.
            self.award(str(index),'bob',now=10000+index)
            for account in ('alice','bob'):
                credits,xp,rank,audit=self.audit(str(index),account)
                self.assertEqual((credits,xp,rank),(int(100*factor),int(100*factor),int(4*factor)))
                self.assertEqual(audit['progression_repeat'],audit['repeat'])
                self.assertEqual(audit['experience_factor'],audit['progression_repeat'])
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM reward_pairs').fetchone()[0],index+1)

    def test_fresh_teammate_does_not_restore_progression_against_farmed_victim(self):
        for index in range(6):self.award(str(index),xp=0,earned=0,now=100+index)
        context=self.context(opponents=(('bob',(1,)),('carol',(1,))))
        self.award('mixed',xp=100,earned=4,reward_context=context,now=107)
        credits,xp,rank,audit=self.audit('mixed')
        self.assertEqual((credits,xp,rank),(62,25,2))
        self.assertEqual((audit['repeat'],audit['progression_repeat']),('5/8','1/4'))
        self.assertEqual(audit['rank_positive_factor'],'1/2')

    def test_no_repeated_xp_or_rank_on_concurrent_outbox_replay(self):
        kwargs=dict(experience_report={1:100},rank_report={1:(2,False)},
                    reward_context=self.context(),now=100)
        battle_settlement.enqueue(self.path,'outbox',[('alice',1,kwargs)])
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _:battle_settlement.apply(self.path,'outbox','alice'),range(8)))
        self.assertEqual(self.audit('outbox')[:3],(100,100,4))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reward_pairs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],0)

    def test_pair_progression_history_rolls_back_if_later_rank_recipient_is_invalid(self):
        with self.assertRaises(ValueError):
            settle(self.path,'alice','rollback',1,reward_context=self.context(),
                   experience_report={1:1400},rank_report={999:(5,False)},now=100)
        with closing(sqlite3.connect(self.path)) as db:
            for table in ('reward_pairs','experience_battle_audit','battle_rewards'):
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone()
                if exists:self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.award('rollback')
        self.assertEqual(self.audit('rollback')[:3],(100,100,4))

    def test_six_hour_boundary_and_non_pvp_progression(self):
        for index in range(7):self.award(str(index),xp=0,earned=0,now=100)
        self.award('outside',now=21700)
        self.assertEqual(self.audit('outside')[:3],(100,100,4))
        self.award('encounter',xp=100,earned=2,reward_context=None,now=21701)
        self.assertEqual(self.audit('encounter')[:3],(0,100,4))

    def test_premium_is_combined_before_final_floor_and_audited(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET gold=10 WHERE account='alice'")
        premium.purchase(self.path,'alice',premium.encode_purchase(1,10),now=100)
        for index in range(6):self.award(str(index),xp=0,earned=0,now=100+index)
        self.award('premium',xp=11,earned=3,now=107)
        credits,xp,rank,audit=self.audit('premium')
        self.assertEqual((credits,xp,rank),(37,4,2))
        self.assertEqual((audit['experience_factor'],audit['rank_positive_factor']),('3/8','3/4'))

    def test_anti_experience_subscription_still_suppresses_xp(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET gold=10 WHERE account='alice'")
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER)')
            db.execute("INSERT INTO character_locations VALUES ('alice',4)")
        premium.purchase(self.path,'alice',premium.encode_purchase(3,10),now=100)
        self.award('anti',now=101)
        self.assertEqual(self.audit('anti')[1],0)
        self.assertEqual(self.audit('anti')[3]['experience_factor'],'0')

    def test_repeat_penalty_does_not_discount_death_or_escape_penalty(self):
        for index in range(6):self.award(str(index),xp=0,earned=0,now=100+index)
        for match,died,escaped,expected in (('dead',True,False,5),('escape',False,True,20)):
            settle(self.path,'alice',match,0,reward_context=self.context(),
                   rank_report={1:(0,died)},escaped=escaped,now=107)
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(db.execute('SELECT penalty FROM rank_battle_audit WHERE match_id=?',(match,)).fetchone()[0],expected)

    def test_invalid_xp_types_cannot_become_valid_during_multiplier_arithmetic(self):
        for index,bad in enumerate((True,-1,MAX_XP+1,1.0)):
            with self.assertRaises(ValueError):self.award('bad'+str(index),xp=bad)
        with closing(sqlite3.connect(self.path)) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='reward_pairs'").fetchone()
            if exists:self.assertEqual(db.execute('SELECT count(*) FROM reward_pairs').fetchone()[0],0)

    def test_shared_authoritative_attack_and_forged_result_do_not_bypass_progression_limit(self):
        from test_shared_team_arena import SharedTeamTests
        from tio.protocol.battle_attack import AttackRequest, encode_attack_request
        from tio.protocol.battle_over import encode_battle_over
        case=SharedTeamTests();case.setUp();self.addCleanup(case.doCleanups)
        context=RewardContext((1,),(('bob',(1,)),),True)
        for index in range(6):settle(case.path,'alice','history'+str(index),1,
                                    reward_context=context,now=100)
        owners,battle=case.open_battle();field=battle['field'];combat=field.combat
        attacker=field.actor_ids(owners[0])[0];victim=field.actor_ids(owners[1])[0]
        field._actors[victim]=replace(field.actor(victim),x=5,y=6,health=2)
        combat.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a)
        # Client-supplied battle-over money and result are not an accepted
        # action. Only the server's own attack can populate XP/kills.
        case.send(0,encode_battle_over(1,credits=1000000))
        self.assertFalse(combat.experience.totals);self.assertFalse(combat.rank_kills)
        case.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        self.assertEqual(field.actor(victim).health,0)
        self.assertGreater(combat.experience.totals[attacker],0)
        with patch('server.team_arena.time.time',return_value=100):
            case.hub.settle(battle,owners[0],1)
        with closing(sqlite3.connect(case.path)) as db:
            gain=db.execute('SELECT gain FROM experience_battle_audit WHERE account=? AND match_id=?',
                            ('alice',battle['match_id'])).fetchone()[0]
            calculation=json.loads(db.execute('SELECT calculation FROM battle_rewards WHERE account=? AND match_id=?',
                                               ('alice',battle['match_id'])).fetchone()[0])
        self.assertEqual(gain,int(combat.experience.totals[attacker])//4)
        self.assertEqual(calculation['progression_repeat'],'1/4')


if __name__=='__main__':unittest.main()
