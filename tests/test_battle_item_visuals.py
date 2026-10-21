"""Recipient-private F7/v1 presentation, server TTL and deterministic bounds."""
from copy import copy
from dataclasses import replace
import unittest
from unittest.mock import patch

from test_battle_item_effects import BattleItemFixture
from tio import battle_item_effects as effects, battle_item_visuals as visuals, battle_snapshot
from tio.protocol.battle_item_visuals import encode_item_visuals, decode_item_visuals, MAX_CELLS
from tio.protocol.battle_attack import AttackRequest
from tio.protocol.binary import PacketError


class ItemVisualTests(BattleItemFixture):
    def test_recon_survives_overlapping_effect_without_replacing_its_sprite(self):
        self.throw(318,(5,3))
        state=effects.initialize(self.combat)
        state['recon'][1]=dict(source=1,center=(5,3),radius=1,shape='square',expiry=0)
        cells=visuals.visible_cells(self.field,7)
        self.assertEqual({(x,y) for x,y,k in cells if k==3},
                         {(x,y) for x in range(4,7) for y in range(2,5)})
        self.assertIn((5,3,1),cells)
        self.assertEqual(decode_item_visuals(encode_item_visuals(cells)),cells)

    def test_snapshot_codec_strict_version_lengths_coordinates_kinds_and_duplicates(self):
        cells=((2,3,1),(4,5,2),(6,7,3),(8,9,4),(10,11,5))
        self.assertEqual(decode_item_visuals(encode_item_visuals(cells)),cells)
        self.assertEqual(encode_item_visuals(()),b'\xf7\1\0\0')
        for invalid in (((255,0,1),),((True,2,1),),((1,2,6),),((1,2,1),(1,2,2)),tuple((0,0,1) for _ in range(MAX_CELLS+1))):
            with self.subTest(invalid=invalid[:2]),self.assertRaises(PacketError):encode_item_visuals(invalid)
        for packet in (b'\xf7\2\0\0',encode_item_visuals(cells)[:-1],encode_item_visuals(cells)+b'\0',b'\xf7\1\1\x10'):
            with self.assertRaises(PacketError):decode_item_visuals(packet)

    def test_smoke_cloud_surface_can_be_visible_while_combat_sight_is_blocked(self):
        self.throw(318,(5,3))
        self.assertFalse(effects.can_observe(self.combat,self.field.actor(1),self.field.actor(2)))
        for owner in (7,8,9):self.assertIn((5,3,1),visuals.visible_cells(self.field,owner))
        self.assertTrue(all(len(row)==3 for row in visuals.visible_cells(self.field,7)))

    def test_visual_snapshot_obeys_static_cover_and_each_recipient_coordinates(self):
        self.prepare(318,blocker={(4,y) for y in range(20)})
        self.field._actors[3]=replace(self.field.actor(3),health=0)
        with patch.object(effects,'_scatter',return_value=(5,3)):effects.attack(self.combat,7,AttackRequest(1,5,3))
        alice=visuals.visible_cells(self.field,7);bob=visuals.visible_cells(self.field,8)
        self.assertTrue(alice);self.assertTrue(all(x<4 for x,y,kind in alice))
        self.assertIn((5,3,1),bob);self.assertNotIn((5,3,1),alice)
        replay=copy(self.field);replay._actors=dict(self.field._actors)
        replay._actors[1]=replace(replay.actor(1),x=12,y=3)
        self.assertIn((5,3,1),visuals.visible_cells(replay,7))

    def test_remote_recon_cells_go_only_to_allied_owners_and_expire_on_source_turn(self):
        self.prepare(24);effects.initialize(self.combat)
        self.combat.item_effects['recon'][1]=dict(source=1,center=(26,12),radius=5,expiry=0)
        for owner in (7,9):self.assertIn((26,12,3),visuals.visible_cells(self.field,owner))
        self.assertFalse(visuals.visible_cells(self.field,8))
        effects.end_turn(self.combat,7,(1,))
        self.assertEqual(visuals.packets(self.field,7),(b'\xf7\1\0\0',b'\xf9\1\0\0',bytes.fromhex('fb0100000000000000')))

    def test_dark_flare_cells_stay_in_normal_radius_and_overlapping_smoke_masks_light(self):
        self.prepare(5001);self.field.item_darkness=True;effects.initialize(self.combat);effects.refresh_sight(self.combat)
        self.field._actors[3]=replace(self.field.actor(3),health=0)
        self.combat.item_effects['areas'][1]=dict(kind='flare',center=(10,3),radius=3,source=1,owner=7,expiry=3)
        cells=visuals.visible_cells(self.field,7)
        self.assertIn((10,3,2),cells);self.assertFalse(any(x>11 for x,y,kind in cells))
        self.combat.item_effects['areas'][2]=dict(kind='smoke',center=(10,3),radius=3,source=2,owner=8,expiry=3)
        self.assertIn((8,3,1),visuals.visible_cells(self.field,7))
        self.assertNotIn((8,3,2),visuals.visible_cells(self.field,7))

    def test_snapshot_reconnect_and_server_ttl_replace_clouds_with_empty_packet(self):
        self.throw(318,(5,3));packet=visuals.packets(self.field,7)
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.assertEqual(visuals.packets(restored,7),packet)
        for turn in range(3):
            restored.prepare_turn(7,(1,));effects.end_turn(restored.combat,7,(1,))
        self.assertEqual(visuals.packets(restored,7),(b'\xf7\1\0\0',b'\xf9\1\0\0',bytes.fromhex('fb0100000000000000')))

    def test_native_fixed_buffer_bound_is_deterministic_without_changing_authoritative_areas(self):
        self.prepare(318);self.field.width=self.field.height=255
        self.field._actors[1]=replace(self.field.actor(1),x=127,y=127,sight_radius=255)
        state=effects.initialize(self.combat)
        for identity,(x,y) in enumerate(( (x,y) for y in range(60,195,6) for x in range(60,195,6) )):
            state['areas'][identity]=dict(kind='smoke',center=(x,y),radius=3,source=1,owner=7,expiry=3)
        areas=dict(state['areas']);cells=visuals.visible_cells(self.field,7)
        self.assertEqual(len(cells),MAX_CELLS);self.assertEqual(visuals.visible_cells(self.field,7),cells)
        self.assertEqual(state['areas'],areas);self.assertEqual(len(decode_item_visuals(visuals.packets(self.field,7)[0])),MAX_CELLS)


if __name__=='__main__':unittest.main()
