from wallet_fixture import fund_wallet
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from server.team_arena import TeamArena
from tio.arena_service import ArenaService
from tio.survival_service import SurvivalService
from tio.wallets import WalletStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.pet_info import decode_pet_info,encode_pet_info

ROOT=Path(__file__).resolve().parents[1]


class Session:
    def stop(self):raise AssertionError('Unexpected queue overflow')


class SharedTeamTests(unittest.TestCase):
    def verify_member_order(self,mode):
        from tio.protocol.battle_members import decode_battle_members
        from tio.protocol.battle_turn import encode_members_arranged
        initial_replies={}
        for index in (0,1):self.create(index,mode);initial_replies[index]=self.send(index,b'\x2e')
        owners=[self.hub.identities[s] for s in self.sessions[:2]]
        battle=self.hub.battles[owners[0]];sequence=battle['room'].members
        self.assertEqual(len(sequence),4 if mode==1 else 8)
        for index,viewer in enumerate(owners):
            expected=tuple(1 if member==viewer else member for member in sequence)
            packet=encode_members_arranged(expected)
            initial=list(initial_replies[index])+list(self.hub.queues[viewer])
            self.assertIn(packet,initial)
            self.hub.queues[viewer].clear();self.hub.send_scene(viewer,reconnect=True)
            scene=list(self.hub.queues[viewer]);self.assertIn(packet,scene)
            member_index=next(i for i,p in enumerate(scene) if p[0]==0x25)
            self.assertEqual(scene[member_index+1],packet)
            members=decode_battle_members(scene[member_index])[2]
            self.assertEqual(tuple(m.character_id for m in members),expected)
            self.assertLess(member_index+1,scene.index(b'\x41'))
        self.hub.offline[owners[0]]=180
        self.hub.queues[owners[1]].clear();self.hub.notify_online(battle,exclude=owners[0])
        updates=list(self.hub.queues[owners[1]])
        self.assertEqual(updates[-1],self.hub.battle_order_packet(battle,owners[1]))
        self.assertEqual(updates[-1],encode_members_arranged(1 if m==owners[1] else m for m in sequence))

    def test_team_member_numbers_match_authoritative_order_and_reload(self):
        self.verify_member_order(1)

    def test_wall_member_numbers_match_authoritative_order_and_reload(self):
        self.verify_member_order(4)

    def add_selected(self,index,count,*,reserve_level=None):
        session=self.sessions[index];store=OwnedPetStore(self.path)
        _,packet,_=store.list(session.account)[0]
        pet=decode_pet_info(packet,human_equipment=True)
        for identity in range(2,count+1):
            fields={**pet.fields,'0x8c43eb':identity,'0x8c44a6':identity}
            if reserve_level is not None:fields['0x8c4aef']=reserve_level
            store.ensure(session.account,encode_pet_info(replace(pet,fields=fields)),encode_item_list(identity,()),human=True)

    def test_wall_multiple_selected_admits_first_and_preserves_reserves(self):
        self.add_selected(1,3,reserve_level=7)
        before=OwnedPetStore(self.path).list(self.sessions[1].account)
        for index in (0,1):self.create(index,4);self.send(index,b'\x2e')
        owners=[self.hub.identities[s] for s in self.sessions[:2]]
        battle=self.hub.battles[owners[1]]
        self.assertEqual(len(battle['field']._actors),8)
        for owner in owners:
            ids=battle['field'].actor_ids(owner)
            self.assertEqual(len(ids),1)
            self.assertEqual(battle['field'].combat.storage_ids[ids[0]],1)
        self.assertEqual(OwnedPetStore(self.path).list(self.sessions[1].account),before)

    def test_team_one_against_two_admits_equal_squads(self):
        self.add_selected(1,2)
        before=OwnedPetStore(self.path).list(self.sessions[1].account)
        for index in (0,1):
            self.send(index,b'\xba\3\1\1');self.send(index,b'\x2e')
        battle=self.hub.battles[self.hub.identities[self.sessions[0]]]
        self.assertEqual(len(battle['field']._actors),4)
        self.assertEqual(battle['room'].request.soldiers_count_01,1)
        self.assertEqual(OwnedPetStore(self.path).list(self.sessions[1].account),before)

    def test_four_humans_team_three_against_two_trims_every_participant(self):
        for index,count in ((0,3),(2,3),(1,2),(3,2)):self.add_selected(index,count)
        for index in (0,1):self.send(index,b'\xba\3\1\1')
        for index,captain in ((2,0),(3,1)):
            room=self.hub.lobbies.room(self.hub.identities[self.sessions[captain]])
            self.send(index,b'\xba\4'+room.identity.to_bytes(4,'little'))
            self.send(index,b'\x2c\1')
        for index in (0,1):self.send(index,b'\x2e')
        battle=self.hub.battles[self.hub.identities[self.sessions[0]]]
        self.assertFalse(battle['bots'])
        self.assertEqual(len(battle['field']._actors),8)
        self.assertEqual(battle['room'].request.soldiers_count_01,2)
        self.assertEqual(battle['room'].request.unknown_u32_01,60)
        for index,session in enumerate(self.sessions):
            ids=battle['field'].actor_ids(self.hub.identities[session])
            self.assertEqual(len(ids),2)
            self.assertEqual({battle['field'].combat.storage_ids[i] for i in ids},{1,2})
            self.assertEqual(len(OwnedPetStore(self.path).list(session.account)),3 if index in (0,2) else 2)

    def test_wall_reordered_selection_still_rejected_before_pair_consumed(self):
        self.add_selected(0,2)
        self.create(0,4);self.send(0,b'\x2e')
        session=self.sessions[0];store=OwnedPetStore(self.path)
        _,raw,_=store.list(session.account)[0]
        pet=decode_pet_info(raw,human_equipment=True)
        raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c44a6':0}))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(raw,session.account))
        self.create(1,4);replies=self.send(1,b'\x2e')
        self.assertTrue(any(p[0]==0xf0 for p in replies))
        self.assertFalse(self.hub.battles)
        self.assertEqual(len(self.hub.lobbies.rooms),2)

    def test_wounded_team_and_wall_rejected_with_readable_hp_then_healed_retry(self):
        for index,mode in ((0,1),(1,4)):
            session=self.sessions[index]
            store=OwnedPetStore(self.path)
            identity,raw,inventory=store.list(session.account)[0]
            pet=decode_pet_info(raw,human_equipment=True)
            hurt=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4ab1':1}))
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(hurt,session.account,identity))
            replies=self.send(index,bytes((0xba,3,mode,1)))
            error=next(p for p in replies if p[0]==0xf0)
            self.assertEqual(int.from_bytes(error[9:13],'little'),5)
            message=error[13:-2].decode('utf-16-le')
            self.assertIn(f"здоровье 1/{pet.fields['0x8c4a07']}",message)
            self.assertIn('Вылечите',message)
            self.assertIsNone(self.hub.lobbies.room(self.hub.identities[session]))
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(raw,session.account,identity))
            self.assertTrue(any(p[0]==0x25 for p in self.send(index,bytes((0xba,3,mode,1)))))

    def test_hidden_opponent_remains_alive_without_disclosing_position_or_hp(self):
        from tio.protocol.battle_soldier import decode_battle_soldier
        owners,battle=self.paired();field=battle['field']
        for owner in owners:
            from tio.visibility import VisibilityView
            previous=battle['views'][owner]
            view=VisibilityView(field,owner,previous.templates)
            packets=view.refresh()
            hidden=[i for i in field._actors if i not in view.visible]
            self.assertTrue(hidden)
            for identity in hidden:
                packet=next(p for p in packets if p[0]==0x3b and int.from_bytes(p[1:5],'little')==identity)
                data=decode_battle_soldier(packet,human_equipment=True).fields
                self.assertEqual((data['0x8c519b'],data['0x8c51af'],data['0x8c57bb']),(255,255,1))
            actor=field.actor(hidden[0]);field._actors[actor.actor_id]=replace(actor,x=actor.x+1)
            from tio.protocol.night_vision_state import decode_night_vision_state
            refresh=view.refresh()
            self.assertEqual(refresh[:2],(b'\xf7\x01\x00\x00',b'\xf9\x01\x00\x00'))
            self.assertEqual(refresh[2][0],0xfb)
            self.assertEqual(refresh[3][:2],b'\xfc\x01')
            import struct
            avatar_ids={struct.unpack_from('<I',refresh[3],at)[0] for at in range(4,len(refresh[3]),8)}
            self.assertEqual(avatar_ids,view.visible)
            self.assertFalse(avatar_ids.intersection(hidden))
            self.assertEqual(decode_night_vision_state(refresh[1]),())
            field._actors[actor.actor_id]=replace(actor,health=0)
            updates=view.refresh()
            packet=next(p for p in updates if p[0]==0x3b and int.from_bytes(p[1:5],'little')==actor.actor_id)
            self.assertEqual(decode_battle_soldier(packet,human_equipment=True).fields['0x8c57bb'],0)
            field._actors[actor.actor_id]=actor

    def test_skip_clears_ap_before_disabling_input_and_restores_next_turn(self):
        from tio.protocol.action_points import encode_action_points
        owners,battle=self.open_battle();field=battle['field'];arena=battle['arena']
        identity=field.actor_ids(owners[0])[0];budget=field.actor(identity).action_points
        self.assertGreater(budget,0)
        packets=self.send(0,encode_end_turn())
        self.assertLess(packets.index(encode_action_points(identity,0)),packets.index(b'\x39'))
        self.assertEqual(field.actor(identity).action_points,0)
        self.hub.tick();self.send(1,encode_end_turn());self.hub.tick()
        for _ in range(3):
            if arena._turns:break
            self.hub.tick()
        self.assertEqual(field.actor(identity).action_points,budget)
        self.assertEqual(arena._turns[1][0],owners[0])

    def test_timeout_clears_ap_before_disabling_input(self):
        from tio.protocol.action_points import encode_action_points
        owners,battle=self.open_battle();field=battle['field'];identity=field.actor_ids(owners[0])[0]
        self.now=41;self.hub.tick();packets=tuple(self.hub.queues[owners[0]])
        self.assertLess(packets.index(encode_action_points(identity,0)),packets.index(b'\x39'))
        self.assertEqual(field.actor(identity).action_points,0)

    def test_foreign_timer_after_skip_timeout_and_reload(self):
        owners,battle=self.open_battle()
        def packet(owner,seconds):
            return b'\xc8\x17'+owner.to_bytes(4,'little')+seconds.to_bytes(4,'little')
        self.send(0,encode_end_turn());self.hub.tick()
        self.assertIn(packet(owners[1],40),self.hub.queues[owners[0]])
        self.hub.queues[owners[0]].clear()
        self.now=7;self.hub.restore_turn(battle,owners[0])
        self.assertEqual(tuple(self.hub.queues[owners[0]]),(b'\x39',packet(owners[1],33)))
        for q in self.hub.queues.values():q.clear()
        self.now=41;self.hub.tick()
        self.assertIn(b'\x39',self.hub.queues[owners[1]])
        for owner in owners:
            updates=[p for p in self.hub.queues[owner] if p[:2]==b'\xc8\x17']
            self.assertTrue(updates)
            self.assertIn(int.from_bytes(updates[0][2:6],'little'),battle['bots'])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'players.sqlite3'
        self.now=0;self.hub=TeamArena(clock=lambda:self.now)
        # These legacy fixtures exercise immediate two-owner scenarios;
        # grouped 3/4-player admission is covered with the real delay separately.
        self.hub.survival_queue.group_wait=0
        self.sessions=[]
        for name in ('alice','bob','carol','dave'):
            s=Session();s.account=name;s.database=self.path;s.probe_character_id=1
            s.probe_character_name=name.encode();s.locations=None;s.arena=ArenaService();s.survival=SurvivalService()
            fund_wallet(self.path, name, credits=10_000, gold=10_000)
            pet=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
            parsed=decode_pet_info(pet,human_equipment=True)
            pet=encode_pet_info(replace(parsed,fields={**parsed.fields,'0x8c44a6':1,'0x8c4ab1':parsed.fields['0x8c4a07']}))
            OwnedPetStore(self.path).ensure(name,pet,encode_item_list(1,()),human=True)
            self.sessions.append(s)

    def send(self,index,packet):
        s=self.sessions[index]
        self.assertTrue(self.hub.handle(s,packet))
        owner=self.hub.identities[s]
        replies=tuple(self.hub.queues[owner]);self.hub.queues[owner].clear()
        return replies

    def create(self,index,mode=1):
        replies=self.send(index,encode_create_request(ArenaCreateRequest(mode,0,4 if mode==1 else 8,2,40,1,1,0,0)))
        self.assertTrue(any(p[:1]==b'\x6c' for p in replies),replies)
        return self.hub.lobbies.room(self.hub.identities[self.sessions[index]])

    def paired(self):
        for index in (0,1):
            self.create(index);self.send(index,b'\x2e')
        owners=[self.hub.identities[s] for s in self.sessions[:2]]
        battle=self.hub.battles[owners[0]]
        self.assertIs(battle,self.hub.battles[owners[1]])
        self.assertEqual((battle['field'].width,battle['field'].height),(57,57))
        return owners,battle

    def open_battle(self):
        owners,battle=self.paired();field=battle['field']
        field.blocked=frozenset();field.doors.states={}
        for n,(identity,actor) in enumerate(field._actors.items()):
            field._actors[identity]=replace(actor,x=5+n*2,y=5,sight_radius=30,health=100,max_health=100)
            field.combat.register(identity,encode_item_list(identity,()),human=True)
        for view in battle['views'].values():view.refresh()
        self.send(0,b'\x36');self.send(1,b'\x36');self.hub.tick()
        for q in self.hub.queues.values():q.clear()
        return owners,battle

    def test_move_is_animated_for_both_players_without_position_snapshots(self):
        from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
        owners,battle=self.open_battle();field=battle['field'];identity=field.actor_ids(owners[0])[0]
        actor=field.actor(identity);path=((actor.x,6),(actor.x,7))
        replies=self.send(0,encode_move_request(BattleMove(identity,path)))
        other=tuple(self.hub.queues[owners[1]])
        self.assertEqual(decode_battle_move(next(p for p in replies if p[0]==0x3d)).path,path)
        self.assertEqual(tuple(c for p in other if p[0]==0x3d for c in decode_battle_move(p).path),path)
        for packets in (replies,other):
            self.assertFalse(any(p[0]==0x3b for p in packets))
            self.assertTrue(any(p[0]==0x4e for p in packets))
        self.send(0,encode_end_turn());self.hub.tick()
        self.assertEqual(battle['arena']._turns[1][0],owners[1])
        self.assertIn(b'\xc8\x17'+owners[1].to_bytes(4,'little')+(40).to_bytes(4,'little'),self.hub.queues[owners[0]])

    def test_ap_exhaustion_finishes_without_waiting_for_timeout(self):
        from tio.protocol.battle_move import BattleMove,encode_move_request
        owners,battle=self.open_battle();field=battle['field'];identity=field.actor_ids(owners[0])[0]
        actor=field.actor(identity);field._actors[identity]=replace(actor,action_points=1)
        replies=self.send(0,encode_move_request(BattleMove(identity,((actor.x,6),))))
        self.assertIn(b'\x39',replies);self.assertNotIn(1,battle['arena']._turns)
        self.hub.tick();self.assertEqual(battle['arena']._turns[1][0],owners[1])
        self.assertEqual(self.now,0)

    def test_rejected_move_restores_prediction_and_does_not_block_skip(self):
        from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
        owners,battle=self.open_battle();field=battle['field'];identity=field.actor_ids(owners[0])[0]
        actor=field.actor(identity)
        replies=self.send(0,encode_move_request(BattleMove(identity,((37,37),))))
        restore=decode_battle_move(next(p for p in replies if p[0]==0x3d))
        self.assertEqual(restore.path,((actor.x,actor.y),)*2)
        self.assertEqual(field.actor(identity),actor)
        self.assertFalse(self.hub.queues[owners[1]])
        self.assertIn(b'\x39',self.send(0,encode_end_turn()))

    def test_attack_animation_reaches_opponent_but_inventory_does_not(self):
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
        owners,battle=self.open_battle();field=battle['field']
        attacker=field.actor_ids(owners[0])[0];victim=field.actor_ids(owners[1])[0]
        field._actors[victim]=replace(field.actor(victim),x=5,y=6)
        replies=self.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        other=tuple(self.hub.queues[owners[1]])
        self.assertTrue(any(p[0]==0x30 for p in replies))
        self.assertFalse(any(p[0] in (0x30,0x80,0x82) for p in other))
        result=decode_attack_result(next(p for p in other if p[0]==0x4b))
        self.assertEqual(result.actor_id,attacker)
        self.assertEqual(result.hits[0].actor_id,victim)

    def test_subgrenade_shared_damage_and_account_local_ammunition(self):
        from test_combat import item,FixedRandom
        from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
        from tio.protocol.battle_attack import decode_attack_result
        owners,battle=self.open_battle();field=battle['field'];combat=field.combat
        attacker=field.actor_ids(owners[0])[0];victim=field.actor_ids(owners[1])[0]
        field._actors[victim]=replace(field.actor(victim),x=10,y=5,health=500,max_health=500)
        equipment=(item(901,339,equipped=True),item(902,340,2))
        combat.inventories[attacker]=encode_item_list(attacker,equipment)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',
                       (encode_item_list(1,equipment),'alice'))
            other_before=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',('bob',)).fetchone()[0]
        combat.rng=FixedRandom()
        for view in battle['views'].values():view.refresh()
        replies=self.send(0,encode_ability_cast(AbilityCast(27,attacker,0,10,5)))
        other=tuple(self.hub.queues[owners[1]])
        for packets in (replies,other):
            result=decode_attack_result(next(p for p in packets if p[0]==0x4b))
            self.assertEqual((result.weapon_id,result.skill_id),(340,27))
            hit=next(h for h in result.hits if h.actor_id==victim)
            self.assertEqual(hit.damage,500-field.actor(victim).health)
        self.assertFalse(any(p[0] in (0x30,0x80) for p in other))
        with closing(sqlite3.connect(self.path)) as db:
            saved=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',('alice',)).fetchone()[0]
            self.assertEqual(decode_item_list(saved)[0],1)
            self.assertEqual(next(i.count for i in decode_item_list(saved)[1] if i.template_id==340),1)
            self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',('bob',)).fetchone()[0],other_before)

    def test_armor_break_snapshot_and_inventory_stay_with_affected_account(self):
        from test_durability import gear,FixedRandom
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        from tio.durability import refresh_template
        from tio.protocol.battle_soldier import decode_battle_soldier
        owners,battle=self.open_battle();field=battle['field'];combat=field.combat
        attacker=field.actor_ids(owners[0])[0];victim=field.actor_ids(owners[1])[0]
        field._actors[victim]=replace(field.actor(victim),x=5,y=6)
        armor=gear(900,210,(1,300,300),4)
        combat.inventories[victim]=encode_item_list(victim,(armor,))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,(armor,)),'bob'))
        for view in battle['views'].values():refresh_template(combat,view,victim)
        combat.rng=FixedRandom()
        replies=self.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        other=tuple(self.hub.queues[owners[1]])
        self.assertEqual(decode_item_list(combat.inventories[victim])[1],())
        self.assertTrue(any(p[0]==0x30 and decode_item_list(p)[0]==victim for p in other))
        self.assertFalse(any(p[0]==0x30 and decode_item_list(p)[0]==victim for p in replies))
        self.assertFalse(any(p[0]==0x30 and decode_item_list(p)[0]==attacker for p in other))
        for packets in (replies,other):
            snapshot=next(p for p in packets if p[0]==0x3b and int.from_bytes(p[1:5],'little')==victim)
            self.assertEqual(decode_battle_soldier(snapshot,human_equipment=True).fields['0x8c531b'],0)
        self.assertEqual(decode_item_list(OwnedPetStore(self.path).inventory('bob',1))[1],())

    def test_bot_actions_reach_both_human_observers(self):
        from tio.training_bot import play_turn
        from server.battle_events import BotEventArena
        owners,battle=self.open_battle();arena=battle['arena']
        self.send(0,encode_end_turn())
        bot=next(iter(battle['bots']))
        play_turn(BotEventArena(self.hub,battle),battle['room'].room_id,bot)
        for owner in owners:
            packets=tuple(self.hub.queues[owner])
            self.assertTrue(any(p[0] in (0x3d,0x4b) for p in packets))
            self.assertFalse(any(p[0]==0x30 for p in packets))

    def test_shared_scene_unique_ids_loading_turns_and_isolated_persistence(self):
        owners,battle=self.paired();field=battle['field'];combat=field.combat
        self.assertEqual(len(field._actors),4);self.assertEqual(len(battle['bots']),2)
        self.assertEqual(len(combat.persistence),2)
        self.assertEqual(set(combat.storage_ids.values()),{1})
        self.send(0,b'\x36');self.hub.tick()
        self.assertFalse(battle['arena']._turns)
        self.send(1,b'\x36');self.hub.tick()
        self.assertEqual(battle['arena']._turns[1][0],owners[0])
        actor=field.actor_ids(owners[0])[0]
        rejected=self.send(1,encode_end_turn(actor))
        self.assertTrue(any(p[:1]==b'\xf0' for p in rejected))
        self.send(0,encode_end_turn(actor));self.hub.tick()
        self.assertEqual(battle['arena']._turns[1][0],owners[1])
        # CAS persistence addresses Alice's local actor1, never Bob's actor1.
        from tio.protocol.item_list import ItemRecord
        item=ItemRecord(22,2,bytes(2),1,0,0,(0,0,0),bytes(4),None,bytes(3))
        combat._persist_inventory(actor,combat.inventories[actor],encode_item_list(actor,(item,)))
        with closing(sqlite3.connect(self.path)) as db:
            records=dict(db.execute('SELECT account,inventory_packet FROM owned_pets WHERE pet_id=1'))
        self.assertEqual(decode_item_list(records['alice'])[0],1)
        self.assertEqual(len(decode_item_list(records['alice'])[1]),1)
        self.assertFalse(decode_item_list(records['bob'])[1])

    def test_result_saved_for_each_account_once_and_return_to_city(self):
        owners,battle=self.paired();field=battle['field']
        for identity,actor in tuple(field._actors.items()):
            if field.teams[actor.owner_id]==1:field._actors[identity]=replace(actor,health=0)
        self.hub.tick();self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(dict(db.execute('SELECT account,result FROM battle_rewards')),{'alice':1,'bob':0})
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone()[0],2)
        self.assertTrue(self.hub.busy(self.sessions[0]))
        self.send(0,b'\x2a\x01');self.assertFalse(self.hub.busy(self.sessions[0]))

    def test_reward_uses_real_attack_and_starting_opponents_after_disconnect(self):
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        from tio.battle_rewards import receipt
        from types import SimpleNamespace
        owners,battle=self.open_battle();field=battle['field']
        attacker=field.actor_ids(owners[0])[0];victim=field.actor_ids(owners[1])[0]
        field._actors[victim]=replace(field.actor(victim),x=5,y=6)
        field.combat.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a)
        self.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        self.assertIn(owners[0],battle['reward_damage'])
        self.hub.disconnect(self.sessions[1])
        self.assertTrue(field.actor_ids(owners[1]))
        self.now=self.hub.offline[owners[1]]
        self.hub.expire_reconnects()
        self.assertEqual(receipt(self.path,'bob',battle['match_id']),(0,0))
        self.hub.settle(battle,owners[0],1)
        self.assertEqual(receipt(self.path,'alice',battle['match_id']),(75,0))
        self.hub.settle(battle,owners[0],1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reward_pairs').fetchone()[0],1)

    def test_afk_winner_and_loading_departure_have_no_reward(self):
        from tio.battle_rewards import receipt
        owners,battle=self.open_battle()
        self.hub.settle(battle,owners[0],1)
        self.assertEqual(receipt(self.path,'alice',battle['match_id']),(0,0))

    def test_bot_damage_qualifies_for_discounted_arena_participation(self):
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        from types import SimpleNamespace
        owners,battle=self.open_battle();field=battle['field']
        attacker=field.actor_ids(owners[0])[0]
        bot=next(o for o in battle['bots'] if not field.allied(o,owners[0]))
        victim=field.actor_ids(bot)[0]
        field._actors[victim]=replace(field.actor(victim),x=5,y=6)
        field.combat.rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a)
        self.send(0,encode_attack_request(AttackRequest(attacker,5,6)))
        self.assertIn(owners[0],battle['reward_damage'])
        from tio.battle_rewards import receipt
        self.hub.settle(battle,owners[0],1)
        self.assertEqual(receipt(self.path,'alice',battle['match_id']),(75,0))

    def test_wall_joins_ready_and_disconnection(self):
        first=self.create(0,4);second=self.create(2,4)
        for index,room in ((1,first),(3,second)):
            self.send(index,b'\xba\x04'+room.identity.to_bytes(4,'little'))
        self.send(0,b'\x2e')
        self.assertFalse(first.searching)
        for index in (1,3):self.send(index,b'\x2c\1')
        self.send(0,b'\x2e');self.send(2,b'\x2e')
        owners=[self.hub.identities[s] for s in self.sessions]
        battle=self.hub.battles[owners[0]]
        self.assertEqual(len(battle['field']._actors),8)
        self.assertEqual(len(battle['bots']),4)
        self.hub.disconnect(self.sessions[0])
        self.assertTrue(battle['field'].actor_ids(owners[0]))
        self.now=self.hub.offline[owners[0]]
        self.hub.expire_reconnects()
        self.assertFalse(battle['field'].actor_ids(owners[0]))
        self.assertIn(owners[1],self.hub.battles)

    def test_wall_single_captains_have_three_bots_each(self):
        for index in (0,1):
            self.create(index,4);self.send(index,b'\x2e')
        owners=[self.hub.identities[s] for s in self.sessions[:2]]
        battle=self.hub.battles[owners[0]]
        self.assertIs(battle,self.hub.battles[owners[1]])
        self.assertEqual(len(battle['bots']),6)
        self.assertEqual(len(battle['field']._actors),8)

    def test_loading_timeout_returns_without_reward(self):
        owners,battle=self.paired();self.now=61;self.hub.tick()
        self.assertFalse(self.hub.battles)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='battle_rewards'").fetchone()[0],0)

    def test_survival_waits_for_human_and_uses_native_search_replies(self):
        from tio.protocol.arena import decode_member_list
        replies=self.send(0,b'\xba\x03\0\1')
        self.assertEqual(decode_member_list(replies[0])[2][0].character_id,1)
        self.now=59;self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.assertTrue(self.hub.busy(self.sessions[0]))
        self.send(1,b'\xba\x03\0\1')
        owners=[self.hub.identities[s] for s in self.sessions[:2]]
        battle=self.hub.battles[owners[0]]
        self.assertIs(battle,self.hub.battles[owners[1]])
        self.assertFalse(battle['bots']);self.assertEqual(len(battle['field']._actors),2)
        self.assertFalse(self.hub.survival_waiting)
        self.send(0,b'\x36');self.hub.tick()
        self.assertFalse(battle['arena']._turns)
        self.send(1,b'\x36');self.hub.tick()
        self.assertTrue(battle['arena']._turns)

    def test_survival_pause_cancel_and_disconnect(self):
        self.send(0,b'\xba\x03\0\1')
        replies=self.send(0,b'\xba\x07\0')
        self.assertEqual(replies[0][:2],b'\xba\x08')
        self.send(1,b'\xba\x03\0\1');self.assertFalse(self.hub.battles)
        self.send(0,b'\xba\x05\2\0\0\0\0')
        self.assertTrue(self.hub.busy(self.sessions[0]))
        self.send(0,b'\xba\x05\1\0\0\0\0')
        self.assertFalse(self.hub.busy(self.sessions[0]))
        self.hub.disconnect(self.sessions[1]);self.assertFalse(self.hub.survival_queue.tickets)

    def test_survival_trims_larger_squad_without_changing_saved_selection(self):
        s=self.sessions[0];store=OwnedPetStore(self.path)
        _,packet,inventory=store.list(s.account)[0]
        pet=decode_pet_info(packet,human_equipment=True)
        for identity in (2,3):
            extra=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':identity,'0x8c44a6':identity}))
            store.ensure(s.account,extra,encode_item_list(identity,()),human=True)
        self.send(0,b'\xba\x03\0\3');self.send(1,b'\xba\x03\0\1')
        owner=self.hub.identities[s];battle=self.hub.battles[owner]
        self.assertEqual(len(battle['field'].actor_ids(owner)),1)
        self.assertEqual(len(store.list(s.account)),3)

    def test_survival_resume_pairs_waiting_players(self):
        self.send(0,b'\xba\x03\0\1');self.send(0,b'\xba\x07\0')
        self.send(1,b'\xba\x03\0\1')
        self.assertFalse(self.hub.battles)
        self.send(0,b'\xba\x07\1')
        self.assertEqual(len(self.hub.battles),2)
        self.assertFalse(self.hub.survival_queue.tickets)

    def test_survival_scene_failure_preserves_requests(self):
        from unittest.mock import patch
        self.send(0,b'\xba\x03\0\1')
        with patch('tio.team_scene.prepare',side_effect=ValueError('scene unavailable')):
            replies=self.send(1,b'\xba\x03\0\1')
        self.assertTrue(any(p[:1]==b'\xf0' for p in replies))
        self.assertEqual(len(self.hub.survival_queue.tickets),2)
        self.assertFalse(self.hub.battles)
        self.send(1,b'\xba\x07\1')
        self.assertEqual(len(self.hub.battles),2)
