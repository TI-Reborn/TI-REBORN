from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
import unittest

from tio.db_transaction import connect
from tio.mine_rounds import MineRounds,advance,record_mission
from tio.mine_claims import schema as claim_schema,validate_frozen,frozen_claim


class MineRoundTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'players.db';self.now=7201
        self.store=MineRounds(self.path,clock=lambda:self.now)

    def win(self,identity='mission',side=0,gross=100):
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');return record_mission(db,identity,side,gross,now=self.now)

    def test_all_accounts_share_one_round_and_mission_is_counted_once(self):
        first=self.win();self.assertEqual(first['defense_wins'],1)
        self.assertEqual(self.win()['defense_wins'],1)
        self.win('other',1,200)
        self.assertEqual(MineRounds(self.path,clock=lambda:self.now).state()['raider_wins'],1)
        self.assertEqual(self.store.packets()[0],bytes.fromhex('b0260500000005000000'))
        with self.assertRaises(ValueError):self.win(side=1)
        self.assertEqual(self.store.state()['defense_wins'],1)

    def test_round_winner_changes_tax_only_next_hour_and_old_claim_stays_valid(self):
        with closing(connect(self.path)) as db,db:
            db.execute('CREATE TABLE clans (id INTEGER PRIMARY KEY)');db.execute('INSERT INTO clans VALUES (8)')
            claim_schema(db)
            db.execute('INSERT INTO mine_claims VALUES (13,8,5,1)')
            db.execute("INSERT INTO mine_claim_history VALUES (13,1,8,5,'operator','setup',0)")
            old=frozen_claim(db,13)
        self.win();self.now=10799;self.assertEqual(self.store.state()['defense_points'],5)
        self.now=10800;self.assertEqual(self.store.state()['defense_points'],6)
        with closing(connect(self.path)) as db:
            new=frozen_claim(db,13);self.assertEqual((new['revision'],new['tax_percent']),(2,6))
            self.assertEqual(validate_frozen(db,old),old)
        self.assertEqual(self.store.state()['defense_wins'],0)

    def test_tie_empty_hours_and_restart_do_not_repeat_previous_wins(self):
        self.win('a');self.win('b',1);self.now=10800
        self.assertEqual(self.store.state()['defense_points'],5)
        self.win('c',1);self.now=10800+3600*40
        self.assertEqual(self.store.state()['defense_points'],4)
        self.now+=3600;self.assertEqual(self.store.state()['defense_points'],4)
        self.assertEqual(self.win('c',1)['raider_wins'],0)

    def test_points_are_bounded_and_clock_rollback_keeps_current_round(self):
        self.store.state()
        with closing(connect(self.path)) as db,db:db.execute('UPDATE mine_round_state SET defense_points=10')
        self.win();self.now=10800;self.assertEqual(self.store.state()['defense_points'],10)
        self.now=100;state=self.store.state();self.assertEqual(state['started'],10800)
        self.assertEqual(state['remaining'],3600)
        for invalid in (True,-1,float('nan')):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                with closing(connect(self.path)) as db,db:
                    db.execute('BEGIN IMMEDIATE');advance(db,invalid)

    def test_failed_claim_revision_rolls_back_round_scores_and_history(self):
        with closing(connect(self.path)) as db,db:
            claim_schema(db);db.execute('INSERT INTO mine_claims VALUES (13,8,5,4294967295)')
        self.win();self.now=10800
        with self.assertRaises(ValueError):self.store.state()
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT defense_wins,defense_points FROM mine_round_state').fetchone(),(1,5))
            self.assertEqual(db.execute('SELECT count(*) FROM mine_round_history').fetchone()[0],0)


if __name__=='__main__':unittest.main()
