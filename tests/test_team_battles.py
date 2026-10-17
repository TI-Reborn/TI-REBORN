from wallet_fixture import fund_wallet
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from tio.abilities import AbilityCatalog, AbilityLevel
from tio.arena_service import ArenaService
from tio.battle_state import BattleActor, BattleField
from tio.city_catalogs import CityCatalogs
from tio.hiring import HireStore
from tio.matchmaking import SurvivalQueue
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.survival_service import SurvivalService
from tio.wallets import WalletStore
from tio.visibility import visible_actors
from tio.protocol.arena import ArenaCreateRequest, encode_create_request, decode_battle_settings_body
from tio.protocol.battle_members import decode_battle_members
from tio.protocol.battle_turn import encode_end_turn
from tools.survival_scene import prepare_survival

ROOT=Path(__file__).resolve().parents[1]


class TeamBattleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db'
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        source=json.loads((ROOT/'config/abilities.json').read_text())
        self.catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        hire=HireStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
        for resource in (1,3,2):hire.hire('alice',resource)
        self.rows=OwnedPetStore(self.path).list('alice')

    def select(self,count):
        for slot,(i,_,_) in enumerate(self.rows,1):
            SquadStore(self.path).assign('alice',i,slot if slot<=count else 0)
        return OwnedPetStore(self.path).list('alice')

    def scene(self,mode,count=1,seed=13):
        roster=self.select(count)
        ticket=SurvivalQueue().join(42,roster,mode=mode)
        return prepare_survival(self.path,'alice',ticket,self.catalog,mode=mode,seed=seed)

    def test_formats_spawn_teams_visibility_and_no_persistent_bots(self):
        for mode,count,players in ((1,1,4),(1,3,4),(4,1,8)):
            self.select(count)
            with closing(sqlite3.connect(self.path)) as db:before='\n'.join(db.iterdump())
            scene=self.scene(mode,count)
            self.assertEqual((scene.field.width,scene.field.height),(57,57))
            self.assertEqual(len(scene.field._actors),players*count)
            self.assertEqual(len({(a.x,a.y) for a in scene.field._actors.values()}),players*count)
            self.assertEqual(len(scene.field.living_sides()),2)
            for index,owner in enumerate(scene.participants):
                self.assertEqual(len(scene.field.actor_ids(owner)),count)
                self.assertEqual(scene.field.teams[owner],index%2)
                if index%2==0:self.assertTrue(set(scene.field.actor_ids(owner))<=scene.visibility.visible)
            self.assertEqual(set(scene.field.combat.persistence),set(scene.actor_ids))
            with closing(sqlite3.connect(self.path)) as db:self.assertEqual(before,'\n'.join(db.iterdump()))

    def test_classic_lobby_start_turns_skip_dead_and_team_result(self):
        scene=self.scene(4)
        service=ArenaService(clock=lambda:0)
        req=ArenaCreateRequest(4,3,8,2,40,1,1,0,0)
        room,_=service.create(42,b'Alice',encode_create_request(req),roster=self.select(1))
        room,members=service.fill_training_room(room)
        records=decode_battle_members(members)[2]
        self.assertEqual([m.team for m in records],[0,1,0,1,0,1,0,1])
        room,replies=service.start_survival(42,b'Alice',scene,existing_room=room)
        self.assertEqual(decode_battle_settings_body(replies[0][1:]).mode,4)
        service.member_loaded(42,b'\x36')
        for owner in scene.participants:
            actors=scene.field.living_actor_ids(owner)
            service.begin_turn_packets(owner,actors,40)
            service.end_turn(owner,encode_end_turn(actors[0]))
            self.assertEqual(service.next_turn_owner(room.room_id),scene.participants[(scene.participants.index(owner)+1)%8])
        # Human eliminated: battle and allied sight survive, no immediate loss.
        actor=scene.field.actor(scene.actor_ids[0])
        scene.field._actors[actor.actor_id]=replace(actor,health=0)
        self.assertNotEqual(service.next_turn_owner(room.room_id),42)
        self.assertEqual(service.finish_training(42,self.path,'alice'),())
        for i,a in list(scene.field._actors.items()):
            if not scene.field.allied(a.owner_id,42):scene.field._actors[i]=replace(a,health=0)
        self.assertEqual(len(scene.field.living_sides()),1)
        replies=service.finish_training(42,self.path,'alice')
        self.assertTrue(replies)
        self.assertEqual(next(p for p in replies if p[:1]==b'\x4c')[3],1)
        self.assertEqual(service.rooms.snapshot(),())
        self.assertEqual(service.finish_training(42,self.path,'alice'),())

    def test_search_modes_pause_resume_and_wall_rejects_extra_fighters(self):
        now=[0]
        service=SurvivalService(clock=lambda:now[0])
        roster=self.select(3)
        with self.assertRaises(ValueError):service.join(42,b'Alice',b'\xba\x03\x04\x03',roster)
        self.assertFalse(service.searching(42))
        service.join(42,b'Alice',b'\xba\x03\x01\x03',roster)
        self.assertEqual(service.queue.tickets[42].mode,1)
        with self.assertRaises(ValueError):service.join(42,b'Alice',b'\xba\x03\0\3',roster)
        service.set_ready(42,b'\xba\x07\0')
        self.assertIsNone(service.queue.propose(42))
        service.set_ready(42,b'\xba\x07\1')
        now[0]=6
        self.assertEqual(service.queue.propose(42).first.mode,1)

    def test_allied_spotting_does_not_grant_control_or_allow_direct_attack(self):
        from tio.combat import Combat
        from tio.weapons import WeaponCatalog
        from tio.protocol.item_list import encode_item_list
        from tio.protocol.battle_attack import AttackRequest
        from tio.protocol.battle_move import BattleMove
        actors=[BattleActor(1,10,1,1,17,100,100,sight_radius=2),
                BattleActor(2,20,8,1,17,100,100,sight_radius=3),
                BattleActor(3,30,10,1,17,100,100,sight_radius=2)]
        field=BattleField(16,16,actors,step_cost=1,teams={10:0,20:0,30:1})
        self.assertIn(3,visible_actors(field,10))
        with self.assertRaises(ValueError):field.move(10,BattleMove(2,((8,2),)))
        field.combat=Combat(field,WeaponCatalog())
        for actor in actors:field.combat.register(actor.actor_id,encode_item_list(actor.actor_id,()),human=False)
        field._actors[1]=replace(actors[0],x=7)
        with self.assertRaisesRegex(ValueError,'Visible enemy'):field.combat.attack(10,AttackRequest(1,8,1))
        self.assertEqual(field.actor(1).action_points,17)

    def test_bot_turn_attacks_enemy_spends_ap_and_ignores_ally(self):
        from tio.training_bot import play_turn
        scene=self.scene(1)
        arena=ArenaService(clock=lambda:0)
        room,_=arena.start_survival(42,b'Alice',scene)
        arena.member_loaded(42,b'\x36')
        field=scene.field
        field.blocked=frozenset()
        field.loot.boxes.clear() # Combat-only fixture; scavenging has separate tests.
        # Unarmed mirror actors meet in melee range; ensure a real attack.
        from tio.protocol.item_list import encode_item_list
        for index,owner in enumerate(scene.participants):
            i=field.actor_ids(owner)[0]
            field._actors[i]=replace(field.actor(i),x=5+index,y=5)
            field.combat.register(i,encode_item_list(i,()),human=True)
        bot=scene.participants[1]
        enemy=field.actor_ids(42)[0]
        ally=field.actor_ids(scene.participants[3])[0]
        before=field.actor(ally).health
        replies=play_turn(arena,room.room_id,bot,view=scene.visibility)
        self.assertTrue(any(p[:1]==b'\x4b' for p in replies))
        self.assertLess(field.actor(enemy).health,field.actor(enemy).max_health)
        self.assertEqual(field.actor(ally).health,before)
        self.assertLess(field.actor(field.actor_ids(bot)[0]).action_points,15)
        self.assertFalse(any(p[:1]==b'\x30' for p in replies))

    def test_encrypted_transport_search_and_created_room_complete_turn_cycle(self):
        import socket,threading,time
        from tools.loopback_exchange import LoopbackExchange
        from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
        for mode,count,created in ((1,3,False),(4,1,True)):
            self.select(count)
            transport_path=Path(self.temp.name)/f'transport-{mode}.db'
            with closing(sqlite3.connect(self.path)) as source,closing(sqlite3.connect(transport_path)) as target:
                source.backup(target)
                for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    quoted='"'+table.replace('"','""')+'"'
                    if any(r[1]=='account' for r in target.execute('PRAGMA table_info('+quoted+')')):
                        target.execute('UPDATE '+quoted+" SET account='probe_user' WHERE account='alice'")
                target.commit()
            exchange=LoopbackExchange(Path(self.temp.name)/'events.json',database=transport_path,
                open_town_probe=True,owned_pet_probe=True,observation_seconds=0)
            exchange.probe_character_id=42;exchange.probe_character_name=b'Alice';exchange.locations=None
            exchange.survival.queue.bot_delay=0
            server,client=socket.socketpair();client.settimeout(6)
            thread=threading.Thread(target=exchange.observe_game,args=(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C')))
            thread.start()
            try:
                cipher=InitialCipher('C2S');reader=InitialFrameReader(InitialCipher('S2C'))
                def until(packet,predicate):
                    client.sendall(encode_initial_frame(packet,cipher))
                    packets=[];deadline=time.monotonic()+8
                    while not predicate(packets):
                        self.assertLess(time.monotonic(),deadline,(packets,exchange.events))
                        chunk=client.recv(65535)
                        self.assertTrue(chunk,'Transport closed')
                        packets.extend(reader.feed(chunk))
                    return packets
                if created:
                    req=ArenaCreateRequest(mode,3,8,2,40,count,count,0,0)
                    packets=until(encode_create_request(req),lambda ps:any(p[:1]==b'\x25' for p in ps))
                    self.assertEqual(len(decode_battle_members(next(p for p in packets if p[:1]==b'\x25'))[2]),8)
                    packets=until(b'\x2e',lambda ps:b'\x41' in ps)
                else:
                    packets=until(bytes((0xba,3,mode,count)),lambda ps:b'\x41' in ps)
                self.assertTrue(any(p[:1]==b'\x35' for p in packets))
                self.assertEqual(len(exchange.arena.rooms.snapshot()),1)
                room=exchange.arena.rooms.snapshot()[0]
                self.assertEqual(room.request.mode,mode)
                until(b'\x36',lambda ps:any(p[:1]==b'\x38' for p in ps))
                field=exchange.arena._fields[room.room_id]
                own=field.living_actor_ids(42)
                turns={i:field._ability_turns[i] for i in field._actors}
                until(encode_end_turn(own[0]),lambda ps:any(p[:1]==b'\x38' for p in ps))
                self.assertEqual(exchange.arena._turns[room.room_id][0],42)
                for i in field._actors:self.assertEqual(field._ability_turns[i],turns[i]+1)
                # Duplicate load acknowledgement must not refill AP/turns.
                until(b'\x36\x00',lambda ps:any(p[:1]==b'\xf0' for p in ps))
                self.assertEqual(field._ability_turns[own[0]],2)
            finally:
                client.close();thread.join(3);exchange.stop();server.close()
            self.assertFalse(thread.is_alive())
