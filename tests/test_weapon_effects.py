import unittest
from dataclasses import replace
from types import SimpleNamespace
from tio.battle_state import BattleActor,BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.battle_attack import AttackRequest,decode_attack_result
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
from tio.protocol.abilities import AbilityEntry,decode_abilities
from tio.protocol.item_action import ItemAction
from tio.arena_service import ArenaService
from test_combat import item,FixedRandom


class WeaponEffectsTests(unittest.TestCase):
    def setup_effect(self,weapon,ammo=None,count=100):
        field=BattleField(24,24,[BattleActor(1,7,1,1,40,100,100),
            BattleActor(2,8,6,1,40,500,500),BattleActor(3,7,6,2,40,500,500)],step_cost=1)
        combat=Combat(field,WeaponCatalog(),rng=FixedRandom());field.combat=combat
        items=[item(100,weapon,equipped=True)]
        if ammo:items.append(item(101,ammo,count))
        combat.register(1,encode_item_list(1,items),human=True)
        return field,combat

    def test_heavy_burst_uses_whole_burst_and_native_distance_interval(self):
        for weapon,bullets,ap in ((314,20,9),(315,30,10)):
            field,combat=self.setup_effect(weapon,14,bullets)
            result=decode_attack_result(combat.attack(7,AttackRequest(1,6,1))[0])
            self.assertEqual(result.hits[0].damage,combat.catalog.distance_damage(weapon,5)[0])
            self.assertEqual(field.actor(1).action_points,40-ap)
            self.assertEqual(field.actor(3).health,500)
            items=decode_item_list(combat.inventories[1])[1]
            self.assertEqual([i.template_id for i in items],[weapon])
            self.assertEqual(items[0].unknown_words[0],300-ap)

    def test_heavy_miss_still_spends_burst_without_damage(self):
        field,combat=self.setup_effect(314,14,20)
        combat.rng=SimpleNamespace(randrange=lambda n:99,randint=lambda a,b:a)
        result=decode_attack_result(combat.attack(7,AttackRequest(1,6,1))[0])
        self.assertEqual((result.flags,result.hits[0].damage),(2,0))
        self.assertEqual(field.actor(2).health,500)
        self.assertEqual([i.template_id for i in decode_item_list(combat.inventories[1])[1]],[314])

    def test_rocket_blast_includes_allies_consumes_missile_not_launcher(self):
        field,combat=self.setup_effect(316,8,1)
        result=decode_attack_result(combat.attack(7,AttackRequest(1,6,1))[0])
        self.assertEqual({h.actor_id for h in result.hits},{2,3})
        self.assertTrue(all(h.damage==135 for h in result.hits))
        self.assertEqual((field.actor(1).health,field.actor(1).action_points),(100,28))
        items=decode_item_list(combat.inventories[1])[1]
        self.assertEqual([i.template_id for i in items],[316])
        self.assertEqual(items[0].unknown_words[0],288)

    def test_rocket_wall_and_missing_ammo_are_atomic(self):
        for wall,ammo in ((True,8),(False,None)):
            field,combat=self.setup_effect(316,ammo,1)
            if wall:field.blocked=frozenset(((3,1),))
            before=(dict(field._actors),dict(combat.inventories))
            with self.assertRaises(ValueError):combat.attack(7,AttackRequest(1,6,1))
            self.assertEqual((field._actors,combat.inventories),before)

    def test_subgrenade_is_weapon_ability_and_spends_only_its_round(self):
        field,combat=self.setup_effect(339,340,2)
        combat.learned[1]=(AbilityEntry(1,1,0,0),)
        self.assertEqual([e.ability_id for e in decode_abilities(combat.skill_packets(1)[0])[1]],[1,27])
        arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=field;arena._turns={1:(7,{1},20)}
        result=decode_attack_result(arena.cast_ability(7,encode_ability_cast(AbilityCast(27,1,0,6,1)))[0])
        self.assertEqual((result.weapon_id,result.skill_id),(340,27))
        self.assertEqual({h.actor_id for h in result.hits},{2,3})
        items=decode_item_list(combat.inventories[1])[1]
        self.assertEqual([(i.template_id,i.count) for i in items],[(339,1),(340,1)])
        self.assertEqual((items[0].unknown_words[0],field.actor(1).action_points),(294,34))
        combat.inventories[1]=encode_item_list(1,[replace(i,unknown_u8_01=0,location_raw=0) for i in items])
        self.assertEqual([e.ability_id for e in decode_abilities(combat.skill_packets(1)[0])[1]],[1])
        self.assertEqual(combat.learned[1],(AbilityEntry(1,1,0,0),))

    def test_subgrenade_rejects_wrong_weapon_range_owner_and_empty_ammo(self):
        for weapon,ammo,owner,x in ((301,340,7,6),(339,None,7,6),(339,340,8,6),(339,340,7,3)):
            field,combat=self.setup_effect(weapon,ammo)
            before=(dict(field._actors),dict(combat.inventories))
            with self.assertRaises(ValueError):combat.cast_subgrenade(owner,AbilityCast(27,1,0,x,1))
            self.assertEqual((field._actors,combat.inventories),before)

    def test_new_medical_items_and_dog_species_gate(self):
        for template,human,power,ap in ((20,True,100,10),(32,False,15,1)):
            field,combat=self.setup_effect(301)
            combat.register(1,encode_item_list(1,(item(200,template,2),)),human=human)
            field._actors[1]=replace(field.actor(1),health=1)
            combat.use_medical(7,ItemAction(1,200,255))
            self.assertEqual((field.actor(1).health,field.actor(1).action_points),(min(100,1+power),40-ap))
            self.assertEqual(decode_item_list(combat.inventories[1])[1][0].count,1)
        combat.register(1,encode_item_list(1,(item(200,32),)),human=True)
        before=(dict(field._actors),dict(combat.inventories))
        with self.assertRaises(ValueError):combat.use_medical(7,ItemAction(1,200,255))
        self.assertEqual((field._actors,combat.inventories),before)

    def test_incomplete_original_effects_are_not_treated_as_bullets(self):
        for weapon in (323,334,340):
            field,combat=self.setup_effect(weapon)
            with self.assertRaises(ValueError):combat.attack(7,AttackRequest(1,6,1))
