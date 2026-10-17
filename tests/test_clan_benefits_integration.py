"""Shared transaction integration; temporary databases, no hosted/GUI claim."""
from contextlib import closing
from fractions import Fraction
import json
import sqlite3
import unittest

from tio import clan_benefits as benefits
from tio.clans import settle_influence,ClanRejected
from tio.db_transaction import transaction
from tio.achievements import schema as achievement_schema,update
from tio import ranks
from server.public_profile import read_profile


class ClanSettlementIntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_clan_benefits import ClanBenefitTests
        self.f=ClanBenefitTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)

    def call(self,*args,**kwargs):return self.f.call(settle_influence,*args,**kwargs)

    def test_durable_xp_bonus_and_achievement_replay_after_restart(self):
        with transaction(self.f.path) as db:
            achievement_schema(db)
            update(db,'alice',add={'clan_influence':7500,'assault_top20':1})
            db.execute('CREATE TABLE premium_accounts(account TEXT PRIMARY KEY,kind INTEGER,expires INTEGER)')
            db.execute("INSERT INTO premium_accounts VALUES ('alice',3,100)")
            db.execute("INSERT INTO clan_assault_medals VALUES ('old','alice','attack',1,'23/20')")
        result=self.call('alice',{1:1000},identity='match1',city_coefficient='2',now=10)
        self.assertEqual(result['amount'],189)
        self.assertEqual(self.f.read("SELECT contribution FROM clan_members WHERE account='alice'"),[(189,)])
        self.assertEqual(self.f.read("SELECT value FROM achievement_counters WHERE account='alice' AND metric='clan_influence'"),[(7689,)])
        self.assertEqual(self.call('alice',{1:1000},identity='match1',city_coefficient='2',now=9999),result)
        self.assertEqual(self.f.read("SELECT contribution FROM clan_members WHERE account='alice'"),[(189,)])
        self.assertEqual(self.f.read("SELECT COUNT(*) FROM achievement_events WHERE event_id='influence:xp:match1'"),[(1,)])
        with self.assertRaises(ClanRejected):self.call('alice',{1:1001},identity='match1',city_coefficient='2')

    def test_achievement_receipt_fault_rolls_back_influence_and_benefit_receipt(self):
        with transaction(self.f.path) as db:
            achievement_schema(db)
            db.execute("CREATE TRIGGER fail_achievement BEFORE INSERT ON achievement_events BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before=self.f.read('SELECT influence FROM clans ORDER BY id')
        with self.assertRaises(sqlite3.IntegrityError):self.call('alice',{1:1000},identity='fault')
        self.assertEqual(self.f.read('SELECT influence FROM clans ORDER BY id'),before)
        self.assertEqual(self.f.read('SELECT * FROM clan_benefit_receipts'),[])
        self.assertEqual(self.f.read('SELECT * FROM achievement_counters'),[])

    def test_legacy_caller_preserved_and_new_context_requires_identity(self):
        self.assertIsNone(self.call('alice',{1:1000}))
        self.assertEqual(self.f.read("SELECT contribution FROM clan_members WHERE account='alice'"),[(50,)])
        self.assertEqual(self.f.read('SELECT * FROM clan_benefit_receipts'),[])
        with self.assertRaises(ValueError):self.call('alice',{1:1000},city_coefficient=2)
        with self.assertRaises(ValueError):self.call('alice',{1:1000},now=10)
        self.assertEqual(self.f.read("SELECT contribution FROM clan_members WHERE account='alice'"),[(50,)])

    def test_zero_coefficient_or_unclanned_event_not_backfilled_on_retry(self):
        self.assertEqual(self.call('alice',{1:1000},identity='reservation',city_coefficient=0)['amount'],0)
        with transaction(self.f.path) as db:db.execute("DELETE FROM clan_members WHERE account='bob'")
        first=self.call('bob',{1:1000},identity='outside')
        with transaction(self.f.path) as db:db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('bob',1,0)")
        self.assertEqual(self.call('bob',{1:1000},identity='outside'),first)
        self.assertEqual(self.f.read("SELECT contribution FROM clan_members WHERE account='bob'"),[(0,)])
        with self.assertRaises(ClanRejected):self.call('alice',{999:1000},identity='foreign')

    def test_saved_crest_projection_and_signed_rating_are_read_only(self):
        from tests.test_clan_benefits import bmp
        saved=self.f.call(benefits.set_crest,'alice',bmp(), 'crest1')
        with transaction(self.f.path) as db:
            db.execute('CREATE TABLE soldier_ratings(account TEXT,pet_id INTEGER,rating INTEGER)')
            db.execute("INSERT INTO soldier_ratings VALUES ('alice',1,4294967295)")
            achievement_schema(db);update(db,'alice',add={'clan_capture':1})
        before=self.f.path.read_bytes();profile=read_profile(self.f.path,account='alice')
        self.assertEqual(profile.rating,0x7fffffff);self.assertEqual(profile.clan_crest_id,saved['crest_id'])
        self.assertEqual(profile.alliance_crest_id,0);self.assertEqual(read_profile(self.f.path,account='carol').clan_crest_id,0)
        self.assertEqual(self.f.path.read_bytes(),before)

class TerritoryBenefitsIntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_territories import TerritoriesTests
        self.f=TerritoriesTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)

    def final_battle(self):
        pair=self.f.pair()
        self.f.store.settle_match(self.f.event['id'],'match-1',self.f.results(pair,kill=True),(344,280))
        self.f.now=self.f.event['ends']+1;self.f.store.sync();return pair

    def rows(self,sql,args=()):
        with closing(sqlite3.connect(self.f.path)) as db:return db.execute(sql,args).fetchall()

    def claim(self,owner=None):
        owner=self.f.cids[0] if owner is None else owner
        with transaction(self.f.path) as db:
            db.execute('INSERT INTO territory_claims VALUES (11,?,0,1)',(owner,))
            db.execute("INSERT INTO territory_claim_history VALUES (11,1,?,0,'fixture','fixture',0)",(owner,))

    def test_real_finalization_awards_capture_top20_medals_once(self):
        pair=self.final_battle();final=self.f.store.finalize(self.f.event['id'])
        winner=final['winner_clan'];self.assertEqual(final['benefits_version'],1)
        self.assertEqual(self.rows('SELECT influence FROM clans WHERE id=?',(winner,)),[(10000+final['influence'][str(winner)],)])
        awarded=self.rows("SELECT account,value FROM achievement_counters WHERE metric='clan_capture' ORDER BY account")
        expected=[(m['account'],1) for g in pair['groups'] for m in g['members'] if m['clan_id']==winner]
        self.assertEqual(awarded,sorted(expected))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM achievement_counters WHERE metric='assault_top20'"),[(7,)])
        before=(self.rows('SELECT * FROM clan_benefit_receipts'),self.rows('SELECT * FROM achievement_events'),self.rows('SELECT * FROM range_accounts'))
        self.assertEqual(self.f.store.finalize(self.f.event['id']),final)
        self.assertEqual((self.rows('SELECT * FROM clan_benefit_receipts'),self.rows('SELECT * FROM achievement_events'),self.rows('SELECT * FROM range_accounts')),before)

    def test_prize_failure_rolls_back_capture_ordinary_influence_and_finalization(self):
        self.final_battle();before=(self.f.rows('clans'),self.f.rows('clan_ledger'),self.f.rows('warfare_clan_locks'))
        with transaction(self.f.path) as db:
            benefits.schema(db)
            db.execute("CREATE TRIGGER fail_bonus BEFORE INSERT ON clan_benefit_receipts BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.f.store.finalize(self.f.event['id'])
        self.assertEqual(self.f.rows('territory_claims'),());self.assertEqual(self.f.rows('warfare_event_receipts'),())
        self.assertEqual((self.f.rows('clans'),self.f.rows('clan_ledger'),self.f.rows('warfare_clan_locks')),before)
        self.assertEqual(self.rows('SELECT SUM(finalized) FROM warfare_events WHERE id=?',(self.f.event['id'],)),[(0,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM sqlite_master WHERE name='range_accounts'"),[(0,)])

    def test_legacy_unmarked_final_receipt_preserves_accounts_without_backfill(self):
        self.final_battle()
        old=dict(event_id=self.f.event['id'],town=11,winner_clan=None,captured=False,claim={},influence={},scores={})
        with transaction(self.f.path) as db:
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)',(self.f.event['id'],json.dumps(old)))
            db.execute('UPDATE warfare_events SET finalized=1 WHERE id=?',(self.f.event['id'],))
        before=self.f.path.read_bytes();self.assertEqual(self.f.store.finalize(self.f.event['id']),old)
        self.assertEqual(self.f.path.read_bytes(),before)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM sqlite_master WHERE name='clan_assault_prizes'"),[(0,)])

    def test_achievement_failure_rolls_back_already_computed_prizes_and_capture(self):
        self.final_battle();before=(self.f.rows('clans'),self.f.rows('clan_ledger'))
        with transaction(self.f.path) as db:
            achievement_schema(db)
            db.execute("CREATE TRIGGER fail_achievement BEFORE INSERT ON achievement_events BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.f.store.finalize(self.f.event['id'])
        self.assertEqual((self.f.rows('clans'),self.f.rows('clan_ledger')),before)
        self.assertEqual(self.f.rows('warfare_event_receipts'),());self.assertEqual(self.f.rows('territory_claims'),())
        self.assertEqual(self.rows('SELECT * FROM achievement_events'),[])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM sqlite_master WHERE name='clan_assault_prizes'"),[(0,)])

    def test_unopposed_or_empty_scores_never_create_capture_or_top20_prizes(self):
        pair=self.f.pair()
        self.f.store.settle_match(self.f.event['id'],'match-1',self.f.results(pair),decisive=pair['groups'][0]['id'])
        final=self.f.finish();self.assertFalse(final['captured'])
        self.assertEqual(self.rows('SELECT * FROM clan_assault_prizes'),[])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM sqlite_master WHERE name='achievement_events'"),[(0,)])

    def test_actual_owner_retention_awards_only_frozen_participating_owner_members(self):
        self.claim();self.f.event=self.f.store.current_event(11)
        # This event was already born unowned; freeze the trusted owner before pairing.
        with transaction(self.f.path) as db:
            claim=self.f.store._claim(db,11)
            db.execute('UPDATE warfare_events SET claim=? WHERE id=?',(json.dumps(claim),self.f.event['id']))
        self.f.event=self.f.store.current_event(11);pair=self.f.pair()
        flags=(344,280) if pair['groups'][0]['members'][0]['clan_id']==self.f.cids[0] else (280,344)
        self.f.store.settle_match(self.f.event['id'],'match-1',self.f.results(pair),flags)
        self.f.now=self.f.event['ends']+1;self.f.store.sync()
        final=self.f.store.finalize(self.f.event['id']);self.assertFalse(final['captured'])
        expected=sorted((m['account'],1) for g in pair['groups'] for m in g['members'] if m['clan_id']==self.f.cids[0])
        self.assertEqual(self.rows("SELECT account,value FROM achievement_counters WHERE metric='clan_defense' ORDER BY account"),expected)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM achievement_counters WHERE metric='clan_capture'"),[(0,)])

    def test_owner_schedule_earlier_than_default_creates_real_event_at_chosen_hour(self):
        self.claim();default=self.f.event['starts']+self.f.store.policy['period_seconds']
        self.f.now=self.f.event['ends']+1;self.f.store.finalize(self.f.event['id'])
        chosen=default//86400*86400+12*3600
        with transaction(self.f.path) as db:benefits.set_next_assault(db,'a0',11,default,chosen,now=self.f.now)
        self.f.now=chosen+1;actual=self.f.store.current_event(11)
        self.assertEqual((actual['starts'],actual['phase']),(chosen,'REGISTRATION'))
        self.assertEqual(actual['id'],f'territory:11:{chosen}')

    def test_owner_later_schedule_waits_and_birth_uses_selected_time_once(self):
        self.claim();default=self.f.event['starts']+self.f.store.policy['period_seconds']
        self.f.now=self.f.event['ends']+1;self.f.store.finalize(self.f.event['id'])
        chosen=default//86400*86400+21*3600
        with transaction(self.f.path) as db:benefits.set_next_assault(db,'a0',11,default,chosen,now=self.f.now)
        self.f.now=default+1;pending=self.f.store.current_event(11)
        self.assertEqual((pending['starts'],pending['phase']),(chosen,'WAIT_ASSAULT'))
        self.f.now=chosen+1;actual=self.f.store.current_event(11)
        self.assertEqual((actual['starts'],actual['phase']),(chosen,'REGISTRATION'))
        self.f.store.sync()
        self.assertEqual(self.rows('SELECT COUNT(*) FROM warfare_events WHERE town=11 AND starts=?',(chosen,)),[(1,)])


class WeeklyRankIntegrationTests(unittest.TestCase):
    def combat(self):
        from tio.battle_state import BattleActor,BattleField
        from tio.combat import Combat
        from tio.weapons import WeaponCatalog
        field=BattleField(8,8,[BattleActor(1,7,1,1,15,100,100),BattleActor(2,8,4,4,15,0,100)],step_cost=1)
        combat=Combat(field,WeaponCatalog());combat.persistence={1:('unused','alice')}
        combat.resources={1:1,2:1};combat.rank_profiles={1:(20,100),2:(20,100)};combat.rank_kills=[(1,2)]
        return combat

    def test_weekly_addition_is_per_opponent_kill_legacy_zero_and_wager_guard(self):
        combat=self.combat();self.assertEqual(ranks.battle_report(combat,7),{1:(10,False)})
        self.assertEqual(ranks.battle_report(combat,7,weekly_rank_per_kill=5),{1:(15,False)})
        combat.wager=True;self.assertEqual(ranks.battle_report(combat,7,weekly_rank_per_kill=5),{1:(10,False)})

    def test_no_weekly_bonus_for_mutants_allies_or_ineligible_low_level_victims(self):
        combat=self.combat();combat.resources[2]=100
        self.assertEqual(ranks.battle_report(combat,7,weekly_rank_per_kill=5),{1:(0,False)})
        combat.resources[2]=1;combat.field.teams={7:0,8:0}
        self.assertEqual(ranks.battle_report(combat,7,weekly_rank_per_kill=5),{1:(10,False)})
        combat.field.teams={};combat.rank_profiles[2]=(1,100)
        self.assertEqual(ranks.battle_report(combat,7,weekly_rank_per_kill=5),{1:(0,False)})
        for value in (-1,True,6,'5'):
            with self.assertRaises(ValueError):ranks.battle_report(combat,7,weekly_rank_per_kill=value)

    def test_weekly_bonus_passes_existing_caps_repeat_and_receipt_protection(self):
        from tests.test_ranks import RankStoreTests
        fixture=RankStoreTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        combat=self.combat();report=ranks.battle_report(combat,7,weekly_rank_per_kill=5)
        fixture.seed(0,level=1)
        with transaction(fixture.path) as db:ranks.settle_ranks(db,'alice','badge-repeat',1,report,repeat_factor=Fraction(1,2))
        self.assertEqual(fixture.state(),(15,0))
        fixture.seed(110,level=1)
        from tio.battle_rewards import settle
        settle(fixture.path,'alice','badge-match',1,rank_report=report)
        self.assertEqual(fixture.state(),(120,0))
        settle(fixture.path,'alice','badge-match',1,rank_report={1:(999,False)})
        self.assertEqual(fixture.state(),(120,0))

    def test_per_death_bonus_preserves_expiry_in_long_match_and_reconnect(self):
        from tio.battle_state import BattleActor
        combat=self.combat();combat.field._actors[3]=BattleActor(3,8,5,5,15,0,100)
        combat.resources[3]=1;combat.rank_profiles[3]=(20,100);combat.rank_kills.append((1,3))
        saved={2:5,3:0}  # First death before the server badge expiry, second after.
        report=ranks.battle_report(combat,7,weekly_rank_per_kill=5,weekly_rank_by_victim=saved)
        self.assertEqual(report,{1:(25,False)})
        self.assertEqual(ranks.battle_report(combat,7,weekly_rank_by_victim=dict(saved)),report)
        self.assertEqual(ranks.battle_report(combat,7,weekly_rank_by_victim={}),{1:(20,False)})
        for invalid in ({999:5},{2:True},{2:6},{'2':5}):
            with self.assertRaises(ValueError):ranks.battle_report(combat,7,weekly_rank_by_victim=invalid)


if __name__=='__main__':unittest.main()
