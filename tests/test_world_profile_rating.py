"""World standings and the clan profile share one signed earned rating."""
import unittest
from server.public_profile import read_profile
from tio.world_completion import player_top100
from tests import test_player_top100 as fixtures


class WorldProfileRatingTests(unittest.TestCase):
    def test_top100_and_profile_use_the_same_signed_total_rating(self):
        fixture=fixtures.PlayerTop100Tests(methodName='runTest')
        self.addCleanup(fixture.doCleanups)
        db,path=fixture.fixture()
        db.execute('ALTER TABLE ranked_players ADD COLUMN streak INTEGER NOT NULL DEFAULT 0')
        db.execute("UPDATE soldier_ratings SET rating=4294967295 WHERE account='alice'")
        db.commit()
        before=path.read_bytes()
        profile=read_profile(path,account='alice')
        row=next(r for r in player_top100(path) if r['owner']=='alice')
        self.assertEqual((profile.rating,row['rating']),(0x7fffffff,0x7fffffff))
        self.assertEqual(path.read_bytes(),before)
