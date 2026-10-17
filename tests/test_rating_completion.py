"""Eight authoritative save owners; independent Wall values and UTC archive."""
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wallet_fixture import fund_wallet
from tio import ranked,team_ratings,rating_completion,battle_settlement
from tio.character_identity import alias,initialise
from server.team_ranked import command,reconcile_pending


def utc(month=10,day=8,hour=12,minute=0):
    return datetime(2026,month,day,hour,minute,tzinfo=timezone.utc).timestamp()


class RatingCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ratings.db';self.now=utc()
        self.names=('alice','bob','carol','dave','eve','fred','gina','hank')
        self.teams=(self.names[:4],self.names[4:])
        for name in self.names:fund_wallet(self.path,name,credits=3000,gold=7)

    def admit(self,identity='wall',teams=None,now=None):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            return rating_completion.admit(db,identity,self.teams if teams is None else teams,now=self.now if now is None else now)

    def settle(self,frozen,winner=0,sides=(0,1),now=None):
        report=rating_completion.report(frozen,winner,sides)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            rating_completion.settle(db,frozen['match_id'],report,now=self.now if now is None else now)
        return report

    def listing(self,scope='2026-10'):
        with closing(sqlite3.connect(self.path)) as db:return rating_completion.standings(db,scope=scope)

    def test_four_member_identity_retry_conflict_and_eight_auth_accounts(self):
        frozen=self.admit();self.assertEqual(frozen['version'],2)
        self.assertEqual(frozen,self.admit(teams=tuple(tuple(reversed(t)) for t in self.teams)))
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            self.admit(teams=(('alice','bob','carol','eve'),('dave','fred','gina','hank')))
        second=alias('alice',2);fund_wallet(self.path,second,credits=3000,gold=0)
        with closing(sqlite3.connect(self.path)) as db,db:
            initialise(db);db.execute('INSERT INTO character_identities VALUES (?,?,?)',('alice',2,second))
        with self.assertRaisesRegex(ValueError,'восемь разных'):
            self.admit('alias',teams=(self.teams[0],(second,*self.teams[1][1:])))
        for size in (2,3):
            with self.assertRaises(ValueError):self.admit(str(size),teams=tuple(t[:size] for t in self.teams))

    def test_wall_preserves_existing_pairs_duel_values_and_wallets(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            pair=team_ratings.admit(db,'pairs',(('alice','bob'),('carol','dave')),now=self.now)
            team_ratings.settle(db,'pairs',team_ratings.report(pair,0,(0,1)),now=self.now)
            ranked.settle(db,'duel',dict(winner=0,teams=((('alice',25,25/3),),(('eve',25,25/3),))),now=self.now)
            old={table:db.execute('SELECT * FROM '+table).fetchall() for table in ('ranked_players','ranked_matches','team_rating_values','team_rating_archives','wallets')}
        frozen=self.admit();self.settle(frozen);rows=self.listing()
        self.assertEqual(len(rows),2);self.assertGreater(next(r for r in rows if r['wins'])['mu'],25)
        self.settle(frozen)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(old,{table:db.execute('SELECT * FROM '+table).fetchall() for table in old})
            self.assertEqual(db.execute('SELECT count(*) FROM wall_ranked_matches').fetchone(),(1,))
            self.assertEqual(db.execute('SELECT count(*) FROM wall_ranked_opponents WHERE rated=1').fetchone(),(16,))
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.settle(frozen,winner=1)

    def test_draw_uncontested_and_repeat_accounts_not_new_partner_names(self):
        self.settle(self.admit('draw'),winner=None)
        self.assertEqual([r['place'] for r in self.listing()],[1,1])
        for row in self.listing():self.assertEqual((row['mu'],row['sigma'],row['draws']),(25,25/3,1))
        self.settle(self.admit('quiet'),sides=(0,))
        for index in range(2):self.settle(self.admit('rated'+str(index),now=self.now+index+1))
        previous=self.listing();self.settle(self.admit('repeated',now=self.now+4))
        after=self.listing()
        self.assertEqual([(r['mu'],r['sigma'],r['wins'],r['losses']) for r in previous],
                         [(r['mu'],r['sigma'],r['wins'],r['losses']) for r in after])
        self.assertEqual(after[0]['unrated'],2)

    def test_pending_old_month_archive_no_new_month_reset_of_lifetime(self):
        frozen=self.admit(now=utc(day=31,hour=23,minute=59))
        rating_completion.status(self.path,now=utc(month=11,day=1,hour=0))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT state FROM wall_rating_seasons WHERE season_id='2026-10'").fetchone(),('closing',))
        self.settle(frozen,now=utc(month=11,day=1,hour=0)+1)
        before=self.listing();self.assertTrue(all(r['archived'] for r in before))
        next_frozen=self.admit('new',now=utc(month=11,day=2))
        self.assertEqual(next_frozen['snapshots']['2026-11'][0]['mu'],25)
        self.assertGreater(next_frozen['snapshots']['all'][0]['mu'],25)
        self.settle(next_frozen,now=utc(month=11,day=2))
        self.assertEqual(before,self.listing())
        with closing(sqlite3.connect(self.path)) as db,db:
            old=db.execute("SELECT * FROM wall_rating_archives WHERE season_id='2026-10' ORDER BY team_id").fetchall()
            rating_completion.close_finished(db,utc(month=12,day=1))
            self.assertEqual(old,db.execute("SELECT * FROM wall_rating_archives WHERE season_id='2026-10' ORDER BY team_id").fetchall())

    def test_reward_outbox_rollback_retry_all_eight_no_season_prize(self):
        frozen=self.admit();report=rating_completion.report(frozen,0,(0,1))
        reports=[(name,int(index<4),dict(team_ranked_report=report,now=self.now)) for index,name in enumerate(self.names)]
        battle_settlement.enqueue(self.path,'wall',reports)
        with patch('tio.rating_completion.settle',side_effect=ValueError('Injected settlement fault')):
            with self.assertRaises(ValueError):battle_settlement.apply(self.path,'wall','alice')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute('SELECT 1 FROM wall_rating_values').fetchone())
            self.assertEqual(db.execute("SELECT credits,gold FROM wallets WHERE account='alice'").fetchone(),(3000,7))
        for name in self.names:battle_settlement.apply(self.path,'wall',name)
        self.assertEqual(len(self.listing()),2)
        first=self.listing();battle_settlement.apply(self.path,'wall','alice');self.assertEqual(first,self.listing())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone(),(8,))
            self.assertEqual(set(db.execute('SELECT gold FROM wallets')),{(7,)})
            self.assertEqual(db.execute('SELECT count(*) FROM wall_rating_values').fetchone(),(4,))

    def test_void_missing_recovery_and_unknown_report_version(self):
        frozen=self.admit();self.assertEqual(reconcile_pending(self.path,(),now=self.now),('wall',))
        self.assertFalse(self.listing())
        with self.assertRaisesRegex(ValueError,'Voided'):self.settle(frozen)
        self.assertEqual(reconcile_pending(self.path,(),now=self.now),())

    def test_readonly_empty_status_then_safe_names_paging_and_native_private_command(self):
        with closing(sqlite3.connect(self.path)) as db:
            old=db.total_changes;dto=rating_completion.public_listing(db,now=self.now)
            self.assertEqual(old,db.total_changes);self.assertEqual(dto['rows'],[])
            self.assertEqual(dto['rewards'],[]);self.assertEqual(dto['seasonState'],'not_created')
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='wall_rating_values'").fetchone())
        self.settle(self.admit())
        with closing(sqlite3.connect(self.path)) as db:
            before=db.total_changes;dto=rating_completion.public_listing(db,now=self.now,limit=1)
            self.assertEqual(before,db.total_changes)
            self.assertEqual((dto['total'],dto['hasMore'],len(dto['rows'])),(2,True,1))
            self.assertEqual(dto['rows'][0]['names'],['Удалённый персонаж']*4)
            self.assertNotIn('alice',json.dumps(dto));self.assertNotIn('members',dto['rows'][0])
        packets=command(SimpleNamespace(database=self.path),'!teamrating wall',now=self.now)
        self.assertTrue(packets);self.assertTrue(all(p[:1]==b'\x22' for p in packets))
        for text in ('!teamrating wall 2026-13','!teamrating wall all 101','!seasons wall x'):
            with self.assertRaises(ValueError):command(SimpleNamespace(database=self.path),text,now=self.now)

    def test_invalid_nonfinite_clock_and_stale_snapshot_transaction_roll_back(self):
        with self.assertRaises(ValueError):self.admit(now=float('nan'))
        first=self.admit();second=self.admit('concurrent')
        self.settle(first)
        with self.assertRaisesRegex(ValueError,'snapshot changed'):self.settle(second)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT state FROM wall_ranked_matches WHERE match_id='concurrent'").fetchone(),('pending',))
            self.assertEqual(db.execute('SELECT count(*) FROM wall_ranked_opponents').fetchone(),(16,))


if __name__=='__main__':unittest.main()
