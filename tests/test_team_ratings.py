from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wallet_fixture import fund_wallet
from tio import ranked, rating_seasons, team_ratings, battle_settlement
from tio.character_identity import initialise as identity_schema, alias
from server.team_ranked import command, reconcile_pending


def stamp(year=2026,month=10,day=8,hour=12,minute=0):
    return datetime(year,month,day,hour,minute,tzinfo=timezone.utc).timestamp()


class TeamRatingTests(unittest.TestCase):
    def test_exclusion_filters_before_places_and_public_total(self):
        self.apply(self.admit())
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE rating_exclusions(account TEXT PRIMARY KEY)')
            db.execute("INSERT INTO rating_exclusions VALUES ('alice')")
            rows=team_ratings.standings(db,scope='all',limit=1)
            self.assertEqual(rows[0]['members'],['carol','dave'])
            self.assertEqual(rows[0]['place'],1)
            from tio.rating_completion import public_listing
            dto=public_listing(db,format='pairs',scope='all',now=self.now)
            self.assertEqual(dto['total'],1)
            self.assertFalse(dto['hasMore'])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ratings.sqlite3';self.now=stamp()
        for account in ('alice','bob','carol','dave','eve','fred'):fund_wallet(self.path,account,credits=3000,gold=0)

    def admit(self,match='one',teams=(('alice','bob'),('carol','dave')),now=None):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            return team_ratings.admit(db,match,teams,now=self.now if now is None else now)

    def apply(self,frozen,*,winner=0,sides=(0,1),now=None):
        value=team_ratings.report(frozen,winner,sides)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            team_ratings.settle(db,frozen['match_id'],value,now=self.now if now is None else now)
        return value

    def table(self,scope='2026-10'):
        with closing(sqlite3.connect(self.path)) as db:return team_ratings.standings(db,scope=scope)

    def test_fixed_identity_sorted_pair_and_admission_retry(self):
        one=self.admit();again=self.admit(teams=(('bob','alice'),('dave','carol')))
        self.assertEqual(one,again)
        self.assertEqual(team_ratings.identity(('alice','bob')),team_ratings.identity(('bob','alice')))
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.admit(teams=(('alice','carol'),('bob','dave')))

    def test_both_fixed_pairs_lifetime_season_once_and_duel_untouched(self):
        frozen=self.admit();value=self.apply(frozen)
        first=self.table();self.assertEqual(len(first),2)
        winner=next(row for row in first if row['wins']);loser=next(row for row in first if row['losses'])
        self.assertEqual(winner['members'],['alice','bob']);self.assertEqual(loser['members'],['carol','dave'])
        self.assertGreater(winner['mu'],25);self.assertLess(loser['mu'],25)
        self.assertEqual(self.table('all')[0]['skill'],winner['skill'])
        self.apply(frozen);self.assertEqual(first,self.table())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_players'").fetchone())
            self.assertEqual(db.execute('SELECT count(*) FROM team_ranked_matches').fetchone()[0],1)
        self.assertEqual(ranked.snapshot(self.path,'alice'),(ranked.MU,ranked.SIGMA))
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.apply(frozen,winner=1)

    def test_draw_keeps_gaussian_and_counts_equal_place(self):
        frozen=self.admit();self.apply(frozen,winner=None)
        rows=self.table();self.assertEqual([r['place'] for r in rows],[1,1])
        for row in rows:
            self.assertEqual((row['mu'],row['sigma'],row['skill'],row['draws']),(ranked.MU,ranked.SIGMA,0,1))

    def test_one_sided_or_empty_battle_is_audited_without_rating(self):
        for index,sides in enumerate(((),(0,),(1,))):
            self.apply(self.admit(str(index)),sides=sides)
        self.assertFalse(self.table())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT rated FROM team_ranked_matches').fetchall(),[(0,),(0,),(0,)])
            self.assertEqual(set(db.execute('SELECT mu,sigma,wins,losses,draws,unrated FROM team_rating_values')),
                             {(ranked.MU,ranked.SIGMA,0,0,0,3)})
            self.assertEqual(db.execute('SELECT sum(rated) FROM team_ranked_opponents').fetchone()[0],0)

    def test_auth_opposing_pair_limit_survives_partner_rotation(self):
        for index in range(3):self.apply(self.admit(str(index),now=self.now+index),now=self.now+index)
        before=next(r for r in self.table() if r['members']==['alice','bob'])
        frozen=self.admit('rotated',teams=(('alice','bob'),('carol','eve')),now=self.now+4)
        self.apply(frozen,now=self.now+4)
        after=next(r for r in self.table() if r['members']==['alice','bob'])
        self.assertEqual((after['mu'],after['sigma'],after['wins']),(before['mu'],before['sigma'],3))
        self.assertEqual(after['unrated'],1)
        expired=self.admit('after-window',now=self.now+86405);self.apply(expired,now=self.now+86405)
        self.assertEqual(next(r for r in self.table() if r['members']==['alice','bob'])['wins'],4)

    def alias_owner(self,login,slot=2):
        owner=alias(login,slot);fund_wallet(self.path,owner,credits=3000,gold=0)
        with closing(sqlite3.connect(self.path)) as db,db:
            identity_schema(db);db.execute('INSERT INTO character_identities VALUES (?,?,?)',(login,slot,owner))
        return owner

    def test_same_authenticated_login_cannot_be_teammate_or_opponent(self):
        second=self.alias_owner('alice')
        for teams in (((('alice',second),('carol','dave'))),((('alice','bob'),(second,'dave')))):
            with self.assertRaisesRegex(ValueError,'четыре разных'):self.admit(teams=teams)

    def test_character_rotation_cannot_reset_opposing_pair_limit(self):
        for index in range(3):self.apply(self.admit(str(index),now=self.now+index),now=self.now+index)
        owner=self.alias_owner('alice')
        frozen=self.admit('new-character',teams=((owner,'bob'),('carol','dave')),now=self.now+4)
        self.apply(frozen,now=self.now+4)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT rated FROM team_ranked_matches WHERE match_id='new-character'").fetchone(),(0,))

    def test_month_boundary_retains_pending_then_seals_archive(self):
        last=stamp(day=31,hour=23,minute=59);november=stamp(month=11,day=1,hour=0)
        frozen=self.admit(now=last)
        self.admit('november',teams=(('eve','fred'),('alice','bob')),now=november)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(dict(db.execute('SELECT season_id,state FROM team_rating_seasons')),
                             {'2026-10':'closing','2026-11':'open'})
            self.assertFalse(db.execute('SELECT 1 FROM team_rating_archives').fetchone())
        self.apply(frozen,now=november+1)
        rows=self.table();self.assertEqual(len(rows),2);self.assertTrue(all(r['archived'] for r in rows))
        with closing(sqlite3.connect(self.path)) as db,db:
            before=db.execute('SELECT * FROM team_rating_archives').fetchall()
            rating_seasons.close_finished(db,november+86400)
            self.assertEqual(before,db.execute('SELECT * FROM team_rating_archives').fetchall())
            self.assertEqual(db.execute("SELECT state FROM team_rating_seasons WHERE season_id='2026-10'").fetchone(),('archived',))

    def test_new_month_starts_fresh_lifetime_carries_and_old_rows_preserved(self):
        self.apply(self.admit());old=self.table()
        frozen=self.admit('new',now=stamp(month=11,day=1))
        self.assertEqual(frozen['snapshots']['2026-11'][0]['mu'],ranked.MU)
        self.assertGreater(frozen['snapshots']['all'][0]['mu'],ranked.MU)
        self.apply(frozen,now=stamp(month=11,day=1)+1)
        self.assertEqual(old[0]['skill'],self.table()[0]['skill'])
        self.assertEqual(self.table('all')[0]['wins'],2)
        self.assertEqual(self.table('2026-11')[0]['wins'],1)

    def test_void_loading_shutdown_or_fault_preserves_both_ratings(self):
        frozen=self.admit()
        with closing(sqlite3.connect(self.path)) as db,db:
            self.assertTrue(team_ratings.void(db,'one','loading_timeout',now=self.now+60))
            self.assertFalse(team_ratings.void(db,'one','graceful_shutdown',now=self.now+61))
            self.assertFalse(db.execute('SELECT 1 FROM team_rating_values').fetchone())
            self.assertFalse(db.execute('SELECT 1 FROM team_ranked_opponents').fetchone())
        with self.assertRaisesRegex(ValueError,'Voided'):self.apply(frozen)

    def test_pending_reconciliation_keeps_actual_checkpoint_and_reward_jobs(self):
        self.admit('kept');self.admit('outbox',teams=(('eve','fred'),('carol','dave')))
        self.admit('lost',teams=(('alice','bob'),('eve','fred')))
        self.assertEqual(reconcile_pending(self.path,('kept','outbox'),now=self.now),('lost',))
        self.assertFalse(reconcile_pending(self.path,('kept','outbox'),now=self.now))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(dict(db.execute('SELECT match_id,state FROM team_ranked_matches')),
                             {'kept':'pending','outbox':'pending','lost':'void'})

    def test_conflicting_frozen_snapshot_rolls_back_all_teams_and_scopes(self):
        frozen=self.admit()
        with closing(sqlite3.connect(self.path)) as db,db:
            team=team_ratings.identity(('carol','dave'))
            db.execute('INSERT INTO team_rating_values VALUES (?,?,?,?,?,?,?,?,?,?,?)',('2026-10',team,31,7,80,1,0,0,0,1,self.now))
        with self.assertRaisesRegex(ValueError,'snapshot changed'):self.apply(frozen)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM team_rating_values').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT state FROM team_ranked_matches').fetchone(),('pending',))
            self.assertFalse(db.execute('SELECT 1 FROM team_ranked_opponents').fetchone())

    def test_wallet_and_team_rating_failure_rollback_then_outbox_retry(self):
        frozen=self.admit();value=team_ratings.report(frozen,0,(0,1))
        battle_settlement.initialise(self.path)
        battle_settlement.enqueue(self.path,'one',[('alice',1,dict(team_ranked_report=value,now=self.now))])
        with patch('tio.team_ratings.settle',side_effect=ValueError('Injected rating failure')):
            with self.assertRaises(ValueError):battle_settlement.apply(self.path,'one','alice')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_rewards'").fetchone())
            self.assertFalse(db.execute('SELECT 1 FROM team_rating_values').fetchone())
        battle_settlement.apply(self.path,'one','alice');before=self.table()
        battle_settlement.apply(self.path,'one','alice');self.assertEqual(before,self.table())

    def test_normal_reward_validation_and_escaped_fixed_pair_outcome(self):
        value=team_ratings.report(self.admit(),0,(0,1))
        team_ratings.validate_reward('alice',1,value)
        team_ratings.validate_reward('alice',0,value,escaped=True)
        with self.assertRaisesRegex(ValueError,'mismatch'):team_ratings.validate_reward('alice',0,value)
        with self.assertRaisesRegex(ValueError,'missing'):team_ratings.validate_reward('eve',1,value)

    def test_native_chat_current_archive_all_and_no_login_aliases(self):
        frozen=self.admit();self.apply(frozen)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB)')
            db.executemany('INSERT INTO characters VALUES (?,1,?)',[(a,a.capitalize().encode()) for a in ('alice','bob','carol','dave')])
        session=SimpleNamespace(database=self.path)
        for text in ('!teamrating','!teamrating all','!teamrating 2026-10','!seasons'):
            replies=command(session,text,now=self.now)
            self.assertTrue(replies);self.assertTrue(all(p[:1]==b'\x22' for p in replies))
        replies=command(session,'!teamrating',now=self.now)
        self.assertTrue(any('Alice + Bob' in p.decode('utf-16-le',errors='ignore') for p in replies))
        self.assertIsNone(command(session,'обычное сообщение',now=self.now))
        for text in ('!teamrating invalid','!teamrating all 0','!teamrating all nope','!seasons extra'):
            with self.assertRaises(ValueError):command(session,text,now=self.now)

    def test_season_year_rollover_and_strict_clock(self):
        identity,first,last=rating_seasons.boundary(stamp(month=12,day=31))
        self.assertEqual(identity,'2026-12');self.assertEqual(last,datetime(2027,1,1,tzinfo=timezone.utc).timestamp())
        for bad in (True,float('nan'),float('inf'),'today'):
            with self.assertRaises(ValueError):rating_seasons.boundary(bad)


if __name__=='__main__':unittest.main()
