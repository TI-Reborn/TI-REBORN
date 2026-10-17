"""Behavior checks against real AP, loot, combat and fog services."""
from dataclasses import replace
import json
from pathlib import Path
import random
from types import SimpleNamespace
import unittest

from tio.arena_service import ArenaService
from tio.battle_state import BattleActor, BattleField
from tio.battle_loot import BattleLoot
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.protocol.item_list import ItemRecord, encode_item_list, decode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.tactical_bot import (Actions, play_actor, fire_plan, hidden_cell, loot_selection,
                              fits, heal, weapon_for, enemies_for)
from tio.visibility import visible_actors
from tio.weight import inventory_weight, overload_penalty


def item(identity,template,count=1,equipped=False,slot=0):
    return ItemRecord(identity,template,b'\0\0',count,int(equipped),slot,(100,100,100),b'\0'*4,None,b'\0'*3)


class TacticalBotTests(unittest.TestCase):
    def scene(self,*,bot=(2,3),enemy=(8,3),blocked=(),sight=9,enemy_sight=5,ap=15,bag=()):
        field=BattleField(24,16,[BattleActor(1,7,*bot,ap,100,100,sight_radius=sight),
                                BattleActor(2,8,*enemy,15,1000,1000,sight_radius=enemy_sight)],
                         blocked=blocked,step_cost=1)
        field.battle_mode=0;field.combat=Combat(field,WeaponCatalog(),rng=random.Random(4))
        raw=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        profile=decode_pet_info(bytes.fromhex(raw['packet_hex']),human_equipment=True)
        profile=encode_pet_info(replace(profile,fields={**profile.fields,'0x8c4aef':1}))
        for identity in (1,2):
            field.combat.register(identity,encode_item_list(identity,bag if identity==1 else ()),human=True,pet_packet=profile)
            field.combat.weight_capacities[identity]=1000
        field.loot=BattleLoot(field.combat,(),level=1,rng=random.Random(1))
        room=SimpleNamespace(room_id=1,members=(7,8))
        arena=ArenaService(clock=lambda:0);arena.rooms=SimpleNamespace(snapshot=lambda:(room,))
        arena._fields[1]=field;arena._turns[1]=(7,frozenset((1,)),100)
        return field,arena,Actions(arena,7,None)

    def gun(self):
        return (item(10,301,equipped=True,slot=16),item(11,3,40))

    def test_shoots_and_leaves_enemy_fog_with_actual_weapon_cost(self):
        field,arena,_=self.scene(bot=(3,3),enemy=(7,3),enemy_sight=5,bag=self.gun())
        cost=weapon_for(field,1).attack_ap
        packets=play_actor(arena,1,7,1)
        attacks=[p for p in packets if p[0]==0x4b]
        self.assertEqual(len(attacks),1)
        self.assertNotIn(1,visible_actors(field,8))
        distance=abs(field.actor(1).x-3)+abs(field.actor(1).y-3)
        self.assertEqual(field.actor(1).action_points,15-cost-distance)
        self.assertEqual(next(i.count for i in decode_item_list(field.combat.inventories[1])[1] if i.template_id==3),39)

    def test_new_contact_after_five_steps_stops_walk_and_reserves_shot_and_escape(self):
        field,arena,_=self.scene(bot=(1,3),enemy=(13,3),sight=7,enemy_sight=7,bag=(item(10,303,equipped=True,slot=16),item(11,3,40)))
        field.patrol_waypoints=((20,3),)
        packets=play_actor(arena,1,7,1)
        self.assertTrue(any(p[0]==0x4b for p in packets))
        first_shot=next(n for n,p in enumerate(packets) if p[0]==0x4b)
        self.assertEqual(sum(p[0]==0x3d for p in packets[:first_shot]),5)
        self.assertNotIn(1,visible_actors(field,8))
        self.assertGreaterEqual(field.actor(1).action_points,0)

    def test_cover_is_checked_against_two_known_hostiles(self):
        field,_,_=self.scene(bot=(6,5),enemy=(10,5),enemy_sight=5,bag=self.gun())
        field._actors[3]=BattleActor(3,9,2,5,15,100,100,sight_radius=5)
        enemies=enemies_for(field,7,1)
        self.assertFalse(hidden_cell(field,1,(4,5),enemies))
        plan=fire_plan(field,1,enemies,visible_actors(field,7))
        self.assertIsNotNone(plan)
        if plan[2]:self.assertTrue(hidden_cell(field,1,plan[2][-1],enemies))

    def test_hidden_enemy_position_does_not_change_plan(self):
        field,_,_=self.scene(bot=(3,3),enemy=(7,3),bag=self.gun())
        known=visible_actors(field,7);enemies=enemies_for(field,7,1)
        before=fire_plan(field,1,enemies,known)
        field._actors[3]=BattleActor(3,9,23,15,15,100,100,sight_radius=100)
        self.assertEqual(fire_plan(field,1,enemies_for(field,7,1),visible_actors(field,7)),before)

    def test_medical_threshold_real_consumption_and_ap(self):
        for hp,expected in ((71,False),(70,True),(60,True)):
            field,_,actions=self.scene(bag=(item(20,34,2),))
            field._actors[1]=replace(field.actor(1),health=hp)
            self.assertEqual(heal(field,1,actions),expected)
            self.assertEqual(field.actor(1).health,hp+(13 if expected else 0))
            self.assertEqual(field.actor(1).action_points,15-int(expected))
            self.assertEqual(items_count(field,34),2-int(expected))

    def test_no_medicine_or_insufficient_ap_does_not_invent_healing(self):
        for bag in ((),(item(20,20),)):
            field,_,actions=self.scene(bag=bag,ap=1)
            field._actors[1]=replace(field.actor(1),health=60)
            self.assertFalse(heal(field,1,actions))
            self.assertEqual(field.actor(1).health,60)

    def test_loot_is_limited_to_usable_gear_matching_ammo_and_safe_weight(self):
        field,_,_=self.scene(enemy=(23,15))
        contents=(item(10,301),item(11,3,100000),item(12,34,100),item(13,302),item(14,2,10000))
        selected=dict(loot_selection(field,1,contents))
        bag=tuple(replace(i,unknown_u32_01=selected[i.instance_id]) for i in contents if i.instance_id in selected)
        self.assertIn(10,selected);self.assertNotIn(13,selected);self.assertNotIn(14,selected)
        self.assertLessEqual(selected.get(12,0),3)
        self.assertTrue(fits(field,1,bag))
        self.assertEqual(overload_penalty(inventory_weight(encode_item_list(1,bag)),field.combat.weight_capacity(1)),0)

    def test_opens_crate_transfers_equips_and_stops_after_at_most_two(self):
        field,arena,_=self.scene(enemy=(23,15))
        # Two crates offer a weapon/ammo; third must remain sealed.
        field.loot.boxes={(3,3):(item(101,301),item(102,3,30)),
                          (4,3):(item(103,34,3),), (5,3):(item(104,301),)}
        packets=play_actor(arena,1,7,1)
        self.assertTrue(any(p[0]==0x47 for p in packets))
        self.assertEqual(weapon_for(field,1).template_id,301)
        self.assertEqual(len(field.bot_crates[1]),2)
        self.assertNotIn((5,3),field.loot.opened)
        self.assertTrue(next(i for i in decode_item_list(field.combat.inventories[1])[1] if i.template_id==301).equipped)

    def test_no_ammo_does_not_attempt_unlimited_shots(self):
        field,arena,_=self.scene(enemy=(23,15),bag=(item(10,301,equipped=True,slot=16),))
        packets=play_actor(arena,1,7,1)
        self.assertFalse(any(p[0]==0x4b for p in packets))
        self.assertGreaterEqual(field.actor(1).action_points,0)

    def test_different_weapon_ap_prices_are_reserved(self):
        for template in (301,302,303):
            catalog=WeaponCatalog();w=catalog.weapons[template]
            bag=(item(10,template,equipped=True,slot=16),item(11,w.ammo_id,40))
            field,_,_=self.scene(bot=(3,3),enemy=(7,3),bag=bag,ap=w.attack_ap+2)
            plan=fire_plan(field,1,enemies_for(field,7,1),visible_actors(field,7))
            self.assertIsNotNone(plan)
            self.assertIsNotNone(plan[2])
            self.assertLessEqual(len(plan[0])+w.attack_ap+len(plan[2]),w.attack_ap+2)

    def test_ammunition_can_be_replenished_after_two_initial_crates(self):
        field,arena,_=self.scene(enemy=(23,15),bag=(item(10,301,equipped=True,slot=16),))
        field.bot_crates={1:{(15,2),(15,3)}}
        field.loot.boxes={(3,3):(item(102,3,1000),)}
        play_actor(arena,1,7,1)
        self.assertEqual(weapon_for(field,1).template_id,301)
        self.assertGreater(items_count(field,3),0)
        self.assertTrue(fits(field,1,decode_item_list(field.combat.inventories[1])[1]))

    def test_scavenging_progress_round_trips_through_durable_snapshot(self):
        from tio.battle_snapshot import dumps,loads
        field,arena,_=self.scene(enemy=(23,15))
        field.loot.boxes={(3,3):(item(101,301),item(102,3,30)),(4,3):(item(103,34),)}
        play_actor(arena,1,7,1)
        restored,_=loads(dumps(field))
        self.assertEqual(restored.bot_crates,field.bot_crates)
        self.assertEqual(restored.bot_supply_turns,field.bot_supply_turns)
        self.assertEqual(restored.combat.inventories,field.combat.inventories)


def items_count(field,template):
    return sum(i.count for i in decode_item_list(field.combat.inventories[1])[1] if i.template_id==template)
