import unittest
from tio.visibility import clear_sight,visible_actors
from tio.battle_state import BattleActor,BattleField


class VisibilityTests(unittest.TestCase):
    def test_individual_radius_boundary_and_shared_dog_sight(self):
        from dataclasses import replace
        human=BattleActor(1,7,1,1,40,100,100,sight_radius=9)
        enemy=BattleActor(2,8,10,1,40,100,100)
        def seen(*actors):
            return visible_actors(BattleField(32,32,actors,step_cost=1),7)
        self.assertIn(2,seen(human,enemy))
        self.assertNotIn(2,seen(human,replace(enemy,x=11)))
        self.assertNotIn(2,seen(human,replace(enemy,y=2)))
        dog=BattleActor(3,7,1,2,40,100,100,sight_radius=12)
        self.assertIn(2,seen(human,dog,replace(enemy,x=12)))
        self.assertNotIn(2,seen(human,replace(dog,health=0),replace(enemy,x=12)))

    def test_walls_corners_and_symmetry(self):
        for start,end,wall,expected in (
            ((1,1),(5,1),{(3,1)},False),
            ((1,1),(5,2),{(3,1)},False),
            ((1,1),(5,1),{(3,2)},True),
            ((1,1),(3,3),{(2,1)},False),
            ((1,1),(1,5),{(1,3)},False)):
            self.assertEqual(clear_sight(start,end,wall),expected)
            self.assertEqual(clear_sight(end,start,wall),expected)

    def test_squad_shared_sight_death_and_distance(self):
        own=BattleActor(1,7,1,2,40,100,100)
        enemy=BattleActor(2,8,5,2,40,100,100)
        field=BattleField(32,32,[own,enemy],blocked={(3,2)},step_cost=1)
        self.assertEqual(visible_actors(field,7),{1})
        ally=BattleActor(3,7,5,4,40,100,100)
        field=BattleField(32,32,[own,enemy,ally],blocked={(3,2)},step_cost=1)
        self.assertEqual(visible_actors(field,7),{1,2,3})
        from dataclasses import replace
        field=BattleField(32,32,[own,enemy,replace(ally,health=0)],blocked={(3,2)},step_cost=1)
        self.assertEqual(visible_actors(field,7),{1,3})
        field=BattleField(32,32,[own,replace(enemy,x=25)],step_cost=1)
        self.assertEqual(visible_actors(field,7),{1})
