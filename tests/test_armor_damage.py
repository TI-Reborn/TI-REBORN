import unittest,struct
from dataclasses import replace
import test_combat
from tio.armor import ArmorCatalog,mitigate
from tio.protocol.item_list import encode_item_list
from tio.protocol.battle_attack import AttackRequest
from tio.battle_state import BattleActor


def armor(i,template,slot):
    return replace(test_combat.item(i,template,equipped=True),location_raw=slot)


class ArmorDamageTests(unittest.TestCase):
    setup_combat=test_combat.CombatTests.setup_combat

    def test_formula_and_backpack_species_slots(self):
        self.assertEqual(mitigate(50,85),(27,23))
        self.assertEqual(mitigate(50,160),(19,31))
        self.assertEqual(mitigate(0,160),(0,0))
        self.assertEqual(mitigate(1,10000),(1,0))
        catalog=ArmorCatalog()
        items=(armor(1,243,4),test_combat.item(2,252),armor(3,266,4),armor(4,242,8))
        bag=encode_item_list(2,items)
        self.assertEqual(catalog.defense(bag,human=True),85)
        self.assertEqual(catalog.defense(bag,human=False),160)
        with self.assertRaises(ValueError):catalog.defense(encode_item_list(2,(armor(1,243,4),armor(2,252,4))),human=True)
        self.assertEqual(catalog.defense(encode_item_list(2,(armor(1,251,1),)),human=True),63)

    def test_bullet_packet_and_statistics_use_reduced_damage(self):
        f,c=self.setup_combat()
        c.register(2,encode_item_list(2,(armor(201,243,4),)),human=True)
        packets=c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(f.actor(2).health,92) # raw16 ->8
        self.assertEqual(struct.unpack_from('<H',packets[0],57)[0],8)
        self.assertEqual(c.statistics[7]['damage_dealt'],8)
        self.assertEqual(c.statistics[8]['damage_received'],8)
        c.register(2,encode_item_list(2,()),human=True)
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(f.actor(2).health,76)

    def test_bite_against_dog_armor_and_overkill(self):
        f,c=self.setup_combat()
        f._actors[1]=replace(f.actor(1),x=4)
        c.register(1,encode_item_list(1,()),human=False)
        c.register(2,encode_item_list(2,(armor(201,266,4),)),human=False)
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(f.actor(2).health,81)
        f._actors[2]=replace(f.actor(2),health=2)
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(c.statistics[7]['damage_dealt'],21)
        self.assertEqual(c.statistics[7]['kills'],1)

    def test_grenade_reduces_each_victim_including_friendly(self):
        ally=BattleActor(3,7,5,2,15,100,100)
        f,c=self.setup_combat(317,None,extra=(ally,))
        c.register(2,encode_item_list(2,(armor(201,243,4),)),human=True)
        c.register(3,encode_item_list(3,(armor(301,266,4),)),human=False)
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual((f.actor(2).health,f.actor(3).health),(47,62)) # raw99
        self.assertEqual(c.statistics[7]['damage_dealt'],53)
        self.assertEqual(c.statistics[7]['damage_received'],38)

    def test_miss_does_not_report_absorption(self):
        f,c=self.setup_combat()
        c.register(2,encode_item_list(2,(armor(201,243,4),)),human=True)
        c.catalog.sources[301]={**c.catalog.sources[301],'accuracy':'0'}
        packet=c.attack(7,AttackRequest(1,5,1))[0]
        self.assertEqual(f.actor(2).health,100)
        self.assertEqual(struct.unpack_from('<H',packet,57)[0],0)
