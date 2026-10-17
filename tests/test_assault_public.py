from contextlib import closing
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from server.assault_public import AssaultPublicStore, AssaultViewRejected, active_badge_places, command, private_command, snapshot
from tio import clan_benefits as b
from tio.clans import schema as clan_schema
from tio.db_transaction import transaction
from tio.territories import schema as warfare_schema


class AssaultPublicTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'shared.sqlite3'
        self.week = b.week_start(1791600000)
        self.now = self.week+b.WEEK+25
        with transaction(self.path) as db:
            clan_schema(db); warfare_schema(db); b.schema(db)
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB)')
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER)')
            for account in ('alice', 'bob', 'carol', 'dana', 'visitor'):
                db.execute('INSERT INTO characters VALUES (?,1,?)', (account, account.title().encode()))
                db.execute('INSERT INTO wallets VALUES (?,3000,0)', (account,))
            for identity, account, name in ((1,'alice','Alpha'), (2,'carol','Бета'), (3,'dana','Gamma')):
                db.execute('INSERT INTO clans(id,name,name_key,leader,influence) VALUES (?,?,?,?,1000)', (identity,name.encode('cp1251'),name.casefold(),account))
            for account, clan in (('alice',1), ('bob',1), ('carol',2), ('dana',3)):
                db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,?,0)', (account,clan))
        self.store = AssaultPublicStore(self.path)

    def event(self, identity, *, week=None, scores=None, accepted=True, legacy=False):
        week = self.week if week is None else week
        scores = scores if scores is not None else [(1,'alice',21,1), (1,'bob',10,1), (2,'carol',32,1), (3,'dana',7,0)]
        ends = week+10000+self.query('SELECT COUNT(*) FROM warfare_events')[0][0]
        totals = {}
        for clan, _, units, _ in scores:
            totals[str(clan)] = totals.get(str(clan),0)+units
        claim = dict(location=6,owner_clan=1,tax_percent=0,revision=1)
        final = dict(event_id=identity,town=6,winner_clan=1,captured=False,claim=claim,scores=totals,benefits_version=0 if legacy else 1)
        with transaction(self.path) as db:
            db.execute('INSERT INTO warfare_events VALUES (?,?,?,?,?,?,?,?,?,1)', (identity,6,ends-100,ends,'FINISHED',3,ends,'{}',json.dumps(claim)))
            db.execute('INSERT INTO warfare_event_receipts VALUES (?,?,0)', (identity,json.dumps(final)))
            for clan, account, units, contested in scores:
                db.execute('INSERT INTO warfare_scores VALUES (?,?,?,?,1,0,10,0,?)', (identity,clan,account,units,contested))
            if accepted:
                b.settle_assault(db,identity)
        return ends

    def close(self, week=None):
        week = self.week if week is None else week
        with transaction(self.path) as db:
            return b.close_week(db,week,now=week+b.WEEK)

    def query(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(sql,args).fetchall()

    def fingerprint(self):
        with closing(sqlite3.connect(self.path)) as db:
            return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()

    def read(self, account='alice', **kwargs):
        return self.store.snapshot(account,now=self.now,**kwargs)

    def test_empty_unclanned_player_no_schema_or_awards_created(self):
        before = self.fingerprint()
        value = self.read('visitor')
        self.assertEqual(value['previous_week']['status'],'pending')
        self.assertEqual(value['current_week']['status'],'current')
        self.assertEqual(value['current_week']['rows'],[])
        self.assertIsNone(value['player']['clan'])
        self.assertIsNone(value['player']['badge'])
        self.assertFalse(value['player']['bonuses']['influence_applies'])
        self.assertEqual(value['player']['bonuses']['influence_factor'],'1')
        self.assertEqual(before,self.fingerprint())

    def test_real_finalization_and_week_closure_public_rows_and_owned_medal(self):
        ends = self.event('previous1'); self.close()
        before = self.fingerprint(); value = self.read()
        week = value['previous_week']
        self.assertEqual(week['status'],'closed')
        self.assertEqual([(row['clan']['name'],row['score'],row['rank_per_kill']) for row in week['rows']], [('Бета','16',5),('Alpha','31/2',4)])
        badge = value['player']['badge']
        self.assertEqual((badge['place'],badge['rank_per_kill'],badge['starts'],badge['expires']), (2,4,self.week+b.WEEK,self.week+2*b.WEEK))
        medals = value['player']['medals']
        self.assertEqual(medals['total'],1)
        self.assertEqual(medals['entries'][0],dict(event_id='previous1',town=6,earned_at=ends,side='defense',place=1,tier='gold',influence_factor='23/20',permanent=True))
        self.assertNotIn('account',json.dumps(value))
        self.assertEqual(value['player']['bonuses']['influence_factor'],'23/20')
        self.assertEqual(before,self.fingerprint())

    def test_current_week_uses_only_accepted_finalized_contested_results(self):
        current = self.week+b.WEEK
        self.event('accepted',week=current)
        self.event('not-settled',week=current,accepted=False)
        with transaction(self.path) as db:
            db.execute('INSERT INTO clan_assault_totals VALUES (?,?,?,?)',('orphan',3,current,99999))
            db.execute('INSERT INTO clan_assault_totals VALUES (?,?,?,?)',('not-settled',3,current,99999))
        value = self.read()
        self.assertEqual([(row['clan']['id'],row['score_units']) for row in value['current_week']['rows']],[(2,32),(1,31)])
        self.assertEqual([row['rank_per_kill'] for row in value['current_week']['rows']],[0,0])
        self.assertIsNone(value['player']['badge'])

    def test_pending_previous_week_does_not_close_or_award_from_read(self):
        self.event('pending'); before = self.fingerprint()
        value = self.read()
        self.assertEqual(value['previous_week']['status'],'pending')
        self.assertEqual(len(value['previous_week']['rows']),2)
        self.assertIsNone(value['player']['badge'])
        self.assertEqual(before,self.fingerprint())
        self.assertEqual(self.query('SELECT * FROM clan_weeks'),[])
        self.assertEqual(self.query('SELECT * FROM clan_weekly_badges'),[])

    def test_badge_current_membership_late_join_switch_leave_and_expiry(self):
        self.event('closed'); self.close()
        with transaction(self.path) as db:
            db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('visitor',2,0)")
        self.assertEqual(self.read('visitor')['player']['bonuses']['weekly_rank_per_kill'],5)
        with transaction(self.path) as db:
            db.execute("UPDATE clan_members SET clan_id=1 WHERE account='visitor'")
        self.assertEqual(self.read('visitor')['player']['bonuses']['weekly_rank_per_kill'],4)
        with transaction(self.path) as db:
            db.execute("DELETE FROM clan_members WHERE account='visitor'")
        self.assertEqual(self.read('visitor')['player']['bonuses']['weekly_rank_per_kill'],0)
        expired = self.store.snapshot('alice',now=self.week+2*b.WEEK)
        self.assertIsNone(expired['player']['badge'])
        self.assertEqual(expired['player']['medals']['total'],1)
        self.assertEqual(expired['player']['bonuses']['medal_influence_factor'],'23/20')

    def test_highest_medal_achievement_and_active_premium_match_real_effect(self):
        self.event('gold')
        self.event('silver',scores=[(1,'bob',40,1),(1,'alice',21,1),(2,'carol',30,1)])
        with transaction(self.path) as db:
            db.execute('CREATE TABLE achievement_awards(account TEXT,id INTEGER,body TEXT)')
            for identity,value in ((1,1.05),(2,1.1)):
                db.execute('INSERT INTO achievement_awards VALUES (?,?,?)',('alice',identity,json.dumps(dict(prizes=[dict(kind=1,value=value)]))))
            db.execute('CREATE TABLE premium_accounts(account TEXT PRIMARY KEY,kind INTEGER,expires INTEGER)')
            db.execute('INSERT INTO premium_accounts VALUES (?,3,?)',('alice',self.now+10))
        value = self.read()['player']
        self.assertEqual(value['medals']['total'],2)
        self.assertEqual(value['bonuses']['medal_influence_factor'],'23/20')
        self.assertEqual(value['bonuses']['achievement_influence_factor'],'11/10')
        self.assertEqual(value['bonuses']['premium_influence_factor'],'3/2')
        self.assertEqual(Fraction(value['bonuses']['influence_factor']),Fraction(759,400))

    def test_old_orphan_badges_hidden_and_unaccepted_medal_fail_closed(self):
        with transaction(self.path) as db:
            db.execute('INSERT INTO clan_weekly_badges VALUES (?,?,?,?,?,?)',(self.week,1,1,5,self.week+b.WEEK,self.week+2*b.WEEK))
        self.assertIsNone(self.read()['player']['badge'])
        with transaction(self.path) as db:
            db.execute("INSERT INTO clan_assault_medals VALUES ('orphan','alice','attack',1,'23/20')")
        with self.assertRaisesRegex(AssaultViewRejected,'не подтверждена'):
            self.read()
        self.assertEqual(self.read('visitor')['player']['medals']['total'],0)

    def test_accepted_score_or_badge_disagreement_fails_without_writes(self):
        self.event('closed'); self.close()
        with transaction(self.path) as db:
            db.execute('UPDATE clan_weekly_badges SET rank_per_kill=5 WHERE clan_id=1')
        before = self.fingerprint()
        with self.assertRaisesRegex(AssaultViewRejected,'значок'):
            self.read()
        self.assertEqual(before,self.fingerprint())

    def test_medal_pagination_is_stable_owner_only_and_highest_from_all_pages(self):
        for index in range(22):
            self.event(f'event{index:02}')
        first = self.read()['player']['medals']
        second = self.read(medal_page=2)['player']['medals']
        self.assertEqual((first['total'],len(first['entries']),first['has_next']), (22,20,True))
        self.assertEqual((len(second['entries']),second['has_next']),(2,False))
        self.assertEqual(first['entries'][0]['event_id'],'event21')
        self.assertEqual(second['entries'][-1]['event_id'],'event00')
        self.assertEqual(self.read('visitor')['player']['medals']['total'],0)

    def test_twenty_clan_limit_and_tie_break_use_the_real_week_receipt(self):
        scores = []
        with transaction(self.path) as db:
            for identity in range(4, 26):
                account = f'owner{identity}'
                db.execute('INSERT INTO characters VALUES (?,1,?)',(account,account.encode()))
                db.execute('INSERT INTO clans(id,name,name_key,leader) VALUES (?,?,?,?)',(identity,account.encode(),account,account))
                db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,?,0)',(account,identity))
                scores.append((identity,account,20,1))
        self.event('twenty',scores=scores)
        receipt = self.close()
        value = self.read()['previous_week']
        self.assertEqual(len(value['rows']),20)
        self.assertEqual([row['clan']['id'] for row in value['rows']],list(range(4,24)))
        self.assertEqual([row['clan']['id'] for row in value['rows']],[row['clan_id'] for row in receipt])
        self.assertEqual([row['rank_per_kill'] for row in value['rows']],[5]+[4]*4+[3]*5+[2]*10)

    def test_native_83_badge_projection_is_accepted_week_place_and_expires(self):
        self.event('closed');self.close();before=self.fingerprint()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            self.assertEqual(active_badge_places(db,now=self.now),{2:1,1:2})
            self.assertEqual(active_badge_places(db,now=self.week+2*b.WEEK),{})
        self.assertEqual(before,self.fingerprint())

    def test_absent_tables_are_not_created_and_read_connection_rejects_write(self):
        bare = self.path.parent/'bare.sqlite3'
        with closing(sqlite3.connect(bare)) as db, db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB)')
            db.execute("INSERT INTO characters VALUES ('alice',1,X'416C696365')")
        value = AssaultPublicStore(bare).snapshot('alice',now=self.now)
        self.assertEqual(value['player']['medals']['total'],0)
        with closing(sqlite3.connect(bare)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('characters',)])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            snapshot(db,'alice',now=self.now)
            with self.assertRaises(sqlite3.OperationalError):db.execute("UPDATE wallets SET credits=0")

    def test_native_private_chat_adapter_unicode_and_all_lines_bounded(self):
        self.event('closed'); self.close()
        for mode in ('top','current','me','medals','medals 2','help'):
            before = self.fingerprint()
            with closing(sqlite3.connect(self.path)) as db:
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                replies = command(db,'alice','!ASSAULT '+mode,now=self.now)
            self.assertTrue(replies)
            for packet in replies:
                self.assertEqual(packet[:6],b'\x22\0\0\0\0\x04')
                self.assertTrue(packet[6:].startswith(b'Assault\0'))
                line = packet[14:-2].decode('utf-16-le')
                self.assertLessEqual(len(line),200)
            self.assertEqual(before,self.fingerprint())
        packet = b'\x21\0'+'!assault me'.encode('utf-16-le')+b'\0\0'
        self.assertTrue(private_command(packet))
        self.assertFalse(private_command(b'\x21\0'+'hello'.encode('utf-16-le')+b'\0\0'))
        self.assertFalse(private_command(b'\x21\0bad'))

    def test_invalid_requests_and_missing_database_do_not_create_files(self):
        for page in (0,True,1.5,10001):
            with self.assertRaises(AssaultViewRejected):self.read(medal_page=page)
        with self.assertRaises(AssaultViewRejected):self.read('absent')
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(RuntimeError):snapshot(db,'alice',now=self.now)
            db.execute('BEGIN')
            for text in ('!assault top 2','!assault medals -1','!assault medals ²','!assault x','!assault medals 1 extra'):
                with self.assertRaises(AssaultViewRejected):command(db,'alice',text,now=self.now)
        absent = self.path.parent/'absent.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):AssaultPublicStore(absent).snapshot('alice')
        self.assertFalse(absent.exists())


if __name__ == '__main__':
    unittest.main()
