from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import socket
import tempfile
import threading
import unittest

from test_combat import item,FixedRandom
from test_weapon_proficiency import profile
from tio.battle_state import BattleActor,BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.visibility import VisibilityView
from tools.battle_actor_fixture import actor_packet
from tio.battle_equipment import inventory_after_snapshot


def scene(weapon=312,distance=4,rental=False):
    f=BattleField(40,40,[BattleActor(1,7,1,1,12,100,100,sight_radius=30),
                        BattleActor(2,8,1+distance,1,12,1000,1000)],step_cost=1)
    c=Combat(f,WeaponCatalog(),rng=FixedRandom());f.combat=c
    gear=item(100,weapon,equipped=True)
    if rental:gear=replace(gear,unknown_bytes_02=b'\x14\0\0\1',unknown_bytes_03=b'\x14\0\0',optional_u32=9371)
    p=profile(4)
    bag=encode_item_list(1,(gear,item(101,c.catalog.weapons[weapon].ammo_id,100)))
    from tio.weight import project_base_weight
    p=project_base_weight(p,True,bag)
    c.register(1,bag,human=True,pet_packet=p)
    t=decode_battle_soldier(actor_packet(p,7,bag,x=1,y=1),human_equipment=True)
    view=VisibilityView(f,7,{1:t,2:replace(t,fields={**t.fields,'0x8c5088':2,'0x8c50ea':8})})
    view.visible=frozenset((1,2))
    return f,c,view


class BattleWeaponRegressions(unittest.TestCase):
    def test_low_obstacles_block_movement_but_allow_awp_and_automatic_fire(self):
        from tio.protocol.battle_move import BattleMove
        for weapon in (312,304):
            f,c,view=scene(weapon)
            f.blocked=frozenset({(3,1)});f.transparent_obstacles=f.blocked
            with self.assertRaises(ValueError):f.move(7,BattleMove(1,((2,1),(3,1))))
            before=f.actor(1).action_points
            c.attack(7,AttackRequest(1,5,1),view=view)
            self.assertEqual(f.actor(1).action_points,before-c.catalog.weapons[weapon].attack_ap)
            self.assertLess(f.actor(2).health,1000)

    def test_native_edge_rays_allow_corner_shot_but_not_solid_wall(self):
        from tio.shot_geometry import clear_shot
        self.assertTrue(clear_shot((1,1),(3,3),{(2,1)}))
        self.assertFalse(clear_shot((1,1),(3,3),{(2,1),(1,2)}))
        f,c,view=scene()
        f.transparent_obstacles=frozenset()
        f.blocked=frozenset((3,y) for y in range(40))
        before=(dict(f._actors),dict(c.inventories))
        with self.assertRaises(ValueError):c.attack(7,AttackRequest(1,5,1),view=view)
        self.assertEqual((f._actors,c.inventories),before)

    def test_closed_door_blocks_shots_after_repeated_open_and_close(self):
        from tio.battle_doors import BattleDoors
        from tio.protocol.battle_door import DoorRequest
        from tio.visibility import field_sight
        f,_,_=scene();f.transparent_obstacles=frozenset()
        f._actors[1]=replace(f.actor(1),x=2)
        doors=BattleDoors(f,((3,1,False),),{1:(True,False)})
        for _ in range(2):
            self.assertFalse(field_sight(f,(2,1),(5,1)))
            doors.change(7,DoorRequest(1,True,3,1))
            self.assertTrue(field_sight(f,(2,1),(5,1)))
            doors.change(7,DoorRequest(1,False,3,1))
        self.assertFalse(field_sight(f,(2,1),(5,1)))

    def test_awp_fires_below_reference_range_and_consumes_ap_ammo(self):
        for distance in (1,2,4,6,7,18):
            f,c,view=scene(distance=distance)
            c.attack(7,AttackRequest(1,1+distance,1),view=view)
            self.assertEqual(f.actor(1).action_points,3)
            self.assertLess(f.actor(2).health,1000)
            self.assertEqual(decode_item_list(c.inventories[1])[1][1].count,99)

    def test_awp_range_wall_ammo_and_ap_rejections_do_not_mutate(self):
        for reason in ('range','wall','ammo','ap'):
            f,c,view=scene(distance=19 if reason=='range' else 4)
            if reason=='wall':f.blocked=frozenset(((3,1),))
            if reason=='ammo':c.inventories[1]=encode_item_list(1,decode_item_list(c.inventories[1])[1][:1])
            if reason=='ap':f._actors[1]=replace(f.actor(1),action_points=8)
            before=(dict(f._actors),dict(c.inventories))
            with self.assertRaises(ValueError):c.attack(7,AttackRequest(1,f.actor(2).x,1),view=view)
            self.assertEqual((f._actors,c.inventories),before)

    def test_snapshot_restore_keeps_real_rental_and_effective_upgrade_private(self):
        f,c,view=scene(304,rental=True)
        original=decode_item_list(c.inventories[1])[1][0]
        replies=c.attack(7,AttackRequest(1,5,1),view=view)
        snapshot=next(p for p in reversed(replies) if p[0]==0x3b)
        restored=inventory_after_snapshot((f,),7,snapshot)
        gear=decode_item_list(restored)[1][0]
        self.assertEqual((gear.instance_id,gear.unknown_bytes_02,gear.unknown_bytes_03,gear.optional_u32),
                         (100,b'\x0a\0\0\1',b'\x14\0\0',9371))
        self.assertEqual(decode_item_list(c.inventories[1])[1][0],replace(original,unknown_words=(295,300,300)))
        self.assertIsNone(inventory_after_snapshot((f,),8,snapshot))
        self.assertIsNone(inventory_after_snapshot((f,),7,view.snapshot(2)))

    def test_encrypted_attack_sends_full_item_metadata_after_skill_snapshot(self):
        from tools.loopback_exchange import LoopbackExchange
        from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.db'
            from tio.owned_pets import OwnedPetStore
            f,c,view=scene(304,rental=True)
            OwnedPetStore(path).ensure('probe_user',profile(4),c.inventories[1],human=True)
            exchange=LoopbackExchange(Path(folder)/'events.json',database=path,open_town_probe=True,observation_seconds=0)
            exchange.locations=None;exchange.probe_character_id=7
            arena=exchange.arena;arena._clock=lambda:10
            arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
            arena._fields[1]=f;arena._turns[1]=(7,{1},50)
            exchange.visibility_views[1]=view
            server,client=socket.socketpair();client.settimeout(3)
            thread=threading.Thread(target=exchange.observe_game,args=(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C')))
            thread.start()
            try:
                client.sendall(encode_initial_frame(encode_attack_request(AttackRequest(1,5,1)),InitialCipher('C2S')))
                reader=InitialFrameReader(InitialCipher('S2C'));packets=[]
                while len(packets)<9:
                    try:packets.extend(reader.feed(client.recv(65535)))
                    except TimeoutError:raise AssertionError(([p.hex() for p in packets],exchange.events))
                self.assertEqual([p[0] for p in packets],[0x4b,0x4e,0x30,0x4e,0x4e,0x3b,0x30,0x4e,0x4e])
                gear=decode_item_list(packets[6])[1][0]
                self.assertEqual((gear.unknown_bytes_02[0],gear.unknown_bytes_03[0],gear.optional_u32),(10,20,9371))
            finally:
                client.close();thread.join(3);exchange.stop();server.close()
            self.assertFalse(thread.is_alive())
