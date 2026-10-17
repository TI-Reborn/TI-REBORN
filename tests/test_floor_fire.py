from dataclasses import replace
import unittest
import test_special_items
from tio.battle_hazards import add_fire,fire_cells,fire_areas
from tio.battle_item_visuals import visible_cells


class FloorFireTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_special_items.SpecialItemsTests();self.addCleanup(self.fixture.doCleanups)
        self.field,self.combat=self.fixture.prepare(319)

    def test_empty_landing_burns_later_crossing_only_once_per_generation(self):
        add_fire(self.combat,self.field.actor(1),(8,5),1)
        self.assertEqual(self.combat.after_move(2),())
        hp=self.field.actor(2).health
        self.combat.after_move(2,((7,5),(8,5),(9,5)))
        self.assertEqual(self.field.actor(2).health,hp-10)
        self.assertEqual(self.combat.after_move(2,((8,5),)),())

    def test_walls_and_expiry_and_source_death(self):
        self.field.blocked=frozenset({(7,y) for y in range(10)})
        add_fire(self.combat,self.field.actor(1),(6,2),3)
        area=next(iter(fire_areas(self.combat).values()))
        self.assertNotIn((8,2),fire_cells(self.combat,area))
        self.field._actors[1]=replace(self.field.actor(1),health=0)
        self.assertTrue(fire_areas(self.combat))
        self.field._ability_turns[2]=area['expiry']
        self.assertFalse(fire_areas(self.combat))

    def test_visible_fire_hides_behind_walls_and_expired_snapshot_clears(self):
        add_fire(self.combat,self.field.actor(1),(6,2),1)
        self.assertIn((6,2,4),visible_cells(self.field,8))
        self.field._ability_turns[2]=3
        self.assertFalse(visible_cells(self.field,8))

    def test_overlap_does_not_multiply_damage(self):
        add_fire(self.combat,self.field.actor(1),(8,5),1)
        add_fire(self.combat,self.field.actor(1),(8,5),1)
        hp=self.field.actor(2).health
        self.combat.after_move(2,((8,5),))
        self.assertEqual(self.field.actor(2).health,hp-10)
