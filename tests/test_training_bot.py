import unittest
from dataclasses import replace
from tio.battle_state import BattleActor, BattleField
from tio.training_bot import approach_path, bot_known
from tio.mining_ai import configure_patrols
from tio.protocol.battle_move import BattleMove


class TrainingPathTests(unittest.TestCase):
    def test_mine_detection_is_individual_but_team_detection_is_shared(self):
        near=BattleActor(1,7,5,5,20,150,150,sight_radius=6)
        far=BattleActor(2,7,20,5,20,150,150,sight_radius=6)
        enemy=BattleActor(3,8,8,5,20,100,100)
        field=BattleField(32,32,[near,far,enemy],step_cost=1)
        self.assertIn(3,bot_known(field,7,2)) # Existing team AI.
        configure_patrols(field,(1,2))
        self.assertIn(3,bot_known(field,7,1))
        self.assertNotIn(3,bot_known(field,7,2))
        field.blocked=frozenset({(6,5)})
        self.assertNotIn(3,bot_known(field,7,1))
        field.blocked=frozenset()
        field._actors[1]=replace(near,health=0)
        self.assertNotIn(3,bot_known(field,7,1))
        field._actors[1]=near
        field._actors[3]=replace(enemy,health=0)
        self.assertNotIn(3,bot_known(field,7,1)) # Corpses do not interrupt patrols.

    def test_separate_patrols_stay_in_connected_spawn_neighbourhoods(self):
        actors=[BattleActor(1,7,5,5,20),BattleActor(2,7,20,5,20)]
        field=BattleField(32,32,actors,blocked={(6,5),(6,4)},step_cost=1)
        configure_patrols(field,(1,2),radius=6)
        self.assertNotEqual(field.bot_patrol_waypoints[1],field.bot_patrol_waypoints[2])
        for a in actors:
            region=field.bot_patrol_regions[a.actor_id]
            self.assertFalse(region & field.blocked)
            for x,y in region:self.assertLessEqual(abs(x-a.x)+abs(y-a.y),6)
            path=approach_path(field,a.actor_id,(),{1,2},
                               destination=field.bot_patrol_waypoints[a.actor_id][0],allowed=region)
            self.assertTrue(path)
            self.assertTrue(set(path)<=region)
            self.assertLessEqual(len(path),6)

    def test_route_may_first_move_away_and_respects_ap(self):
        bot=BattleActor(1,7,3,3,3,100,100)
        enemy=BattleActor(2,8,6,3,40,100,100)
        # A U-shaped obstacle requires moving left, away from the target.
        wall={(4,y) for y in range(1,6)}|{(x,1) for x in range(2,5)}|{(x,5) for x in range(2,5)}
        field=BattleField(9,9,[bot,enemy],blocked=wall,step_cost=1)
        path=approach_path(field,1,[enemy],{1,2})
        self.assertTrue(path)
        self.assertLess(path[0][0],bot.x)
        self.assertEqual(abs(path[-1][0]-enemy.x)+abs(path[-1][1]-enemy.y),1)
        field.move(7,BattleMove(1,path[:3]))
        self.assertEqual(field.actor(1).action_points,0)
        with self.assertRaises(ValueError):field.move(7,BattleMove(1,path[3:4]))

    def test_unreachable_target_does_not_block_reachable_target(self):
        bot=BattleActor(1,7,1,1,40)
        trapped=BattleActor(2,8,3,1,40)
        other=BattleActor(3,8,1,6,40)
        field=BattleField(9,9,[bot,trapped,other],blocked={(2,1),(4,1),(3,0),(3,2)},step_cost=1)
        path=approach_path(field,1,[trapped,other],{1,2,3})
        self.assertEqual(path[-1],(1,5))
        self.assertEqual(approach_path(field,1,[trapped],{1,2,3}),())

    def test_hidden_occupancy_not_used_in_planning(self):
        bot=BattleActor(1,7,1,1,40)
        enemy=BattleActor(2,8,5,1,40)
        hidden=BattleActor(3,8,2,1,40)
        field=BattleField(9,9,[bot,enemy,hidden],step_cost=1)
        path=approach_path(field,1,[enemy],{1,2})
        self.assertEqual(path[0],(2,1))
        with self.assertRaises(ValueError):field.move(7,BattleMove(1,path[:1]))
        self.assertEqual(field.actor(1),bot)
        self.assertNotIn((2,1),approach_path(field,1,[enemy],{1,2,3}))
