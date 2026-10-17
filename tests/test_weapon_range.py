import unittest
from dataclasses import replace
from types import SimpleNamespace
from tio.weapons import WeaponCatalog
from tio.protocol.battle_attack import AttackRequest
from tio.protocol.abilities import AbilityEntry
from tio.abilities import AbilityCatalog,AbilityLevel
import test_combat
from test_weapon_proficiency import profile


class WeaponRangeTests(unittest.TestCase):
    def test_original_intervals_and_accuracy(self):
        c=WeaponCatalog()
        # Explicit native results, including single-precision accuracy ties
        # and extended-precision damage truncation rather than algebraic math.
        cases=[(304,1,(50,75),89),(304,5,(43,65),77),(304,9,(37,56),65),
               (302,1,(50,75),90),(302,5,(10,15),90),
               (307,5,(42,56),88),(312,7,(50,75),85)]
        for identity,distance,damage,accuracy in cases:
            with self.subTest(weapon=identity,distance=distance):
                self.assertEqual(c.distance_damage(identity,distance),damage)
                self.assertEqual(c.accuracy(identity,distance),accuracy)
        self.assertEqual(c.distance_damage(312,c.weapons[312].max_range),(60,90))
        self.assertEqual(c.distance_damage(304,9,3),(39,58))
        self.assertEqual(c.distance_damage(304,0),(50,75))
        self.assertEqual(c.accuracy(309,1),95)
        self.assertEqual(c.accuracy(333,1,20),95)

    def test_attack_range_changes_damage_before_skill_and_armor(self):
        for identity,distance,expected in ((304,1,42),(304,9,31),(302,1,42),(302,5,8),(312,18,51)):
            with self.subTest(weapon=identity,distance=distance):
                cata=WeaponCatalog();w=cata.weapons[identity]
                f,c=test_combat.CombatTests().setup_combat(identity,w.ammo_id,100)
                c.register(1,c.inventories[1],human=True,pet_packet=profile())
                f._actors[1]=replace(f.actor(1),sight_radius=20)
                f._actors[2]=replace(f.actor(2),x=1+distance,health=1000,max_health=1000)
                c.attack(7,AttackRequest(1,1+distance,1))
                self.assertEqual(f.actor(2).health,1000-expected)
                self.assertEqual(f.actor(1).action_points,40-w.attack_ap)

    def test_same_roll_hits_close_ak_but_misses_far(self):
        for distance,hit in ((1,True),(9,False)):
            f,c=test_combat.CombatTests().setup_combat(304,7,10)
            f._actors[2]=replace(f.actor(2),x=1+distance)
            c.rng=SimpleNamespace(randrange=lambda n:80,randint=lambda a,b:a)
            packet=c.attack(7,AttackRequest(1,1+distance,1))[0]
            self.assertEqual(int.from_bytes(packet[35:39],'little'),0 if hit else 2)
            self.assertEqual(f.actor(2).health<100,hit)
            self.assertEqual(f.actor(1).action_points,35)
            from tio.protocol.item_list import decode_item_list
            self.assertEqual(next(i.count for i in decode_item_list(c.inventories[1])[1] if i.template_id==7),5)

    def test_learned_accuracy_applies_only_to_its_weapon_class(self):
        catalog=AbilityCatalog([AbilityLevel(i,1,dict(name='test',value=str(value))) for i,value in ((10,10),(17,15))])
        learned=(AbilityEntry(10,1,0,0),AbilityEntry(17,1,0,0))
        for identity,roll,hit in ((301,80,True),(326,90,True),(304,90,False)):
            w=WeaponCatalog().weapons[identity]
            f,c=test_combat.CombatTests().setup_combat(identity,w.ammo_id,100)
            c.configure_accuracy(1,learned,catalog)
            f._actors[1]=replace(f.actor(1),x=4)
            c.rng=SimpleNamespace(randrange=lambda n:roll,randint=lambda a,b:a)
            c.attack(7,AttackRequest(1,5,1))
            self.assertEqual(f.actor(2).health<100,hit)
        c.configure_accuracy(1,(),catalog)
        self.assertEqual(c.weapon_accuracy_bonuses[1],{})
