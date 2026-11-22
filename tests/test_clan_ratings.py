from contextlib import closing
from pathlib import Path
import sqlite3
import unittest

from tio.clan_ratings import clans,alliances,standings
from tio.db_transaction import connect


class ClanRatingsTests(unittest.TestCase):
    def test_excluded_clan_and_alliance_do_not_consume_places(self):
        self.fixture.create();self.fixture.join()
        expected=[r for r in standings(self.path) if r['id']!=self.fixture.ids['alice']][0]['id']
        with closing(connect(self.path)) as db,db:
            db.execute('CREATE TABLE rating_exclusions(account TEXT PRIMARY KEY)')
            db.execute("INSERT INTO rating_exclusions VALUES ('alice')")
        before=self.fixture.rows()
        rows=standings(self.path,limit=1)
        self.assertEqual(rows[0]['id'],expected)
        self.assertEqual(rows[0]['place'],1)
        self.assertEqual(standings(self.path,kind='alliances'),())
        self.assertEqual(before,self.fixture.rows())

    def setUp(self):
        from tests.test_alliances import AllianceTests
        self.fixture=AllianceTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.path=self.fixture.path

    def test_current_influence_order_ties_levels_and_paging_without_writes(self):
        with closing(connect(self.path)) as db,db:
            db.execute("UPDATE clans SET influence=200000,level=2 WHERE leader='carol'")
            db.execute("UPDATE clans SET influence=200000,level=0 WHERE leader='dave'")
        before=self.fixture.rows();records=standings(self.path)
        self.assertEqual([r['id'] for r in records],[self.fixture.ids[a] for a in ('carol','dave','alice','bob')])
        self.assertEqual([r['place'] for r in records],[1,2,3,4])
        self.assertEqual(records[2]['leader_name'],b'Alice');self.assertEqual(records[2]['members'],2)
        self.assertEqual([r['id'] for r in standings(self.path,level=1)], [self.fixture.ids[a] for a in ('alice','bob')])
        self.assertEqual(standings(self.path,offset=1,limit=2),records[1:3]);self.assertEqual(before,self.fixture.rows())

    def test_trueskill_averages_current_members_and_excludes_qa(self):
        from tio.ranked import schema
        with closing(connect(self.path)) as db,db:
            schema(db)
            db.executemany('INSERT INTO ranked_players VALUES (?,25,8,?,3,1,0,0,1,0,1)',
                           [('alice',100),('member',201),('bob',125),('carol',400)])
            db.execute('CREATE TABLE rating_exclusions(account TEXT PRIMARY KEY)')
            db.execute("INSERT INTO rating_exclusions VALUES ('carol')")
            db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('qt12345678a',?,0)",
                       (self.fixture.ids['alice'],))
        before=self.fixture.rows()
        rows=standings(self.path,kind='clan_trueskill')
        self.assertEqual([(r['name'],r['rating'],r['place']) for r in rows],
                         [(b'Alpha',150,1),(b'Beta',125,2),(b'Delta',0,3)])
        self.assertEqual(standings(self.path,kind='clan_trueskill',offset=1,limit=1),rows[1:2])
        self.assertEqual(before,self.fixture.rows())
        self.fixture.clans.remove('member')
        self.assertEqual([(r['name'],r['rating']) for r in standings(self.path,kind='clan_trueskill')],
                         [(b'Beta',125),(b'Alpha',100),(b'Delta',0)])

    def test_spending_changes_rating_without_duplicate_influence_and_pending_is_absent(self):
        self.fixture.create();self.fixture.join()
        before=self.fixture.rows();rows=standings(self.path,kind='alliances')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['influence'],185000)
        self.assertEqual(before,self.fixture.rows())
        self.fixture.store.upgrade('alice');self.assertEqual(standings(self.path,kind='alliances')[0]['influence'],165000)
        self.fixture.store.dissolve('alice');before=self.fixture.rows()
        self.assertEqual(standings(self.path,kind='alliances'),());self.assertEqual(before,self.fixture.rows())
        self.fixture.store.restore('alice');self.assertEqual(standings(self.path,kind='alliances')[0]['id'],rows[0]['id'])

    def test_full_alliance_sum_is_not_wrapped_for_sorting_or_mutated(self):
        self.fixture.create();self.fixture.join()
        with closing(connect(self.path)) as db,db:db.execute('UPDATE clans SET influence=4294967295')
        before=self.fixture.rows();row=standings(self.path,kind='alliances')[0]
        self.assertEqual(row['influence'],2*4294967295);self.assertEqual(before,self.fixture.rows())

    def test_invalid_pages_and_missing_database_do_not_create_or_modify_data(self):
        before=self.fixture.rows()
        for options in ({'offset':-1},{'limit':0},{'limit':101},{'level':True},{'kind':'invented'}):
            with self.assertRaises(ValueError):standings(self.path,**options)
        self.assertEqual(before,self.fixture.rows())
        missing=Path(self.path).with_name('never-created.sqlite3')
        with self.assertRaises(sqlite3.OperationalError):standings(missing)
        self.assertFalse(missing.exists())

    def test_empty_pre_feature_database_stays_empty(self):
        path=Path(self.path).with_name('old.sqlite3')
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE existing_history(value TEXT)')
        before=path.read_bytes();self.assertEqual(standings(path),());self.assertEqual(standings(path,kind='alliances'),())
        self.assertEqual(before,path.read_bytes())


if __name__=='__main__':unittest.main()
