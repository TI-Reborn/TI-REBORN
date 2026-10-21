import unittest
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from tio import battle_item_effects as effects, battle_snapshot, sniper_scope
from tio.arena_service import ArenaService
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.protocol.abilities import decode_abilities
from tio.protocol.ability_cast import AbilityCast, encode_ability_cast
from tio.protocol.battle_attack import AttackRequest
from tio.protocol.item_list import encode_item_list, decode_item_list
from tio.battle_item_visuals import visible_cells
from test_combat import item, FixedRandom


class ScopeTests(unittest.TestCase):
    def test_each_rifle_has_own_range_and_burst_after_scope(self):
        from tio.sniper_rifles import SVD
        for weapon,maximum,shot_ap,bullets in ((SVD,15,9,1),(313,16,10,3),(312,18,9,1)):
            with self.subTest(weapon=weapon):
                f,c=self.prepare(weapon)
                f._actors[2]=replace(f.actor(2),x=2+maximum,y=3)
                effects.initialize(c)
                self.assertNotIn(2,effects.visible_actors(c,7))
                with self.assertRaises(ValueError):sniper_scope.cast(c,7,AbilityCast(9,1,0,3+maximum,3))
                sniper_scope.cast(c,7,AbilityCast(9,1,0,2+maximum,3))
                self.assertIn(2,effects.visible_actors(c,7))
                c.attack(7,AttackRequest(1,2+maximum,3))
                self.assertEqual(f.actor(1).action_points,15-3-shot_ap)
                self.assertEqual(decode_item_list(c.inventories[1])[1][1].count,30-bullets)

    def test_svd_catalog_ui_assets_level_and_shop(self):
        from pathlib import Path
        import json,xml.etree.ElementTree as ET
        from tio.sniper_rifles import SVD
        from tio.enhancement_limits import required_level
        from tio.weapon_effects import battle_skills
        root=Path(__file__).resolve().parents[1]
        node=ET.parse(root/'evidence/items_diagnostic.xml').getroot().find(f"item[@id='{SVD}']")
        values={v.get('key'):v.get('val') for v in node.findall('value')}
        self.assertEqual((values['maxRange'],values['minRange'],values['actionPoints'],values['level_required']),('15','7','9','5'))
        self.assertEqual((values['image'],values['model_1']),('tio_wi_5013.png','weapon_svd'))
        self.assertEqual(required_level(item(1,SVD)),5)
        for template in (SVD,313):
            for slot in (16,128):
                inventory=encode_item_list(1,(replace(item(1,template,equipped=True),location_raw=slot),))
                self.assertEqual([e.ability_id for e in battle_skills((),inventory,True)],[9] if slot==16 else [])
        offers=json.loads((root/'config/city_catalogs.json').read_text(encoding='utf-8'))['item_categories']['0']
        self.assertEqual([r['unknown_u32_03'] for r in offers if r['item_id']==SVD],[1650])

    def test_svd_shop_purchase_produces_persistent_usable_item(self):
        from test_shop import ShopTests
        from tio.sniper_rifles import SVD
        from tio.protocol.shop_purchase import ShopPurchase
        fixture=ShopTests('test_buy_and_reopen');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        import sqlite3
        from contextlib import closing
        from tio.locations import LocationStore,center
        LocationStore(fixture.path)
        with closing(sqlite3.connect(fixture.path)) as db,db:LocationStore._save(db,'alice',2,*center(2))
        offer=next(r for r in fixture.store.catalogs.items[0] if r.item_id==SVD)
        result=fixture.store.purchase('alice',ShopPurchase(1,0,offer.unknown_u32_01,1))
        bought=next(r for r in decode_item_list(result.inventory)[1] if r.template_id==SVD)
        self.assertEqual((result.charged_credits,bought.count,bought.unknown_words),(1650,1,(300,300,300)))

    def prepare(self, weapon=312):
        f=BattleField(40,30,[BattleActor(1,7,2,3,15,100,100),
            BattleActor(2,8,19,3,15,500,500),BattleActor(3,9,35,20,15,100,100),
            BattleActor(4,8,20,4,15,500,500)],teams={7:0,8:1,9:0},step_cost=1)
        c=Combat(f,WeaponCatalog(),rng=FixedRandom());f.combat=c
        for a in f._actors.values():
            c.register(a.actor_id,encode_item_list(a.actor_id,
                (item(100,weapon,equipped=True),item(101,6,30)) if a.actor_id==1 else ()),human=True)
        return f,c

    def test_scope_reveals_nine_cells_shares_allies_and_enables_shot(self):
        f,c=self.prepare()
        self.assertNotIn(2,effects.visible_actors(c,7))
        replies=sniper_scope.cast(c,7,AbilityCast(9,1,0,20,3))
        from tio.protocol.ability_status import AbilityStatus,decode_ability_status
        states=[decode_ability_status(p) for p in replies if p[:2]==b'\x7f\x01']
        self.assertEqual(states,[(1,(AbilityStatus(9,1,0,0),))])
        self.assertEqual(f.actor(1).action_points,12)
        self.assertEqual(decode_item_list(c.inventories[1])[1][0].unknown_words[0],297)
        self.assertEqual(decode_item_list(c.inventories[1])[1][1].count,30)
        self.assertEqual({(x,y) for x,y,_ in visible_cells(f,7)},
                         {(x,y) for x in range(19,22) for y in range(2,5)})
        self.assertIn(2,effects.visible_actors(c,7))
        self.assertIn(2,effects.visible_actors(c,9))
        self.assertFalse(visible_cells(f,8))
        self.assertNotIn(1,effects.visible_actors(c,8))
        c.attack(7,AttackRequest(1,19,3))
        self.assertLess(f.actor(2).health,500)
        self.assertEqual(f.actor(1).action_points,3)
        effects.end_turn(c,7,(1,))
        self.assertNotIn(2,effects.visible_actors(c,7))
        self.assertFalse(visible_cells(f,7))

    def test_diagonal_visible_multiple_areas_checkpoint_and_source_death(self):
        f,c=self.prepare()
        sniper_scope.cast(c,7,AbilityCast(9,1,0,19,3))
        self.assertIn(4,effects.visible_actors(c,7))
        sniper_scope.cast(c,7,AbilityCast(9,1,0,18,6))
        self.assertEqual(len(c.item_effects['recon']),2)
        import random
        c.rng=random.Random(17)
        saved=battle_snapshot.dumps(f)
        restored=battle_snapshot.loads(saved)[0]
        self.assertEqual(effects.visible_actors(c,7),effects.visible_actors(restored.combat,7))
        f._actors[1]=replace(f.actor(1),health=0)
        self.assertNotIn(2,effects.visible_actors(c,9))

    def test_square_surface_includes_obstacles_and_each_diagonal_enemy(self):
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                with self.subTest(dx=dx,dy=dy):
                    f,c=self.prepare();f._actors[2]=replace(f.actor(2),x=19+dx,y=3+dy)
                    sniper_scope.cast(c,7,AbilityCast(9,1,0,19,3))
                    self.assertIn(2,effects.visible_actors(c,7))
        f,c=self.prepare();f.blocked=frozenset(((20,2),))
        sniper_scope.cast(c,7,AbilityCast(9,1,0,20,3))
        self.assertEqual({(x,y) for x,y,k in visible_cells(f,7) if k==3},
                         {(x,y) for x in range(19,22) for y in range(2,5)})

    def test_square_clips_only_map_edges_and_does_not_extend_binoculars(self):
        from tio.recon_geometry import cells,contains
        f,c=self.prepare()
        effect=dict(center=(0,0),radius=1,shape='square')
        self.assertEqual(set(cells(f,effect)),{(0,0),(0,1),(1,0),(1,1)})
        self.assertTrue(contains(effect,1,1))
        self.assertFalse(contains(effect,2,0))
        self.assertFalse(contains(dict(center=(0,0),radius=1),1,1))

    def test_square_does_not_reveal_enemy_through_wall_or_smoke(self):
        f,c=self.prepare();f.blocked=frozenset(((20,3),))
        sniper_scope.cast(c,7,AbilityCast(9,1,0,19,3))
        self.assertNotIn(4,effects.visible_actors(c,7))
        self.assertIn((20,4,3),visible_cells(f,7))
        f,c=self.prepare();sniper_scope.cast(c,7,AbilityCast(9,1,0,19,3))
        c.item_effects['areas'][1]=dict(kind='smoke',center=(20,4),radius=0,source=2,owner=8,expiry=3)
        self.assertNotIn(4,effects.visible_actors(c,7))

    def test_rejects_range_wall_smoke_wrong_slot_weapon_owner_and_ap_atomically(self):
        for case in ('near','far','wall','smoke','secondary','weapon','owner','ap','reserved','dead','broken'):
            with self.subTest(case=case):
                f,c=self.prepare(311 if case=='weapon' else 312);owner=8 if case=='owner' else 7
                x=8 if case=='near' else 21 if case=='far' else 20
                if case=='wall':f.blocked=frozenset(((10,3),))
                if case in ('ap','dead'):f._actors[1]=replace(f.actor(1),**({'action_points':2} if case=='ap' else {'health':0}))
                if case in ('secondary','broken'):
                    _,items,flag=decode_item_list(c.inventories[1])
                    changes={'location_raw':128} if case=='secondary' else {'unknown_words':(0,300,300)}
                    c.inventories[1]=encode_item_list(1,(replace(items[0],**changes),items[1]),flag)
                effects.initialize(c)
                if case=='smoke':c.item_effects['areas'][1]=dict(kind='smoke',center=(10,3),radius=1)
                before=deepcopy((f._actors,c.inventories,c.item_effects,c.premium_wear_remainders))
                with self.assertRaises(ValueError):sniper_scope.cast(c,owner,AbilityCast(9,1,int(case=='reserved'),x,3))
                self.assertEqual((f._actors,c.inventories,c.item_effects,c.premium_wear_remainders),before)

    def test_weapon_specific_max_and_skill_button_updates(self):
        f,c=self.prepare(313)
        self.assertEqual([e.ability_id for e in decode_abilities(c.skill_packets(1)[0])[1]],[9])
        with self.assertRaises(ValueError):sniper_scope.cast(c,7,AbilityCast(9,1,0,19,3))
        sniper_scope.cast(c,7,AbilityCast(9,1,0,18,3))
        c.swap_weapons(7,1)
        self.assertFalse(decode_abilities(c.skill_packets(1)[0])[1])

    def test_turn_authority_and_persistence_failure(self):
        f,c=self.prepare();arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=f;arena._turns={1:(8,{2},20)}
        packet=encode_ability_cast(AbilityCast(9,1,0,20,3))
        with self.assertRaises(ValueError):arena.cast_ability(7,packet)
        arena._turns={1:(7,{1},20)}
        effects.initialize(c);before=deepcopy((f._actors,c.inventories,c.item_effects))
        with patch.object(c,'_persist_batch',side_effect=RuntimeError('CAS failure')):
            with self.assertRaises(RuntimeError):arena.cast_ability(7,packet)
        self.assertEqual((f._actors,c.inventories,c.item_effects),before)
        arena.cast_ability(7,packet)
        self.assertIn(2,effects.visible_actors(c,7))


if __name__=='__main__':unittest.main()
