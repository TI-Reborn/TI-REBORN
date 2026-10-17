import unittest
from tio.team_lobbies import TeamLobbies


class TeamLobbyTests(unittest.TestCase):
    def test_readiness_leader_bot_limit_and_waiting_for_real_opponent(self):
        q=TeamLobbies();room=q.create(1,4,0,1)
        with self.assertRaises(ValueError):q.start(1)
        q.set_ready(1,True)
        q.start(1)
        self.assertEqual(room.bots,3)
        self.assertFalse(q.pairs())
        q.set_ready(1,False)
        q.join(room.identity,2,0,1)
        self.assertFalse(room.ready)
        q.set_ready(1,True);q.set_ready(2,True)
        with self.assertRaises(ValueError):q.start(2)
        q.start(1)
        self.assertEqual(room.bots,2)
        self.assertEqual(q.pairs(),())
        with self.assertRaises(ValueError):q.join(room.identity,3,0,1)
        other=q.create(3,4,0,1);q.join(other.identity,4,0,1)
        q.set_ready(3,True);q.set_ready(4,True);q.start(3)
        self.assertEqual(q.pairs(),((room,other),))
        q.consume(room,other)
        self.assertFalse(q.membership)

    def test_two_player_teams_and_filters(self):
        q=TeamLobbies();first=q.create(1,1,0,2)
        for owner,band,soldiers in ((2,1,2),(3,0,1)):
            q.create(owner,1,band,soldiers);q.set_ready(owner,True);q.start(owner)
        q.set_ready(1,True);q.start(1)
        self.assertEqual(first.bots,1);self.assertEqual(q.pairs(),((q.room(3),first),))
        other=q.create(4,1,0,2);q.set_ready(4,True);q.start(4)
        # The oldest compatible room is the one-fighter room3. It admits
        # either larger opponent at one fighter, then chooses FIFO room1.
        self.assertEqual(q.pairs(),((q.room(3),first),))

    def test_team_prefers_largest_common_squad_then_fifo(self):
        q=TeamLobbies();rooms=[]
        for owner,count in ((1,3),(2,1),(3,2),(4,3)):
            room=q.create(owner,1,0,count);rooms.append(room)
            q.set_ready(owner,True);q.start(owner)
        self.assertEqual(q.pairs(),((rooms[0],rooms[3]),(rooms[1],rooms[2])))

    def test_leave_kick_disconnect_and_unready_cancel_search(self):
        q=TeamLobbies();r=q.create(1,4,0,1);q.join(r.identity,2,0,1)
        with self.assertRaises(ValueError):q.leave(2,1)
        for owner in (1,2):q.set_ready(owner,True)
        q.start(1);q.set_ready(2,False)
        self.assertFalse(r.searching);self.assertEqual(r.bots,0)
        q.leave(1,2);self.assertFalse(r.ready)
        q.leave(1);self.assertFalse(q.rooms)

    def test_full_teams_no_bots_and_duplicate_creation(self):
        q=TeamLobbies();r=q.create(1,1,2,3)
        self.assertIs(q.create(1,1,2,3),r)
        q.join(r.identity,2,2,3)
        with self.assertRaises(ValueError):q.join(r.identity,3,2,3)
        for i in (1,2):q.set_ready(i,True)
        q.start(1);self.assertEqual(r.bots,0)

    def test_two_single_leaders_fill_both_wall_teams(self):
        q=TeamLobbies()
        rooms=[]
        for owner in (1,2):
            room=q.create(owner,4,0,1);rooms.append(room)
            self.assertEqual(room.bots,0)
            q.set_ready(owner,True);q.start(owner)
            self.assertEqual(room.bots,3)
        self.assertEqual(q.pairs(),(tuple(rooms),))
