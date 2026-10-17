"""Common authoritative field, account-local CAS, TTL and native packet effects."""
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tio import battle_item_effects as effects, battle_snapshot, item_boosters
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog, WeaponStats
from tio.protocol.battle_attack import AttackRequest, decode_attack_result
from tio.protocol.battle_item_status import encode_sight, decode_sight
from tio.protocol.item_action import ItemAction
from tio.protocol.item_list import encode_item_list, decode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from test_combat import item

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    result = WeaponCatalog()
    entries = json.loads((ROOT/'config/battle_item_catalog_extension.json').read_text(encoding='utf-8'))['weapon_catalog_entries']
    for identity, row in entries.items():
        result.weapons[int(identity)] = WeaponStats(template_id=int(identity), **{k:v for k,v in row.items() if k!='source_fields'})
        result.sources[int(identity)] = row['source_fields']
    return result


class BattleItemFixture(unittest.TestCase):
    def prepare(self, template=320, *, position=(8,3), blocker=()):
        self.field = BattleField(32,20,[BattleActor(1,7,2,3,40,200,200,9),
            BattleActor(2,8,*position,40,150,150,9),BattleActor(3,9,30,3,40,180,180,9)],
            step_cost=1, teams={7:0,8:1,9:0}, blocked=blocker)
        self.combat = Combat(self.field, catalog(), rng=random.Random(17)); self.field.combat=self.combat
        record = item(100,template,equipped=template in (318,320,5001))
        if template == 334: record=replace(record,unknown_u8_01=1,location_raw=4)
        self.combat.register(1,encode_item_list(1,(record,)),human=True)
        self.combat.register(2,encode_item_list(2,()),human=True)
        self.combat.register(3,encode_item_list(3,()),human=True)
        self.combat.rank_profiles[1]=(16,0)
        return self.field,self.combat

    def throw(self, template=320, target=(8,3)):
        self.prepare(template)
        with patch.object(effects,'_scatter',return_value=target):
            return effects.attack(self.combat,7,AttackRequest(1,*target))


