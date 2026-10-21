import unittest
from dataclasses import replace
from tio.battle_state import BattleActor,BattleField
from tio.battle_doors import BattleDoors
from tio.protocol.battle_door import DoorRequest,encode_door_request,decode_door_request,encode_door_state
from tio.protocol.battle_move import BattleMove
from tio.visibility import visible_actors


class DoorTests(unittest.TestCase):
    def setUp(self):
        self.field=BattleField(8,8,[BattleActor(1,7,2,3,10,100,100),BattleActor(2,8,5,3,10,100,100)],
                               blocked={(3,y) for y in range(8) if y!=3},step_cost=1)
        self.doors=BattleDoors(self.field,((3,3,False),),{1:{True,False},2:{True,False}})
        self.field.doors=self.doors
        self.open=DoorRequest(1,True,3,3)

    def test_wire_order_and_strict_validation(self):
        p=encode_door_request(self.open)
        self.assertEqual(p,bytes.fromhex('3e01000000010303'))
        self.assertEqual(decode_door_request(p),self.open)
        self.assertEqual(encode_door_state(self.open),bytes.fromhex('3f01000000030301'))
        for bad in (p[:-1],p+b'\0',b'\x3f'+p[1:],p[:5]+b'\x02'+p[6:]):
            with self.assertRaises(ValueError):decode_door_request(bad)

    def test_open_close_movement_sight_cost_and_state_across_turns(self):
        self.assertNotIn(2,visible_actors(self.field,7))
        with self.assertRaises(ValueError):self.field.move(7,BattleMove(1,((3,3),)))
        replies=self.doors.change(7,self.open)
        self.assertEqual(replies[0],encode_door_state(self.open))
        self.assertEqual(self.field.actor(1).action_points,9)
        self.assertIn(2,visible_actors(self.field,7))
        self.doors.change(7,self.open)  # Idempotent state request, no second charge.
        self.assertEqual(self.field.actor(1).action_points,9)
        self.field.move(7,BattleMove(1,((3,3),(4,3))))
        self.field.prepare_turn(7,(1,))
        self.assertTrue(self.doors.states[(3,3)])
        self.doors.change(7,replace(self.open,opened=False))
        self.assertEqual(self.field.actor(1).action_points,9)
        self.assertIn((3,3),self.field.blocked)
        self.assertFalse(self.doors.states[(3,3)])
        for _ in range(3):
            before=self.field.actor(1).action_points
            with self.assertRaises(ValueError):self.field.move(7,BattleMove(1,((3,3),)))
            self.assertEqual(self.field.actor(1).action_points,before)
            self.doors.change(7,self.open)
            self.assertNotIn((3,3),self.field.blocked)
            self.doors.change(7,replace(self.open,opened=False))
            self.assertIn((3,3),self.field.blocked)
            self.assertEqual(self.field.actor(1).action_points,before-2)

    def test_failed_actions_are_atomic_and_occupied_door_cannot_close(self):
        before=self.field.actor(1)
        for owner,req in ((8,self.open),(7,replace(self.open,x=4)),(7,replace(self.open,actor_id=99))):
            with self.assertRaises(ValueError):self.doors.change(owner,req)
            self.assertEqual(self.field.actor(1),before)
            self.assertFalse(self.doors.states[(3,3)])
        for change in ({'action_points':0},{'health':0},{'x':0},{'x':1,'y':2}):
            self.field._actors[1]=replace(before,**change)
            with self.assertRaises(ValueError):self.doors.change(7,self.open)
            self.assertFalse(self.doors.states[(3,3)])
        self.field._actors[1]=before
        self.doors.permissions[1]=set()
        with self.assertRaises(ValueError):self.doors.change(7,self.open)
        self.doors.permissions[1]={True,False}
        self.doors.change(7,self.open)
        self.field.move(7,BattleMove(1,((3,3),)))
        before=self.field.actor(1)
        with self.assertRaises(ValueError):self.doors.change(7,replace(self.open,opened=False))
        self.assertEqual(self.field.actor(1),before)
        self.assertTrue(self.doors.states[(3,3)])

    def test_all_eight_neighbors_operate_door_despite_wall_corners(self):
        for dx,dy in ((x,y) for x in (-1,0,1) for y in (-1,0,1) if x or y):
            for corners in ((),((3+dx,3),),((3,3+dy),),((3+dx,3),(3,3+dy))):
                with self.subTest(offset=(dx,dy),corners=corners):
                    walls=set(corners)-{(3,3),(3+dx,3+dy)}
                    field=BattleField(8,8,[BattleActor(1,7,3+dx,3+dy,10,100,100)],blocked=walls,step_cost=1)
                    doors=BattleDoors(field,((3,3,False),),{1:{True,False}})
                    for opened in (True,True,False):
                        replies=doors.change(7,replace(self.open,opened=opened))
                        self.assertEqual(replies[0],encode_door_state(replace(self.open,opened=opened)))
                        self.assertEqual(doors.states[(3,3)],opened)
                        self.assertEqual(field.blocked,frozenset(walls)|({(3,3)} if not opened else set()))
                    self.assertEqual(field.actor(1).action_points,8)

    def test_diagonal_surface_updates_do_not_reveal_enemy_or_allow_corner_movement(self):
        self.field._actors[1]=replace(self.field.actor(1),x=2,y=2)
        self.field._actors[2]=replace(self.field.actor(2),x=4,y=2)
        self.assertNotIn(2,visible_actors(self.field,7))
        self.assertEqual(self.doors.visible_updates(7,{}),
                         (encode_door_state(replace(self.open,actor_id=0,opened=False)),))
        self.doors.change(7,self.open)
        self.assertNotIn(2,visible_actors(self.field,7))
        before=self.field.actor(1)
        with self.assertRaises(ValueError):self.field.move(7,BattleMove(1,((3,3),)))
        self.assertEqual(self.field.actor(1),before)
        self.doors.change(7,replace(self.open,opened=False))

    def test_generated_combat_profiles_use_same_diagonal_door_rule(self):
        import json
        from pathlib import Path
        from tio.map_generation import generate_map
        profiles=json.loads((Path(__file__).resolve().parents[1]/'config/battle_map_profiles.json').read_text())['profiles']
        checked=0
        for profile,policy in profiles.items():
            for variant in policy['variants']:
                for mode in (0,1,4,7):
                    arena=generate_map(profile,mode=mode,variant=variant['name'],seed=19).arena
                    for x,y,initial_opened in arena.doors:
                        for dx,dy in ((-1,-1),(-1,1),(1,-1),(1,1)):
                            p=x+dx,y+dy
                            if p in arena.blocked or not (0<=p[0]<arena.ground.width and 0<=p[1]<arena.ground.height):continue
                            with self.subTest(profile=profile,variant=variant['name'],mode=mode,door=(x,y),actor=p):
                                field=BattleField(arena.ground.width,arena.ground.height,
                                    [BattleActor(1,7,*p,10,100,100)],blocked=arena.blocked,step_cost=1)
                                doors=BattleDoors(field,arena.doors,{1:{True,False}})
                                for opened in (True,False):doors.change(7,DoorRequest(1,opened,x,y))
                                self.assertEqual(field.actor(1).action_points,9 if initial_opened else 8)
                                checked+=1
        self.assertGreater(checked,0)

    def test_hidden_changes_are_sent_when_seen_without_actor_identity(self):
        remembered=dict(self.doors.states)
        self.field._actors[1]=replace(self.field.actor(1),sight_radius=0)
        self.field._actors[2]=replace(self.field.actor(2),x=4)
        self.doors.change(8,replace(self.open,actor_id=2))
        self.assertEqual(self.doors.visible_updates(7,remembered),())
        self.field._actors[1]=replace(self.field.actor(1),sight_radius=9)
        self.assertEqual(self.doors.visible_updates(7,remembered),(encode_door_state(replace(self.open,actor_id=0)),))
        self.assertEqual(self.doors.visible_updates(7,remembered),())

    def test_turn_authority_and_bot_opens_door_on_path(self):
        from tio.arena_service import ArenaService
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        from tio.protocol.battle_turn import encode_end_turn
        from tio.training_bot import play_turn
        arena=ArenaService(clock=lambda:10)
        arena.create(7,b'Alice',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
        arena.start_loading(7,b'\x2e',lambda room:(encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64))),b'\x41'))
        arena.configure_field(7,self.field);arena.member_loaded(7,b'\x36')
        packet=encode_door_request(self.open)
        with self.assertRaises(ValueError):arena.door_action(7,packet)
        arena.begin_turn_packets(7,(1,),40)
        with self.assertRaises(ValueError):arena.door_action(8,packet)
        with self.assertRaises(ValueError):arena.door_action(7,encode_door_request(replace(self.open,actor_id=2)))
        arena.door_action(7,packet)
        arena.door_action(7,encode_door_request(replace(self.open,opened=False)))
        arena.end_turn(7,encode_end_turn(1))
        with self.assertRaises(ValueError):arena.door_action(7,packet)
        # Explore a public point beyond the closed door, no visible enemies.
        self.field.patrol_waypoints=((5,3),)
        self.field._actors[1]=replace(self.field.actor(1),sight_radius=0)
        self.field._actors[2]=replace(self.field.actor(2),x=6,y=6)
        room=arena.rooms.snapshot()[0]
        updates=play_turn(arena,room.room_id,7)
        self.assertTrue(self.doors.states[(3,3)])
        self.assertTrue(any(p[:1]==b'\x3f' for p in updates))
        self.assertEqual((self.field.actor(1).x,self.field.actor(1).y),(5,3))
        self.assertEqual(self.field.actor(1).action_points,0)

    def test_encrypted_transport_open_close_and_rejection_restore(self):
        import socket,threading,tempfile
        from pathlib import Path
        from tools.loopback_exchange import LoopbackExchange
        from tio.arena_service import ArenaService
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
        with tempfile.TemporaryDirectory() as folder:
            exchange=LoopbackExchange(Path(folder)/'events.json',open_town_probe=True,observation_seconds=0)
            exchange.probe_character_id=7;exchange.probe_character_name=b'Alice'
            exchange.arena=arena=ArenaService(clock=lambda:10)
            arena.create(7,b'Alice',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
            arena.start_loading(7,b'\x2e',lambda room:(encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64))),b'\x41'))
            arena.configure_field(7,self.field);arena.member_loaded(7,b'\x36')
            arena.begin_turn_packets(7,(1,),40)
            server,client=socket.socketpair();client.settimeout(3)
            thread=threading.Thread(target=exchange.observe_game,args=(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C')))
            thread.start()
            try:
                cipher=InitialCipher('C2S');reader=InitialFrameReader(InitialCipher('S2C'))
                def send(request,count=2):
                    wire=request if isinstance(request,bytes) else encode_door_request(request)
                    client.sendall(encode_initial_frame(wire,cipher))
                    packets=[]
                    while len(packets)<count:
                        chunk=client.recv(65535)
                        if not chunk:raise AssertionError('Transport closed')
                        packets.extend(reader.feed(chunk))
                    return packets
                opened=send(self.open)
                self.assertEqual([p[0] for p in opened],[0x3f,0x4e])
                self.assertTrue(self.doors.states[(3,3)])
                closed=send(replace(self.open,opened=False))
                self.assertEqual([p[0] for p in closed],[0x3f,0x4e])
                self.assertEqual(self.field.actor(1).action_points,8)
                self.field._actors[1]=replace(self.field.actor(1),action_points=0)
                rejected=send(self.open,4)
                self.assertEqual([p[0] for p in rejected],[0xf0,0x3f,0x3d,0x4e])
                self.assertEqual(rejected[1],encode_door_state(replace(self.open,opened=False)))
                self.assertFalse(self.doors.states[(3,3)])
                from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
                self.field._actors[1]=replace(self.field.actor(1),action_points=10)
                refused=send(encode_move_request(BattleMove(1,((3,3),))),3)
                self.assertEqual([p[0] for p in refused],[0xf0,0x3d,0x4e])
                self.assertEqual(decode_battle_move(refused[1]),BattleMove(1,((2,3),(2,3))))
                accepted=send(encode_move_request(BattleMove(1,((2,4),))))
                self.assertEqual([p[0] for p in accepted],[0x3d,0x4e])
                self.assertEqual((self.field.actor(1).x,self.field.actor(1).y,self.field.actor(1).action_points),(2,4,9))
            finally:
                client.close();thread.join(3);exchange.stop();server.close()
            self.assertFalse(thread.is_alive())
