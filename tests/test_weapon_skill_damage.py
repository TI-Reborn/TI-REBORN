"""Combat regressions for class-specific proficiency, not just its helper math."""
import unittest
from dataclasses import replace

from tio.protocol.battle_attack import AttackRequest
from tio.protocol.item_action import ItemAction
from tio.protocol.item_list import encode_item_list
from tio.weapon_proficiency import SAVED,bits
from tio.weapons import WeaponCatalog
from test_combat import item
from test_weapon_proficiency import profile,change,setup


class WeaponSkillDamageTests(unittest.TestCase):
    def test_every_original_weapon_selects_its_own_skill(self):
        # Original CFG categories, matched to the native selector a7abfc.
        expected={
            'Melee':(300,326,327,328,329,333,335,337,341),
            'Light':(301,331,332),
            'Heavy':(302,307,308,314,315,322,323,324,336),
            'Distance':(310,311,312,313,338),
            'Automatic':(303,304,305,306,309,330,339),
            'Throwing':(316,317,319,321,325,334,340),
        }
        actual=WeaponCatalog().weapons
        self.assertEqual(set(actual)-{65489},{i for group in expected.values() for i in group})
        self.assertEqual(actual[65489].weapon_type,'Melee')
        for kind,identities in expected.items():
            for identity in identities:self.assertEqual(actual[identity].weapon_type,kind)

    def test_each_combat_class_uses_only_its_own_proficiency(self):
        # Guide p106: skill35=85%, 75=118.333%, 100=139.1667%, 200=222.5%.
        # Fixed minimum roll and unarmored target isolate actual dealt damage.
        examples=((326,0,(17,23,27,44)),(301,1,(13,18,22,35)),
                  (302,2,(42,59,69,111)),(310,3,(25,35,41,66)),
                  (304,4,(42,59,69,111)),(317,5,(84,117,137,220)))
        for weapon,index,damages in examples:
            for skill,damage in zip((35,75,100,200),damages):
                for other in (35,200):
                    with self.subTest(weapon=weapon,skill=skill,other_skills=other):
                        p=change(profile(26),{**{k:bits(other) for k in SAVED},SAVED[index]:bits(skill)})
                        f,c=setup(weapon,packet=p)
                        distance=4 if weapon==317 else c.catalog.weapons[weapon].min_range
                        f._actors[2]=replace(f.actor(2),x=1+distance)
                        c.attack(7,AttackRequest(1,1+distance,1))
                        self.assertEqual(f.actor(2).health,1000-damage)

    def test_switching_weapon_uses_new_class_without_changing_saved_skills(self):
        p=change(profile(26),{SAVED[4]:bits(75),SAVED[1]:bits(100)})
        f,c=setup(packet=p)
        inventory=encode_item_list(1,(item(1,304,1,True),item(2,7,100),
                                     item(3,301),item(4,3,100),item(5,302),item(6,4,100)))
        c.register(1,inventory,human=True,pet_packet=p)
        f._actors[2]=replace(f.actor(2),x=2)
        for instance,damage in ((1,59),(3,22),(5,42),(1,59)):
            c.equip(7,ItemAction(1,instance,4))
            before=f.actor(2).health
            c.attack(7,AttackRequest(1,2,1))
            self.assertEqual(before-f.actor(2).health,damage)
        # Re-entering a battle with the updated profile retains the benefit.
        f2,c2=setup(packet=c.proficiencies[1])
        f2._actors[2]=replace(f2.actor(2),x=2)
        c2.attack(7,AttackRequest(1,2,1))
        self.assertEqual(f2.actor(2).health,941)
