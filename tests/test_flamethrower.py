"""Approved cone, shared-account projection, finite protocol and persistence."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from tio.flamethrower import cells, visual_packet
from tio.protocol.flame_stream import encode_flame_stream, decode_flame_stream
from tio.protocol.battle_attack import AttackRequest, AttackResult, encode_attack_request, encode_attack_result, decode_attack_result
from tio.protocol.item_list import decode_item_list
from tio.battle_state import BattleActor, BattleField
from server.battle_events import project_action
from test_special_items import SpecialItemsTests
from test_battle_events import MinimalView


class FlameTests(unittest.TestCase):
    def prepare(self):
        case=SpecialItemsTests();case.prepare(324)
        return case.field,case.combat

    def test_cone_hits_enemy_and_ally_and_excludes_shooter(self):
        f,c=self.prepare();f._actors[3]=replace(f.actor(3),owner_id=7,x=7,y=3)
        result=decode_attack_result(c.attack(7,AttackRequest(1,3,2))[0])
        self.assertEqual({h.actor_id for h in result.hits},{2,3})
        self.assertEqual(f.actor(1).health,200)
        self.assertEqual({h.damage for h in result.hits},{40})
        self.assertEqual(c.statistics[7]['damage_dealt'],40)
        self.assertEqual(set(c.burns),{2,3})
        self.assertEqual(f.actor(1).action_points,31)
        self.assertEqual(decode_item_list(c.inventories[1])[1][0].unknown_words[0],291)

    def test_aim_distance_does_not_change_cone_width(self):
        f,c=self.prepare();a=f.actor(1)
        self.assertEqual(cells(f,a,(3,2)),cells(f,a,(7,2)))
        self.assertIn((7,3),cells(f,a,(3,2)))
        self.assertNotIn((6,3),cells(f,a,(3,2)))
        self.assertNotIn((8,2),cells(f,a,(3,2)))
        self.assertNotIn((1,2),cells(f,a,(3,2)))

    def test_walls_and_closed_doors_clip_damage_and_visuals(self):
        f,c=self.prepare();f.blocked=frozenset(( (5,1),(5,2),(5,3) ))
        f._actors[3]=replace(f.actor(3),x=4,y=2)
        r=decode_attack_result(c.attack(7,AttackRequest(1,7,2))[0])
        self.assertEqual([h.actor_id for h in r.hits],[3])
        self.assertEqual(f.actor(2).health,200)
        a=f.actor(1);self.assertNotIn((6,2),cells(f,a,(7,2)))
        f.blocked=frozenset();self.assertIn((6,2),cells(f,a,(7,2)))

    def test_empty_cone_consumes_one_burst_and_creates_no_terrain_fire(self):
        f,c=self.prepare();r=decode_attack_result(c.attack(7,AttackRequest(1,2,3))[0])
        self.assertFalse(r.hits);self.assertFalse(c.burns)
        self.assertEqual(f.actor(1).action_points,31)
        self.assertFalse(c.item_effects.get('fires',{}))

    def test_invalid_requests_and_persistence_failure_leave_no_partial_attack(self):
        for owner,x,y in ((8,3,2),(7,2,2),(7,8,2),(7,14,2)):
            f,c=self.prepare();before=dict(f._actors),dict(c.inventories)
            with self.assertRaises(ValueError):c.attack(owner,AttackRequest(1,x,y))
            self.assertEqual((f._actors,c.inventories),before);self.assertFalse(c.burns)
        f,c=self.prepare();before=dict(f._actors),dict(c.inventories)
        with patch.object(c,'_persist_batch',side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):c.attack(7,AttackRequest(1,3,2))
        self.assertEqual((f._actors,c.inventories),before);self.assertFalse(c.burns)

    def test_burn_refresh_does_not_stack_or_create_ground_fire(self):
        f,c=self.prepare()
        for _ in range(2):c.attack(7,AttackRequest(1,6,2))
        self.assertEqual(c.burns[2].remaining,2)
        self.assertEqual(len(c.burns),1)
        self.assertFalse(c.item_effects.get('fires',{}))

    def test_visual_projection_is_bounded_by_visibility_and_precedes_attack(self):
        f=BattleField(18,12,[BattleActor(1,7,2,5,40,200,200,2),BattleActor(2,8,6,5,40,200,200,8)],step_cost=1)
        before=dict(f._actors);view=MinimalView(f,7,{})
        view.visible=frozenset((1,));r=AttackResult(1,(2,5),(7,5),324)
        with patch.object(view,'refresh',return_value=()):
            result=project_action(view,7,before,view.visible,(encode_attack_result(r),))
        self.assertEqual(result[0][:2],b'\xf7\2');self.assertEqual(result[1][0],0x4b)
        actor,token,points=decode_flame_stream(result[0]);self.assertEqual(actor,1)
        self.assertTrue(all((x//32-2)**2+(y//32-5)**2<=4 for x,y,_,_ in points))
        with patch.object(view,'refresh',return_value=()):
            result=project_action(view,8,before,frozenset((2,)),(encode_attack_result(r),))
        self.assertFalse(any(p[:2]==b'\xf7\2' for p in result))

    def test_visual_footprints_do_not_cross_wall_or_disclose_hidden_cells(self):
        f,c=self.prepare();f.blocked=frozenset(((5,1),(5,2),(5,3)))
        view=MinimalView(f,7,{})
        packet=visual_packet(view,dict(f._actors),AttackResult(1,(2,2),(7,2),324))
        points=decode_flame_stream(packet)[2]
        self.assertTrue(all(x+size/2<=5*32 for x,y,size,_ in points))

    def test_event_codec_rejects_corruption(self):
        packet=encode_flame_stream(17,42,((120,160,12,4),))
        self.assertEqual(decode_flame_stream(packet),(17,42,((120,160,12,4),)))
        for bad in (packet[:-1],packet+b'\0',b'\xf7\1'+packet[2:],packet[:10]+b'\xff'+packet[11:]):
            with self.assertRaises(ValueError):decode_flame_stream(bad)
        for points in ((),((8160,1,4,1),),((32,32,33,1),),((32,32,4,0),)):
            with self.assertRaises(ValueError):encode_flame_stream(1,0,points)

    def test_visual_crosses_internal_cell_edges_and_starts_at_nozzle(self):
        f=BattleField(24,24,[BattleActor(1,7,10,10,40,200,200,12)],step_cost=1)
        view=MinimalView(f,7,{})
        p=decode_flame_stream(visual_packet(view,dict(f._actors),AttackResult(1,(10,10),(15,10),324)))[2]
        self.assertTrue(any(x//32==10 and y//32==10 for x,y,_,_ in p))
        # Full-sized envelopes straddle internal grid edges instead of shrinking
        # to zero and omitting the corresponding flame segment.
        self.assertTrue(any(size>=24 and min(x%32,32-x%32,y%32,32-y%32)<size/2 for x,y,size,_ in p))
        self.assertGreaterEqual(len(p),65)

    def test_motion_envelope_stays_inside_recipient_visibility(self):
        from math import ceil
        f=BattleField(24,24,[BattleActor(1,7,10,10,40,200,200,2)],step_cost=1)
        f.blocked=frozenset(((12,9),(12,10),(12,11)))
        view=MinimalView(f,7,{})
        p=decode_flame_stream(visual_packet(view,dict(f._actors),AttackResult(1,(10,10),(15,10),324)))[2]
        for x,y,size,_ in p:
            radius=ceil(size*.75)
            footprint={(u,v) for u in range((x-radius)//32,(x+radius)//32+1)
                       for v in range((y-radius)//32,(y+radius)//32+1)}
            self.assertFalse(footprint & f.blocked)
            self.assertTrue(all((u-10)**2+(v-10)**2<=4 for u,v in footprint))

    def test_visual_phase_varies_between_bursts_without_changing_damage_cells(self):
        f=BattleField(24,24,[BattleActor(1,7,10,10,40,200,200,12)],step_cost=1)
        before=dict(f._actors);view=MinimalView(f,7,{});attack=AttackResult(1,(10,10),(15,10),324)
        area=cells(f,f.actor(1),attack.target)
        first=decode_flame_stream(visual_packet(view,before,attack))[2]
        f._actors[1]=replace(f.actor(1),action_points=31)
        second=decode_flame_stream(visual_packet(view,before,attack))[2]
        self.assertNotEqual(first,second)
        self.assertEqual(cells(f,f.actor(1),attack.target),area)


class SharedFlameTests(unittest.TestCase):
    def test_two_accounts_receive_one_transient_event_without_reconnect_replay(self):
        from test_shared_special_items import SharedSpecialItemsTests
        case=SharedSpecialItemsTests();case.setUp();self.addCleanup(case.doCleanups)
        case.prepare(324);case.clear()
        field=case.battle['field'];a=field.actor(case.ids[0]);b=field.actor(case.ids[1])
        result=case.case.send(0,encode_attack_request(AttackRequest(a.actor_id,b.x,b.y)))
        other=tuple(case.case.hub.queues[case.owners[1]])
        for packets in (result,other):
            streams=[p for p in packets if p[:2]==b'\xf7\2'];self.assertEqual(len(streams),1)
            self.assertEqual(decode_flame_stream(streams[0])[0],a.actor_id)
            attack=next(p for p in packets if p[0]==0x4b)
            self.assertLess(packets.index(streams[0]),packets.index(attack))
        self.assertFalse(any(p[0]==0x30 for p in other))
        fuel=next(i.unknown_words[0] for i in decode_item_list(field.combat.inventories[a.actor_id])[1] if i.template_id==324)
        self.assertEqual(fuel,291)
        case.restore()
        for owner in case.owners:
            self.assertFalse(any(p[:2]==b'\xf7\2' for p in case.case.hub.queues[owner]))
        self.assertEqual(next(i.unknown_words[0] for i in decode_item_list(case.battle['field'].combat.inventories[a.actor_id])[1] if i.template_id==324),fuel)
