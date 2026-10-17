"""Achievements use the actual accepted rating transaction, never previews."""
from contextlib import closing
from unittest.mock import patch
import sqlite3
import unittest

from tio import ranked
from tio.db_transaction import transaction


class RankedAchievementTests(unittest.TestCase):
    def setUp(self):
        from tests.test_ranked import RatingTests
        self.f=RatingTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.path=self.f.path

    def rows(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def accept(self,identity,report):
        with transaction(self.path) as db:ranked.settle(db,identity,report,now=10)

    def test_bronze_promotion_win_counts_pre_league_and_actual_post_league(self):
        for identity in ('one','two','promotion'):self.accept(identity,self.f.report())
        self.assertEqual(self.rows("SELECT league,streak FROM ranked_players WHERE account='alice'"),[(2,3)])
        values=dict(self.rows("SELECT metric,value FROM achievement_counters WHERE account='alice'"))
        self.assertEqual(values['bronze_win'],3);self.assertEqual(values['silver_league'],1)
        self.assertEqual(values['league_streak'],3);self.assertNotIn('gold_league',values)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM achievement_events WHERE account='alice'"),[(3,)])

    def test_loss_draw_reset_series_and_do_not_count_bronze_win(self):
        self.accept('win',self.f.report());self.accept('loss',self.f.report(1));self.accept('draw',self.f.report(None))
        self.assertEqual(self.rows('SELECT account,streak FROM ranked_players ORDER BY account'),[('alice',0),('bob',0)])
        self.assertEqual(self.rows("SELECT account,value FROM achievement_counters WHERE metric='bronze_win' ORDER BY account"),[('alice',1),('bob',1)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM achievement_events WHERE event_id='ranked:draw'"),[(2,)])

    def test_team_accounts_each_receive_one_accepted_event_and_restart_retry_is_noop(self):
        report=self.f.report(0,(('alice','carol'),('bob','dave')));self.accept('teams',report)
        before=(self.rows('SELECT * FROM ranked_players'),self.rows('SELECT * FROM achievement_events'),self.rows('SELECT * FROM achievement_counters'))
        self.accept('teams',report)
        self.assertEqual((self.rows('SELECT * FROM ranked_players'),self.rows('SELECT * FROM achievement_events'),self.rows('SELECT * FROM achievement_counters')),before)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM achievement_events'),[(4,)])
        with self.assertRaises(ValueError):self.accept('teams',{**report,'winner':1})
        self.assertEqual(self.rows('SELECT * FROM achievement_events'),before[1])

    def test_second_player_achievement_fault_rolls_back_first_side_ratings_events_and_receipt(self):
        from tio.achievements import ranked_result
        report=self.f.report()
        def fail(db,account,*args,**kwargs):
            if account=='bob':raise ValueError('second account fault')
            return ranked_result(db,account,*args,**kwargs)
        with patch('tio.achievements.ranked_result',side_effect=fail):
            with self.assertRaises(ValueError):self.accept('fault',report)
        self.assertEqual(ranked.snapshot(self.path,'alice'),(ranked.MU,ranked.SIGMA))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('ranked_players','ranked_matches','achievement_events')"),[(0,)])
        self.accept('fault',report)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM ranked_matches'),[(1,)])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM achievement_events'),[(2,)])

    def test_snapshot_conflict_rolls_back_without_any_synthetic_achievement(self):
        accepted=self.f.report();self.accept('one',accepted)
        before=self.rows('SELECT * FROM achievement_events')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):self.accept('stale',accepted)
        self.assertEqual(self.rows('SELECT * FROM achievement_events'),before)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM ranked_matches'),[(1,)])

    def test_legacy_ranked_receipt_is_not_backfilled_with_current_league(self):
        report=self.f.report()
        with patch('tio.achievements.ranked_result'):
            self.accept('legacy',report)
        self.accept('legacy',report)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM sqlite_master WHERE name='achievement_events'"),[(0,)])


if __name__=='__main__':unittest.main()