class BattleItemTests(BattleItemFixture):
    def test_native_effect_attacks_train_throwing_once_and_wagers_keep_progression(self):
        from test_weapon_proficiency import profile
        for template in (318, 320, 5001, 334):
            for wager in (False, True):
                with self.subTest(template=template, wager=wager):
                    self.prepare(template, position=(5, 3))
                    self.combat.register(1, self.combat.inventories[1], human=True, pet_packet=profile(26))
                    self.combat.wager = wager
                    before = self.combat.proficiencies[1]
                    with patch.object(effects, '_scatter', return_value=(5, 3)):
                        packets = effects.attack(self.combat, 7, AttackRequest(1, 5, 3))
                    self.assertFalse(decode_item_list(self.combat.inventories[1])[1])
                    self.assertEqual(self.field.actor(1).action_points,
                        0 if template == 334 else 40-effects.rules()['items'][str(template)]['ap'])
                    if wager:
                        self.assertEqual(self.combat.proficiencies[1], before)
                    else:
                        expected = self.combat.proficiency_rules.train(before, True, 'Throwing',
                            effects.rules()['items'][str(template)]['ap'], hit=True)
                        self.assertEqual(self.combat.proficiencies[1], expected)
                    if template == 334:
                        self.assertEqual(self.field.actor(1).health, 0)
                        self.assertLess(self.field.actor(2).health, 150)
                    else:
                        self.assertEqual(self.field.actor(2).health, 150)
                    self.assertTrue(packets)

    def test_second_suicide_write_rolls_back_trained_profile_and_rng(self):
        from test_weapon_proficiency import profile
        self.prepare(334, position=(5, 3))
        self.combat.register(1, self.combat.inventories[1], human=True, pet_packet=profile(26))
        before=(dict(self.combat.proficiencies), dict(self.combat.inventories), dict(self.field._actors), self.combat.rng.getstate())
        calls=[]
        def fail_second(changes, **kwargs):
            calls.append((changes, kwargs))
            if len(calls)==2: raise sqlite3.OperationalError('second item write')
        with patch.object(self.combat, '_persist_batch', side_effect=fail_second):
            with self.assertRaises(sqlite3.OperationalError): effects.attack(self.combat, 7, AttackRequest(1, 5, 3))
        self.assertEqual((self.combat.proficiencies, self.combat.inventories, self.field._actors, self.combat.rng.getstate()), before)
        self.assertIn(1, calls[0][1]['trained'])

    def test_native_sight_packets_match_original_probe_and_strict_byte_limits(self):
        proof=json.loads((ROOT/'evidence/battle_item_native.json').read_text(encoding='utf-8'))
        for row in proof['sight_updates']:
            packet=bytes.fromhex(row['packet_hex'])
            self.assertEqual(encode_sight(row['actor'],row['sight']),packet)
            self.assertEqual(decode_sight(packet),(row['actor'],row['sight']))
        for value in (-1,256,True):
            with self.assertRaises(ValueError): encode_sight(1,value)
        for packet in (encode_sight(1,4)[:-1],encode_sight(1,4)+b'\0'):
            with self.assertRaises(ValueError): decode_sight(packet)

    def test_catalog_extension_ids_checked_against_installed_and_server_catalogs(self):
        import xml.etree.ElementTree as ET
        report=json.loads((ROOT/'config/battle_item_catalog_extension.json').read_text(encoding='utf-8'))
        existing={int(n.get('id')) for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()}
        self.assertTrue(report['unused_in_both_catalogs'])
        # After integration the diagnostic catalog contains the reviewed IDs.
        # The collision statement refers to the pinned pre-extension source.
        if set(report['new_ids'])<=existing:
            original=set(report['source_diagnostic_ids'])
            self.assertFalse(original & set(report['new_ids']))
            self.assertTrue(set(report['new_ids'])<=existing)
        else:self.assertFalse(existing & set(report['new_ids']))
        expected=set(range(5001,5012))
        # The later hosted health-capacity release adds its reviewed item5012.
        if (ROOT/'tio/combat_completion.py').exists():expected.add(5012)
        self.assertEqual(set(report['new_ids']),expected)
        nodes=ET.parse(ROOT/'config/battle_item_catalog_extension.xml').getroot()
        self.assertEqual(len(nodes),len(expected))
        for node in nodes:
            values={v.get('key'):v.get('val') for v in node.findall('value')}
            self.assertEqual(values.get('itype','weapon'),'weapon' if node.get('id')=='5001' else 'medkit')
        installed=Path(r'C:\Program Files (x86)\TIOnline')
        if installed.is_dir():self.assertTrue(all((installed/p).is_file() for p in report['assets']))
        else:self.assertTrue(all(p.startswith('base/items/') for p in report['assets']))

    def test_flash_zero_damage_hits_both_sides_and_obeys_cover(self):
        self.prepare(320,blocker={(8,4)})
        self.field._actors[1]=replace(self.field.actor(1),x=7,y=3)
        self.field._actors[3]=replace(self.field.actor(3),x=8,y=5)
        before={i:a.health for i,a in self.field._actors.items()}
        with patch.object(effects,'_scatter',return_value=(8,3)):
            packets=effects.attack(self.combat,7,AttackRequest(1,8,3))
        result=decode_attack_result(packets[0])
        self.assertEqual({h.actor_id for h in result.hits},{1,2}); self.assertTrue(all(h.damage==0 for h in result.hits))
        self.assertEqual({i:a.health for i,a in self.field._actors.items()},before)
        self.assertEqual((self.field.actor(1).sight_radius,self.field.actor(2).sight_radius,self.field.actor(3).sight_radius),(4,4,9))
        self.assertEqual(self.field.actor(1).action_points,34); self.assertFalse(decode_item_list(self.combat.inventories[1])[1])
        self.assertFalse(self.combat.statistics); self.assertFalse(self.combat.rank_kills)

    def test_flash_lasts_one_affected_full_turn_without_tick_replay(self):
        self.throw(); effects.end_turn(self.combat,7,(1,))
        self.assertEqual(self.field.actor(2).sight_radius,4)
        self.field.prepare_turn(8,(2,)); effects.begin_turn(self.combat,8,(2,))
        self.assertEqual(self.field.actor(2).sight_radius,4)
        packets=effects.end_turn(self.combat,8,(2,)); self.assertIn(encode_sight(2,9),packets)
        self.assertEqual(effects.end_turn(self.combat,8,(2,)),())

    def test_kill_and_equipment_sight_deltas_survive_flash_and_injection_expiry(self):
        self.throw(); self.field._actors[2]=replace(self.field.actor(2),sight_radius=6)
        self.assertEqual(effects.refresh_sight(self.combat),(encode_sight(2,4),))
        self.assertEqual(self.combat.item_effects['base_sight'][2],11)
        self.field.prepare_turn(8,(2,)); effects.end_turn(self.combat,8,(2,))
        self.assertEqual(self.field.actor(2).sight_radius,11)
        self.combat.item_effects['vision'][2]=10; effects.refresh_sight(self.combat)
        self.assertEqual(self.field.actor(2).sight_radius,12)
        self.field._actors[2]=replace(self.field.actor(2),sight_radius=13); effects.refresh_sight(self.combat)
        self.combat.item_effects['vision'].pop(2); effects.refresh_sight(self.combat)
        self.assertEqual(self.field.actor(2).sight_radius,12)

    def test_smoke_blocks_sight_and_direct_fire_for_all_coalitions_then_expires(self):
        packets=self.throw(318,target=(5,3)); result=decode_attack_result(packets[0])
        self.assertFalse(result.hits); self.assertEqual(self.field.actor(2).health,150)
        self.assertFalse(effects.clear_item_sight(self.combat,(2,3),(8,3)))
        self.assertFalse(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))
        self.assertFalse(effects.can_observe(self.combat,self.field.actor(2),self.field.actor(1)))
        self.assertEqual(effects.visible_actors(self.combat,7),frozenset((1,3)))
        effects.end_turn(self.combat,7,(1,))
        for _ in range(2):
            self.field.prepare_turn(7,(1,)); effects.begin_turn(self.combat,7,(1,)); effects.end_turn(self.combat,7,(1,))
        self.assertFalse(self.combat.item_effects['areas']); self.assertTrue(effects.clear_item_sight(self.combat,(2,3),(8,3)))

    def test_area_ttl_advances_with_surviving_fighter_when_caster_dies_and_end_is_replayed(self):
        self.throw(318,target=(5,3))
        self.field._actors[3]=replace(self.field.actor(3),owner_id=7)
        self.field._actors[1]=replace(self.field.actor(1),health=0,action_points=0)
        effects.end_turn(self.combat,7,(1,3)); effects.end_turn(self.combat,7,(1,3))
        self.assertEqual(self.combat.item_effects['owner_turns'][7],1)
        for _ in range(2):
            self.field.prepare_turn(7,(3,)); effects.end_turn(self.combat,7,(3,))
        self.assertFalse(self.combat.item_effects['areas'])

    def test_areas_cleanup_when_casting_owner_is_eliminated(self):
        self.throw(318,target=(5,3)); self.field._actors[1]=replace(self.field.actor(1),health=0,action_points=0)
        effects.end_turn(self.combat,8,(2,)); self.assertFalse(self.combat.item_effects['areas'])

    def test_flare_in_darkness_reveals_only_inside_normal_sight_for_every_side(self):
        self.prepare(5001,position=(10,3)); self.field.item_darkness=True; effects.refresh_sight(self.combat)
        self.assertEqual(self.field.actor(1).sight_radius,6)
        self.assertFalse(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))
        with patch.object(effects,'_scatter',return_value=(10,3)):
            result=decode_attack_result(effects.attack(self.combat,7,AttackRequest(1,10,3))[0])
        self.assertEqual(result.weapon_id,5001); self.assertFalse(result.hits)
        self.assertTrue(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))
        self.field._actors[2]=replace(self.field.actor(2),x=12)
        self.assertFalse(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))
        for _ in range(3):
            effects.end_turn(self.combat,7,(1,)); self.field.prepare_turn(7,(1,))
        self.assertFalse(self.combat.item_effects['areas'])

    def test_grenade_actual_impact_uses_server_rng_and_map_validation(self):
        self.prepare(320); before=self.combat.rng.getstate()
        # Force only the first accuracy roll; the scatter cell still comes from
        # the actual server RNG rather than coordinates provided by a client.
        with patch.object(self.combat.rng,'randrange',side_effect=[99,0]):
            result=decode_attack_result(effects.attack(self.combat,7,AttackRequest(1,8,3))[0])
        self.assertEqual(result.target,(8,3)); self.assertNotEqual(result.impact,result.target)
        self.assertLessEqual((result.impact[0]-8)**2+(result.impact[1]-3)**2,4)
        self.assertTrue(self.field.inside(*result.impact)); self.assertNotIn(result.impact,self.field.blocked)

    def test_invalid_ownership_actor_or_landing_never_consumes_items(self):
        for owner,request in ((8,AttackRequest(1,8,3)),(7,AttackRequest(1,32,3)),(7,AttackRequest(1,30,3))):
            self.prepare(320); before=(dict(self.field._actors),dict(self.combat.inventories),self.combat.rng.getstate())
            with self.assertRaises(ValueError): effects.attack(self.combat,owner,request)
            self.assertEqual((self.field._actors,self.combat.inventories,self.combat.rng.getstate()),before)
        self.prepare(320,position=(9,3),blocker={(8,3)})
        with self.assertRaises(ValueError): effects.attack(self.combat,7,AttackRequest(1,8,3))

    def test_persistence_failure_rolls_back_scatter_ap_and_all_effects(self):
        self.prepare(320); effects.initialize(self.combat)
        before=(dict(self.field._actors),dict(self.combat.inventories),self.combat.rng.getstate(),dict(self.combat.item_effects['flash']))
        with patch.object(self.combat,'_persist_batch',side_effect=sqlite3.OperationalError('injected')):
            with self.assertRaises(sqlite3.OperationalError): effects.attack(self.combat,7,AttackRequest(1,8,3))
        self.assertEqual((self.field._actors,self.combat.inventories,self.combat.rng.getstate(),self.combat.item_effects['flash']),before)

    def test_champagne_heals24_for2ap_and_instance_replay_is_rejected(self):
        self.prepare(33); self.field._actors[1]=replace(self.field.actor(1),health=190)
        packets=effects.use(self.combat,7,ItemAction(1,100,255))
        self.assertEqual((self.field.actor(1).health,self.field.actor(1).action_points),(200,38))
        self.assertFalse(decode_item_list(self.combat.inventories[1])[1]); self.assertEqual(packets[0][0],0x4e)
        with self.assertRaises(ValueError): effects.use(self.combat,7,ItemAction(1,100,255))

    def test_champagne_full_health_and_explicit_equip_option_reject_without_cost(self):
        self.prepare(33); before=(dict(self.field._actors),dict(self.combat.inventories))
        for option in (255,4):
            with self.assertRaises(ValueError): effects.use(self.combat,7,ItemAction(1,100,option))
        self.assertEqual((self.field._actors,self.combat.inventories),before)

    def test_vision_injection_duration_cooldown_and_snapshot_dont_reset(self):
        self.prepare(35); effects.use(self.combat,7,ItemAction(1,100,255))
        self.assertEqual((self.field.actor(1).sight_radius,self.field.actor(1).action_points),(10,30))
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.field=restored; self.combat=restored.combat
        self.assertEqual(effects.refresh_sight(self.combat),())
        self.combat.register(1,encode_item_list(1,(item(101,35),)),human=True)
        with self.assertRaisesRegex(ValueError,'cooling'): effects.use(self.combat,7,ItemAction(1,101,255))
        for _ in range(9): self.field.prepare_turn(7,(1,)); effects.end_turn(self.combat,7,(1,))
        self.assertEqual(self.field.actor(1).sight_radius,9)
        for _ in range(6): self.field.prepare_turn(7,(1,)); effects.end_turn(self.combat,7,(1,))
        effects.use(self.combat,7,ItemAction(1,101,255)); self.assertEqual(self.field.actor(1).sight_radius,10)

    def test_night_vision_charges_each_generation_once_and_stops_on_empty_ap(self):
        self.prepare(5002); self.field.item_darkness=True; effects.refresh_sight(self.combat)
        effects.use(self.combat,7,ItemAction(1,100,255))
        self.assertEqual((self.field.actor(1).sight_radius,self.field.actor(1).action_points,effects.armor_bonus(self.combat,1)),(8,37,20))
        self.field.prepare_turn(7,(1,)); effects.begin_turn(self.combat,7,(1,))
        self.assertEqual(self.field.actor(1).action_points,37); self.assertEqual(effects.begin_turn(self.combat,7,(1,)),())
        self.assertEqual(decode_item_list(self.combat.inventories[1])[1][0].unknown_words[0],294)
        self.field.prepare_turn(7,(1,)); self.field._actors[1]=replace(self.field.actor(1),action_points=2)
        effects.begin_turn(self.combat,7,(1,))
        self.assertEqual((self.field.actor(1).sight_radius,self.field.actor(1).action_points,effects.armor_bonus(self.combat,1)),(6,2,0))

    def test_night_vision_low_level_broken_device_and_daylight_do_not_charge(self):
        for low_level,broken,dark in ((True,False,True),(False,True,True),(False,False,False)):
            self.prepare(5002); self.field.item_darkness=dark
            if low_level:self.combat.rank_profiles[1]=(3,0)
            if broken:self.combat.register(1,encode_item_list(1,(replace(item(100,5002),unknown_words=(0,300,300)),)),human=True)
            before=(dict(self.field._actors),dict(self.combat.inventories))
            with self.assertRaises(ValueError): effects.use(self.combat,7,ItemAction(1,100,255))
            self.assertEqual((self.field._actors,self.combat.inventories),before)

    def test_night_vision_final_paid_use_works_then_disables_on_missing_device(self):
        self.prepare(5002); self.field.item_darkness=True; effects.refresh_sight(self.combat)
        self.combat.register(1,encode_item_list(1,(replace(item(100,5002),unknown_words=(3,300,300)),)),human=True)
        self.combat.rank_profiles[1]=(16,0)
        effects.use(self.combat,7,ItemAction(1,100,255))
        self.assertFalse(decode_item_list(self.combat.inventories[1])[1]); self.assertEqual(self.field.actor(1).sight_radius,8)
        self.field.prepare_turn(7,(1,)); effects.begin_turn(self.combat,7,(1,)); self.assertEqual(self.field.actor(1).sight_radius,6)

    def test_binocular_coalition_remote_radius_and_one_turn_not_enemy_disclosure(self):
        self.prepare(24,position=(20,3)); action=ItemAction(1,100,255)
        self.assertFalse(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))
        self.assertEqual(effects.use(self.combat,7,action),()); effects.recon_target(self.combat,7,AttackRequest(1,20,3))
        self.assertEqual((self.field.actor(1).action_points,decode_item_list(self.combat.inventories[1])[1][0].unknown_words[0]),(35,295))
        self.assertTrue(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))
        self.assertTrue(effects.can_observe(self.combat,self.field.actor(3),self.field.actor(2)))
        self.assertFalse(effects.can_observe(self.combat,self.field.actor(2),self.field.actor(1)))
        with self.assertRaises(ValueError): effects.recon_target(self.combat,7,AttackRequest(1,20,3))
        effects.end_turn(self.combat,7,(1,)); self.assertFalse(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))

    def test_visibility_replay_uses_supplied_copy_coordinates_not_live_combat_field(self):
        from copy import copy
        self.prepare(24,position=(20,3))
        replay=copy(self.field); replay._actors=dict(self.field._actors)
        replay._actors[2]=replace(replay.actor(2),x=10)
        self.assertNotIn(2,effects.visible_actors(self.combat,7))
        self.assertIn(2,effects.visible_actors(self.combat,7,field=replay))
        self.assertEqual(self.field.actor(2).x,20)

    def test_saved_recon_smoke_and_flash_survive_reconnect_without_new_cost_or_ttl(self):
        self.throw(318,target=(5,3)); state=self.combat.item_effects
        state['flash'][2]=1; effects.refresh_sight(self.combat)
        state['recon'][1]=dict(source=1,center=(25,3),radius=5,expiry=0)
        before=(dict(self.combat.inventories),dict(state['areas']),dict(state['flash']),self.combat.rng.getstate())
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(self.field,clock=lambda:10,wall=lambda:100),clock=lambda:90,wall=lambda:180)
        c=restored.combat
        self.assertEqual((c.inventories,c.item_effects['areas'],c.item_effects['flash'],c.rng.getstate()),before)
        self.assertEqual(effects.refresh_sight(c),()); self.assertFalse(effects.clear_item_sight(c,(2,3),(8,3)))

    def test_native_projection_filters_hidden_flash_hits_and_keeps_inventory_owner_private(self):
        from server.battle_events import project_action
        from tio.visibility import VisibilityView
        from tio.protocol.battle_soldier import decode_battle_soldier
        from tools.battle_actor_fixture import actor_packet
        self.prepare(320); self.field._actors[1]=replace(self.field.actor(1),sight_radius=4)
        profile=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        pet=decode_pet_info(profile,human_equipment=True); templates={}
        for i,a in self.field._actors.items():
            local=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':i,'0x8c44a6':i}))
            templates[i]=decode_battle_soldier(actor_packet(local,a.owner_id,self.combat.inventories[i],actor_id=i,x=a.x,y=a.y),human_equipment=True)
        views={owner:VisibilityView(self.field,owner,templates) for owner in (7,8,9)}
        def visible(field,owner): return effects.visible_actors(field.combat,owner,field=field)
        with patch('tio.visibility.visible_actors',side_effect=visible),patch('server.battle_events.visible_actors',side_effect=visible):
            for view in views.values(): view.refresh()
            before=dict(self.field._actors); old={o:v.visible for o,v in views.items()}
            self.assertNotIn(2,old[7]); self.assertNotIn(2,old[9]); self.assertIn(2,old[8])
            with patch.object(effects,'_scatter',return_value=(8,3)):
                packets=effects.attack(self.combat,7,AttackRequest(1,8,3))
            projected={o:project_action(v,7,before,old[o],packets) for o,v in views.items()}
        for owner in (7,9):
            self.assertTrue(all(h.actor_id!=2 for p in projected[owner] if p[0]==0x4b for h in decode_attack_result(p).hits))
            self.assertFalse(any(p[0]==0x4e and int.from_bytes(p[1:5],'little')==2 for p in projected[owner]))
        self.assertTrue(any(p[0]==0x4e and int.from_bytes(p[1:5],'little')==2 and int.from_bytes(p[9:13],'little')==12 for p in projected[8]))
        self.assertEqual([p for p in projected[7] if p[0]==0x30],[self.combat.inventory_packet(1)])
        self.assertFalse(any(p[0]==0x30 and int.from_bytes(p[1:5],'little')==1 for p in projected[8]))
        self.assertFalse(any(p[0]==0x30 and int.from_bytes(p[1:5],'little')==1 for p in projected[9]))

    def test_suicide_is_centered_on_actor_self_always_dies_and_allies_take_damage(self):
        self.prepare(334,position=(5,3)); self.field._actors[3]=replace(self.field.actor(3),x=3,y=3)
        self.field._actors[2]=replace(self.field.actor(2),health=200,max_health=200)
        packets=effects.attack(self.combat,7,AttackRequest(1,5,3)); result=decode_attack_result(packets[0])
        self.assertEqual((result.target,result.impact,result.weapon_id),((5,3),(2,3),334))
        self.assertEqual({h.actor_id for h in result.hits},{1,2,3}); self.assertEqual(self.field.actor(1).health,0)
        self.assertLess(self.field.actor(3).health,180); self.assertGreater(self.field.actor(2).health,0)
        self.assertFalse(decode_item_list(self.combat.inventories[1])[1])
        self.assertEqual(self.combat.statistics[7]['losses'],1)
        self.assertIsNone(effects.attack(self.combat,7,AttackRequest(1,5,3)))
        with self.assertRaises(ValueError): self.combat.attack(7,AttackRequest(1,5,3))

    def test_suicide_atomic_second_write_failure_restores_hp_inventory_rng_and_stats(self):
        self.prepare(334,position=(5,3)); before=(dict(self.field._actors),dict(self.combat.inventories),self.combat.rng.getstate())
        with patch.object(self.combat,'_persist_batch',side_effect=[None,sqlite3.OperationalError('second write')]):
            with self.assertRaises(sqlite3.OperationalError): effects.attack(self.combat,7,AttackRequest(1,5,3))
        self.assertEqual((self.field._actors,self.combat.inventories,self.combat.rng.getstate()),before)
        self.assertFalse(self.combat.statistics); self.assertFalse(self.combat.rank_kills); self.assertFalse(self.combat.experience.totals)

    def test_suicide_blast_respects_cover_and_enemy_death_once(self):
        self.prepare(334,position=(3,3),blocker={(2,4)})
        self.field._actors[2]=replace(self.field.actor(2),health=1)
        self.field._actors[3]=replace(self.field.actor(3),x=2,y=5)
        result=decode_attack_result(effects.attack(self.combat,7,AttackRequest(1,3,3))[0])
        self.assertEqual({h.actor_id for h in result.hits},{1,2}); self.assertEqual(self.field.actor(3).health,180)
        self.assertEqual(self.combat.rank_kills,[(1,2)]); self.assertEqual(self.combat.sight_kill_victims,{2})
        self.assertEqual(self.combat.statistics[7]['kills'],1)


