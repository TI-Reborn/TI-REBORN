import sqlite3
import unittest
from tio.rating_visibility import excluded
import test_player_top100
from tio import world_completion


class VisibilityTests(unittest.TestCase):
    def test_wall_fixture_is_filtered_before_paging_without_writes(self):
        from tio import rating_completion
        db=sqlite3.connect(':memory:')
        rating_completion.schema(db)
        for i,members in enumerate((['qs9001ec02a','bob','carol','dave'],['alice','bob','carol','dave'])):
            key=str(i)*64
            db.execute('INSERT INTO wall_rating_teams VALUES (?,?)',(key,__import__('json').dumps(members)))
            db.execute('INSERT INTO wall_rating_values VALUES (?,?,?,?,?,?,?,?,?,?,?)',('all',key,25,8,200-i,1,0,0,0,1,0))
        before=db.total_changes
        rows=rating_completion.standings(db,scope='all',limit=1)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['members'],['alice','bob','carol','dave'])
        self.assertEqual(rows[0]['place'],1)
        self.assertEqual(db.total_changes,before)
        db.close()

    def test_reserved_namespace_slots_and_explicit_marks_are_read_only(self):
        db=sqlite3.connect(':memory:')
        for name in ('qs9001ec02a','qer511fe02da','@character:qs9001ec02a:2'):
            self.assertTrue(excluded(db,name))
        for name in ('queen','qwerty','admin','test','player_two'):
            self.assertFalse(excluded(db,name))
        db.execute('CREATE TABLE rating_exclusions(account TEXT PRIMARY KEY)')
        db.execute("INSERT INTO rating_exclusions VALUES ('custom_fixture')")
        before=db.total_changes
        self.assertTrue(excluded(db,'@character:custom_fixture:2'))
        self.assertEqual(db.total_changes,before)
        db.close()

    def test_hidden_high_score_does_not_consume_top_page(self):
        fixture=test_player_top100.PlayerTop100Tests()
        try:
            db,path=fixture.fixture()
            db.execute("INSERT INTO accounts VALUES ('qs9001ec02a')")
            db.execute("INSERT INTO characters VALUES ('qs9001ec02a',1,?, 'testqa')",(b'HiddenQA',))
            db.execute("INSERT INTO soldier_ratings VALUES ('qs9001ec02a',1,2147483647)")
            db.execute("INSERT INTO owned_pets SELECT 'qs9001ec02a',pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account='alice'")
            db.commit()
            before=db.total_changes
            rows=world_completion.players(db,limit=1)
            self.assertEqual([r['name'] for r in rows],[b'Alice'])
            self.assertEqual(rows[0]['place'],1)
            self.assertEqual(db.total_changes,before)
        finally:
            fixture.doCleanups()