class BoosterAccountTests(BattleItemFixture):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'shared.db'; self.prepare(5003)
        packet=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        pet=decode_pet_info(packet,human_equipment=True)
        packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':1,'0x8c44a6':1,'0x8c4aef':16}))
        self.profile=packet
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,human INTEGER,pet_packet BLOB,inventory_packet BLOB,PRIMARY KEY(account,pet_id))')
            db.executemany('INSERT INTO owned_pets VALUES (?,?,?,?,?)',[
                ('alice',1,1,packet,self.combat.inventories[1]),('bob',1,1,packet,encode_item_list(1,()))])
        self.combat.persistence={1:(self.path,'alice'),2:(self.path,'bob')}; self.combat.storage_ids={1:1,2:1}

    def seed(self,template,count=1):
        inventory=encode_item_list(1,(item(100,template,count=count),))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(inventory,'alice'))
        self.combat.inventories[1]=inventory

    def test_booster_activation_is_persistent_account_local_native33_and_replay_safe(self):
        effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        self.assertEqual(item_boosters.active(self.path,'alice',1,101)['trainer']['value'],30)
        self.assertEqual(item_boosters.active(self.path,'bob',1,101),{})
        self.assertFalse(item_boosters.active(self.path,'alice',1,3700))
        with self.assertRaises(ValueError): effects.use(self.combat,7,ItemAction(1,100,255),now=101)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(decode_item_list(db.execute("SELECT inventory_packet FROM owned_pets WHERE account='alice'").fetchone()[0])[1])

    def test_identical_booster_rejects_without_consuming_but_family_replacement_applies(self):
        self.seed(5003,2); effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        before=self.combat.inventories[1]
        with self.assertRaisesRegex(ValueError,'already active'): effects.use(self.combat,7,ItemAction(1,100,255),now=101)
        self.assertEqual(self.combat.inventories[1],before)
        self.seed(5005); effects.use(self.combat,7,ItemAction(1,100,255),now=102)
        self.assertEqual(item_boosters.active(self.path,'alice',1,103)['trainer']['value'],100)

    def test_booster_inventory_cas_failure_rolls_back_timer_and_consumption(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice'",(encode_item_list(1,()),))
        before=self.combat.inventories[1]
        with self.assertRaisesRegex(ValueError,'outside battle'): effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        self.assertEqual(self.combat.inventories[1],before); self.assertEqual(item_boosters.active(self.path,'alice',1,101),{})

    def test_shared_two_account_item_transaction_rolls_back_sql_after_second_suicide_write(self):
        jacket=replace(item(100,334),unknown_u8_01=1,location_raw=4)
        self.combat.inventories[1]=encode_item_list(1,(jacket,))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice'",(self.combat.inventories[1],))
        before=dict(self.combat.inventories); persist=self.combat._persist_batch; calls=[]
        def fail_second(changes,**kwargs):
            calls.append(changes)
            if len(calls)==2:raise sqlite3.OperationalError('after first successful SQL inventory CAS')
            return persist(changes,**kwargs)
        with patch.object(self.combat,'_persist_batch',side_effect=fail_second):
            with self.assertRaises(sqlite3.OperationalError):effects.attack(self.combat,7,AttackRequest(1,5,3))
        self.assertEqual(self.combat.inventories,before); self.assertEqual(self.field.actor(1).health,200)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT inventory_packet FROM owned_pets WHERE account='alice'").fetchone()[0],before[1])
            self.assertEqual(db.execute("SELECT inventory_packet FROM owned_pets WHERE account='bob'").fetchone()[0],encode_item_list(1,()))

    def test_low_level_and_wager_boosters_reject_without_consumption(self):
        self.seed(5008); self.combat.rank_profiles[1]=(15,0)
        with self.assertRaisesRegex(ValueError,'level'): effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        self.combat.rank_profiles[1]=(16,0); self.combat.wager=True
        with self.assertRaisesRegex(ValueError,'wager'): effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        self.assertEqual(item_boosters.active(self.path,'alice',1,101),{})

    def test_training_and_blocking_bonus_freeze_each_damage_event_across_expiry(self):
        effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        self.combat.experience.totals={1:Fraction(10),2:Fraction(10)}
        effects.freeze_experience(self.combat,{},now=101)
        self.assertEqual(self.combat.experience.totals,{1:Fraction(13),2:Fraction(10)})
        before=dict(self.combat.experience.totals); self.combat.experience.totals[1]+=10
        effects.freeze_experience(self.combat,before,now=3700); self.assertEqual(self.combat.experience.totals[1],23)
        self.seed(5009); effects.use(self.combat,7,ItemAction(1,100,255),now=4000)
        before=dict(self.combat.experience.totals); self.combat.experience.totals[1]+=10
        effects.freeze_experience(self.combat,before,now=4001); self.assertEqual(self.combat.experience.totals[1],23)
        self.assertTrue(all(item_boosters.nontransferable(i) for i in range(5003,5012)))
        self.assertFalse(item_boosters.nontransferable(33))

    def test_rank_advisor_freezes_once_per_victim_before_expiry_and_reconnect(self):
        self.seed(5008); effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        effects.freeze_rank_kills(self.combat,[(1,2)],now=101)
        effects.freeze_rank_kills(self.combat,[(1,2)],now=5000)
        self.assertEqual(effects.rank_bonus(self.combat,1,2),20); self.assertEqual(effects.rank_bonus(self.combat,2,2),0)
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.assertEqual(effects.rank_bonus(restored.combat,1,2),20)

    def test_wager_even_active_boosters_cannot_add_xp_or_rank(self):
        self.seed(5008); effects.use(self.combat,7,ItemAction(1,100,255),now=100)
        self.combat.wager=True; self.combat.experience.totals={1:Fraction(10),2:Fraction(10)}
        effects.freeze_experience(self.combat,{},now=101); effects.freeze_rank_kills(self.combat,[(1,2)],now=101)
        self.assertEqual(self.combat.experience.totals,{1:Fraction(0),2:Fraction(0)})
        self.assertEqual(effects.rank_bonus(self.combat,1,2),0)

    def test_city_booster_use_cas_consumption_and_account_isolation(self):
        inventory=item_boosters.use_saved(self.path,'alice',ItemAction(1,100,255),now=100)
        self.assertFalse(decode_item_list(inventory)[1]); self.assertEqual(item_boosters.active(self.path,'alice',1,101)['trainer']['value'],30)
        for account in ('alice','bob'):
            with self.assertRaises(ValueError): item_boosters.use_saved(self.path,account,ItemAction(1,100,255),now=101)
        self.assertEqual(item_boosters.active(self.path,'bob',1,101),{})


if __name__=='__main__':unittest.main()
