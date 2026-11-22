"""Native checkpoint requests against a real journaled hub and disposable DB.

Controlled fixture positions isolate individual handlers; these are protocol
integration tests, not graphical-client or hosted acceptance.
"""
from contextlib import closing
from dataclasses import replace
import json
import random
import sqlite3
import struct
import unittest
from unittest.mock import patch

import test_shared_team_arena as fixtures
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import battle_checkpoints
from tio.characters import CharacterStore
from tio.clans import ClansStore
from tio.crystal_market import CrystalMarket
from tio.locations import LocationStore,center
from tio.mine_claims import MineClaimsStore
from tio.mining_service import MiningService
from tio.owned_pets import OwnedPetStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_action import ItemAction,encode_item_action
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_position import BattlePositionRequest,encode_position_request
from tio.protocol.battle_loot import LootTransfer,encode_loot_transfer,decode_container


class SharedMineArenaTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.path;self.hub=self.case.hub;self.wall=1000.
        characters=CharacterStore(self.path)
        for session in self.case.sessions:
            session.probe_character_name=session.account.title().encode()
            characters.create(session.account,CharacterCreateRequest(session.probe_character_name,0,(1,0,0,0)))
            store=OwnedPetStore(self.path);identity,raw,inventory=store.list(session.account)[0]
            pet=decode_pet_info(raw,human_equipment=True)
            pet=replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':7355,
                                   '0x8c4ab1':115,'0x8c4a07':115})
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',
                           (encode_pet_info(pet),session.account,identity))
            session.locations=LocationStore(self.path)
            with closing(sqlite3.connect(self.path)) as db,db:
                session.locations._save(db,session.account,13,*center(13))
            session.mining=MiningService(self.path,session.arena,session.locations)
            self.hub.identity(session)
        clans=ClansStore(self.path);self.clan=clans.create('dave',b'Mine Guards')
        clans.invite('dave',b'Carol');clans.accept('carol',1)
        self.claim=MineClaimsStore(self.path).admin_set_claim(13,self.clan,tax_percent=10,
            expected_revision=0,actor='test:operator',reason='isolated fixture only')
        self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.wall)
        self.owners=tuple(self.hub.identities[s] for s in self.case.sessions)

    def send(self,index,packet):
        self.assertTrue(self.hub.handle(self.case.sessions[index],packet))
        owner=self.owners[index];replies=tuple(self.hub.queues[owner]);self.hub.queues[owner].clear()
        return replies

    def enter(self,indices=(0,1,2),*,load=True):
        roles=(1,2,3)
        for index in indices:
            if roles[index]==3:
                from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
                battle=self.hub.battles[self.owners[0]];actor=battle['field'].actor(battle['field'].actor_ids(self.owners[0])[0])
                self.hub.battle_action(self.owners[0],encode_ability_cast(AbilityCast(28,actor.actor_id,0,actor.x,actor.y)))
            replies=self.send(index,bytes((0xb0,0x14,roles[index])))
            self.assertIn(b'\x41',replies,replies)
        battle=self.hub.battles[self.owners[0]]
        self.loaded_packets={}
        if load:
            for index in indices:self.loaded_packets[index]=self.send(index,b'\x36')
            self.hub.tick()
        return battle

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {t:tuple(db.execute('SELECT * FROM "'+t+'"').fetchall()) for t in tables}

    def queues(self):return {o:tuple(q) for o,q in self.hub.queues.items()}

    def economic_rows(self):
        return {t:rows for t,rows in self.rows().items()
                if t not in ('battle_checkpoints','battle_checkpoint_members')}

    def restore(self):
        hub=TeamArena(clock=lambda:self.case.now)
        hub.journal=BattleJournal(hub,self.path,wall=lambda:self.wall)
        self.assertTrue(hub.journal.recover())
        return hub

    def park_mutants(self,battle,*,away=(10,10)):
        """Keep ordinary mutant HP/stats; controlled distant geometry only."""
        from tio.mining_ai import configure_patrols
        field=battle['field'];field.blocked=frozenset();field.transparent_obstacles=frozenset()
        field.doors.solid=frozenset()
        x,y=(48 if away[0]<30 else 4,48 if away[1]<30 else 4)
        for n,identity in enumerate(field.actor_ids(next(iter(battle['bots'])))):
            a=field.actor(identity);field._actors[identity]=replace(a,x=x+n%5,y=y+n//5)
        configure_patrols(field,field.actor_ids(next(iter(battle['bots']))),radius=6)

    def carry_at_exit(self,battle,index,amount):
        field=battle['field'];owner=self.owners[index];identity=field.actor_ids(owner)[0]
        mine=field.mining;exits=mine.layout.raider_exits if mine.roles[owner]==2 else mine.layout.lift
        occupied={(a.x,a.y) for a in field._actors.values() if a.actor_id!=identity and a.health}
        position=next(p for p in sorted(exits) if p not in occupied)
        with self.hub.journal.unit(battle):
            field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1])
            drill=next(iter(field.loot.boxes.values()))[0]
            items=tuple(i for i in decode_item_list(field.combat.inventories[identity])[1] if i.template_id!=52)
            field.combat.inventories[identity]=encode_item_list(identity,(*items,replace(drill,unknown_u32_01=amount)))
        return identity

    def advance_round(self,battle,target):
        for _ in range(80):
            if battle['field'].mining.round>=target:return
            turn=battle['arena']._turns.get(battle['room'].room_id)
            if turn and turn[0] in self.owners:
                self.case.now+=1.01 # A distinct intentional turn, outside native repeat suppression.
                self.send(self.owners.index(turn[0]),encode_end_turn())
            self.hub.tick()
            self.assertFalse(battle.get('faulted'))
        self.fail('Round did not advance')

    def move_to_exit(self,battle,index):
        field=battle['field'];owner=self.owners[index];identity=field.actor_ids(owner)[0]
        mine=field.mining;exits=mine.layout.raider_exits if mine.roles[owner]==2 else mine.layout.lift
        occupied={(a.x,a.y) for a in field._actors.values() if a.actor_id!=identity and a.health}
        x,y=next(p for p in sorted(exits) if p not in occupied)
        with self.hub.journal.unit(battle):
            field._actors[identity]=replace(field.actor(identity),x=x,y=y)
        return identity

    def extract_at_map_exit(self, battle, index):
        owner = self.owners[index]
        with self.hub.journal.unit(battle):
            self.hub.battle_action(owner, b'\x2a\x01')
        replies = tuple(self.hub.queues[owner])
        self.hub.queues[owner].clear()
        return replies

    def assert_scene_actor_bootstrap(self,battle,index,packets):
        """A native scene must register live models before its ready marker."""
        from tio.protocol.battle_soldier import decode_battle_soldier
        field=battle['field'];owner=self.owners[index]
        ready=packets.index(b'\x41');ground=packets.index(battle['ground'])
        soldiers={}
        for offset,packet in enumerate(packets):
            if packet[:1]!=b'\x3b':continue
            self.assertLess(ground,offset);self.assertLess(offset,ready)
            soldier=decode_battle_soldier(packet,human_equipment=True)
            self.assertNotIn(soldier.soldier_id,soldiers)
            soldiers[soldier.soldier_id]=soldier
        self.assertEqual(set(soldiers),set(field._actors))
        self.assertEqual({s.owner_id for s in soldiers.values()},set(battle['room'].members))
        for identity,soldier in soldiers.items():
            actor=field.actor(identity)
            self.assertGreater(soldier.fields['0x8c57bb'],0)
            if actor.owner_id==owner:
                self.assertEqual(soldier.position,(actor.x,actor.y))
                self.assertEqual(soldier.fields['0x8c57bb'],actor.health)
            elif soldier.position==(255,255):
                # Hidden opponents remain alive in the native owner predicate
                # without disclosing their current position or health.
                self.assertEqual(soldier.fields['0x8c57bb'],1)
        self.assertTrue(any(s.position==(255,255) for s in soldiers.values()))

    def test_founder_scene_registers_live_squad_and_mutants_before_ready(self):
        replies=self.send(0,b'\xb0\x14\x01')
        battle=self.hub.battles[self.owners[0]]
        self.assert_scene_actor_bootstrap(battle,0,replies)
        self.send(0,b'\x36');self.hub.tick()
        room=battle['room'].room_id;turn=battle['arena']._turns[room]
        self.assertEqual(turn[0],self.owners[0])
        self.assertEqual(set(turn[1]),set(battle['field'].living_actor_ids(self.owners[0])))
        for _ in range(8):self.hub.tick()
        self.assertEqual(battle['arena']._turns[room],turn)
        self.assertEqual(battle['field'].mining.round,0)

    def test_joining_raider_and_escort_receive_complete_scene_actor_bootstrap(self):
        battle=self.enter((0,),load=False)
        replies=self.send(1,b'\xb0\x14\x02')
        self.assert_scene_actor_bootstrap(battle,1,replies)
        from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
        actor=battle['field'].actor(battle['field'].actor_ids(self.owners[0])[0])
        self.hub.battle_action(self.owners[0],encode_ability_cast(AbilityCast(28,actor.actor_id,0,actor.x,actor.y)))
        replies=self.send(2,b'\xb0\x14\x03')
        self.assert_scene_actor_bootstrap(battle,2,replies)

    def test_joining_escort_receives_visible_open_drill_crate_state(self):
        from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
        from tio.protocol.battle_loot import encode_open_container_state
        battle=self.enter((0,));field=battle['field']
        identity=field.actor_ids(self.owners[0])[0];x,y=next(iter(field.loot.boxes))
        actor=field.actor(identity)
        self.hub.battle_action(self.owners[0],encode_ability_cast(AbilityCast(28,identity,0,actor.x,actor.y)))
        with self.hub.journal.unit(battle):
            self.park_mutants(battle)
            field._actors[identity]=replace(field.actor(identity),x=x-1,y=y)
        opened=self.send(0,encode_position_request(BattlePositionRequest(identity,x,y)))
        state=encode_open_container_state(x,y)
        self.assertIn(state,opened)
        replies=self.send(2,b'\xb0\x14\x03')
        self.assertIn(state,replies)
        self.assertLess(replies.index(state),replies.index(b'\x41'))

    def test_founder_reconnect_replays_live_models_and_preserves_active_turn(self):
        battle=self.enter((0,));room=battle['room'].room_id
        turn=battle['arena']._turns[room]
        self.assertTrue(self.hub.disconnect(self.case.sessions[0]))
        self.assertTrue(self.hub.resume(self.case.sessions[0]))
        replies=tuple(self.hub.queues[self.owners[0]])
        self.assert_scene_actor_bootstrap(battle,0,replies)
        self.send(0,b'\x36');self.hub.tick()
        self.assertEqual(battle['arena']._turns[room],turn)
        self.assertEqual(battle['field'].mining.round,0)

    def test_native_crate_install_pickup_produces_only_after_all_squads_and_mutants_finish(self):
        battle=self.enter();field=battle['field'];identity=field.actor_ids(self.owners[0])[0]
        x,y=next(iter(field.loot.boxes));drill=field.loot.boxes[x,y][0]
        deposit=next(iter(field.mining.deposits.values()))
        with self.hub.journal.unit(battle):
            self.park_mutants(battle,away=deposit.position)
            field._actors[identity]=replace(field.actor(identity),x=x-1,y=y)
        opened=self.send(0,encode_position_request(BattlePositionRequest(identity,x,y)))
        container=decode_container(next(p for p in opened if p[0]==0x47))
        self.assertEqual(container[3][0].instance_id,drill.instance_id)
        taken=self.send(0,encode_loot_transfer(LootTransfer(identity,x,y,(),((drill.instance_id,0),))))
        self.assertTrue(any(p[0]==0x30 for p in taken))
        with self.hub.journal.unit(battle):
            field._actors[identity]=replace(field.actor(identity),x=deposit.position[0],y=deposit.position[1])
        installed=self.send(0,encode_item_action(ItemAction(identity,drill.instance_id,255)))
        self.assertTrue(any(p[:2]==b'\xb0\x16' for p in installed))
        self.assertEqual((field.mining.round,deposit.extracted),(0,0))
        self.hub.tick();self.hub.tick()
        self.assertEqual((field.mining.round,deposit.extracted),(0,0))
        for index in (0,1):
            self.send(index,encode_end_turn());self.hub.tick()
            self.assertEqual((battle['field'].mining.round,battle['field'].mining.deposits[deposit.position].extracted),(0,0))
        self.send(2,encode_end_turn());self.hub.tick()
        self.assertEqual(battle['field'].mining.round,0) # The mutant turn has just ended.
        self.advance_round(battle,1)
        field=battle['field'];deposit=field.mining.deposits[deposit.position]
        self.assertEqual(deposit.extracted,field.mining.total//10)
        pickup=b'\xb0\x15'+struct.pack('<IBBI',identity,*deposit.position,50)
        wrong=self.send(1,pickup)
        self.assertTrue(any(p[0]==0xf0 for p in wrong))
        self.assertIsNotNone(battle['field'].mining.deposits[deposit.position].drill)
        before=battle['field'].actor(identity).action_points
        lifted=self.send(0,pickup);field=battle['field']
        self.assertTrue(any(p[0]==0x30 for p in lifted),lifted)
        self.assertIsNone(field.mining.deposits[deposit.position].drill)
        self.assertEqual(field.actor(identity).action_points,before-1)
        self.assertEqual(next(i for i in decode_item_list(field.combat.inventories[identity])[1]
                              if i.template_id==52).count,50)
        self.assertFalse(any(i.template_id==52 for _,_,raw in OwnedPetStore(self.path).list('alice')
                             for i in decode_item_list(raw)[1]))

    def test_native_three_roles_join_same_persisted_scene_with_private_character_ids(self):
        first=self.enter((0,),load=False);ground=first['ground'];match=first['match_id']
        from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
        actor=first['field'].actor(first['field'].actor_ids(self.owners[0])[0])
        self.hub.battle_action(self.owners[0],encode_ability_cast(AbilityCast(28,actor.actor_id,0,actor.x,actor.y)))
        for index in (1,2):self.send(index,bytes((0xb0,0x14,index+1)))
        field=first['field']
        for index in (0,1,2):
            owner=self.owners[index];self.assertIs(self.hub.battles[owner],first)
            self.assertEqual(self.case.sessions[index].probe_character_id,1)
            self.assertEqual(field.combat.storage_ids[field.actor_ids(owner)[0]],1)
            self.assertFalse(field.allied(owner,next(iter(first['bots']))))
        self.assertEqual((first['ground'],first['match_id']),(ground,match))
        self.assertEqual(len(field._actors),13)
        self.assertEqual(len(battle_checkpoints.read(self.path)),1)
        self.assertTrue(field.allied(self.owners[0],self.owners[2]))
        self.assertFalse(field.allied(self.owners[0],self.owners[1]))
        self.assertEqual(field.mining.roles,{self.owners[0]:1,self.owners[1]:2,self.owners[2]:3})

    def test_full_round_clock_and_repeated_entry_do_not_reduce_lift_wait(self):
        battle=self.enter();field=battle['field'];mine=field.mining
        with self.hub.journal.unit(battle):self.park_mutants(battle)
        self.assertEqual(mine.round,0);deadline=mine.lift_blocked_until
        self.assertEqual(deadline,5)
        self.assertFalse(self.hub.mine_can_quit(battle,self.owners[0]))
        for index in (0,1,2):self.send(index,bytes((0xb0,0x14,index+1)))
        self.assertEqual((mine.round,mine.lift_blocked_until),(0,deadline))
        self.carry_at_exit(battle,0,100)
        self.assertTrue(any(p[:1]==b'\xf0' for p in self.send(0,b'\x2a\1')))
        self.assertIs(self.hub.battles[self.owners[0]],battle)
        self.advance_round(battle,deadline)
        self.assertEqual(battle['field'].mining.round,deadline)
        self.assertTrue(self.hub.mine_can_quit(battle,self.owners[0]))
        self.extract_at_map_exit(battle,0)
        self.assertIn(self.owners[0],self.hub.results)
        self.assertTrue(battle['finished'])
        self.assertTrue(set(self.owners[:3])<=self.hub.results)

    def test_miner_exit_finishes_all_accounts_and_crash_replays_saved_results(self):
        battle=self.enter();field=battle['field'];mine=field.mining
        with self.hub.journal.unit(battle):self.park_mutants(battle)
        self.advance_round(battle,mine.lift_blocked_until)
        identity=self.carry_at_exit(battle,0,101)
        result=self.extract_at_map_exit(battle,0)
        self.assertTrue(any(p[:1]==b'\x4c' for p in result))
        self.assertNotIn(identity,battle['field']._actors)
        self.assertEqual((CrystalMarket(self.path).balance('alice'),CrystalMarket(self.path).balance('carol')),(50,41))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT amount FROM clan_crystals WHERE clan_id=?',(self.clan,)).fetchone(),(10,))
        receipts=self.economic_rows();clone=self.restore()
        fresh=clone.completed[self.owners[1]]
        self.assertFalse(fresh.get('faulted'))
        self.assertIs(fresh,clone.completed[self.owners[2]])
        self.assertEqual((fresh['match_id'],fresh['ground']),(battle['match_id'],battle['ground']))
        self.assertTrue(clone.resume(self.case.sessions[0]))
        self.assertIn(b'\x41',clone.queues[self.owners[0]])
        self.assertTrue(clone.handle(self.case.sessions[0],b'\x36'))
        self.assertEqual(fresh['result_packets'][self.owners[0]],battle['result_packets'][self.owners[0]])
        self.assertEqual(self.economic_rows(),receipts)

    def prepare_contact(self,battle):
        field=battle['field']
        with self.hub.journal.unit(battle):
            self.park_mutants(battle)
            for index,position in ((0,(10,10)),(1,(11,10)),(2,(10,12))):
                identity=field.actor_ids(self.owners[index])[0]
                field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1])
            field.combat.rng=random.Random(1)
            self.hub.snapshot(battle)
        for queue in self.hub.queues.values():queue.clear()
        return tuple(field.actor_ids(owner)[0] for owner in self.owners[:3])

    def test_turn_authority_damage_fog_and_active_crash_reconnect_keep_hp_xp_ids(self):
        battle=self.enter();field=battle['field'];ids=self.prepare_contact(battle)
        old=field.actor(ids[1])
        rejected=self.send(1,encode_attack_request(AttackRequest(ids[1],10,10)))
        self.assertTrue(any(p[:1]==b'\xf0' for p in rejected))
        field=battle['field'] # A rejected journaled request restores a new graph.
        self.assertEqual(field.actor(ids[1]),old)
        result=self.send(0,encode_attack_request(AttackRequest(ids[0],11,10)))
        self.assertTrue(any(p[:1]==b'\x4b' for p in result))
        self.assertLess(field.actor(ids[1]).health,115)
        self.assertGreater(field.combat.experience.totals[ids[0]],0)
        state=(field.actor(ids[0]),field.actor(ids[1]),dict(field.combat.experience.totals),field.mining.round,field.mining.lift_blocked_until)
        clone=self.restore();fresh=clone.battles[self.owners[0]]
        self.assertEqual((fresh['field'].actor(ids[0]),fresh['field'].actor(ids[1]),
                          dict(fresh['field'].combat.experience.totals),fresh['field'].mining.round,
                          fresh['field'].mining.lift_blocked_until),state)
        for index in (0,1,2):
            self.assertTrue(clone.resume(self.case.sessions[index]))
            self.assertTrue(clone.handle(self.case.sessions[index],b'\x36'))
        self.assertEqual(fresh['field'].actor_ids(self.owners[0]),(ids[0],))
        self.assertEqual(fresh['field'].actor(ids[0]).action_points,state[0].action_points)
        # Another living owner's distant model is masked, not an HP disclosure.
        with clone.journal.unit(fresh):
            a=fresh['field'].actor(ids[1]);fresh['field']._actors[ids[1]]=replace(a,x=30,y=30)
            clone.snapshot(fresh)
        self.assertNotIn(ids[1],fresh['views'][self.owners[0]].visible)

    def test_raider_extraction_finishes_shared_mission_without_escort_payments(self):
        battle=self.enter();field=battle['field']
        with self.hub.journal.unit(battle):self.park_mutants(battle)
        self.advance_round(battle,5)
        self.carry_at_exit(battle,1,101)
        self.extract_at_map_exit(battle,1)
        self.assertEqual(CrystalMarket(self.path).balance('bob'),101)
        self.assertTrue(battle['finished'])
        self.assertNotIn(self.owners[0],self.hub.battles)
        self.assertNotIn(self.owners[2],self.hub.battles)
        self.assertEqual((CrystalMarket(self.path).balance('alice'),CrystalMarket(self.path).balance('carol')),(0,0))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT gross,tax FROM mine_crystal_extractions ORDER BY extractor').fetchall(),[(0,0),(101,0),(0,0)])

    def test_interior_exit_with_carried_crystals_is_rejected(self):
        battle=self.enter();field=battle['field'];identity=field.actor_ids(self.owners[1])[0]
        mine=field.mining;position=next(p for p in mine.deposits if p not in mine.layout.raider_exits)
        with self.hub.journal.unit(battle):
            field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1])
            drill=next(iter(field.loot.boxes.values()))[0]
            field.combat.inventories[identity]=encode_item_list(identity,(replace(drill,unknown_u32_01=100),))
        replies=self.send(1,b'\x2a\1')
        self.assertTrue(any(p[:2]==b'\xf0\x8a' for p in replies))
        self.assertEqual(CrystalMarket(self.path).balance('bob'),0)
        self.assertNotIn(self.owners[1],self.hub.results)
        self.assertIs(self.hub.battles[self.owners[1]],battle)
        self.assertIs(self.hub.battles[self.owners[0]],battle)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute('SELECT gross,tax FROM mine_crystal_extractions WHERE extractor=?',('bob',)).fetchone())

    def test_menu_requires_drill_and_empty_drill_loses_for_each_role(self):
        battle=self.enter()
        with self.hub.journal.unit(battle):self.park_mutants(battle)
        self.advance_round(battle,5)
        for index in (1,0,2):
            self.move_to_exit(battle,index)
            rejected=self.send(index,b'\x2a\x01')
            self.assertTrue(any(p[0]==0xf0 for p in rejected))
            self.assertNotIn(self.owners[index],self.hub.results)
            self.carry_at_exit(battle,index,0)
            result=self.extract_at_map_exit(battle,index)
            summary=next(p for p in result if p[0]==0x4c)
            self.assertEqual(summary[3],0)
            self.assertEqual(CrystalMarket(self.path).balance(self.case.sessions[index].account),0)
        self.assertTrue(battle['finished'])

    def test_positive_miner_pays_escort_before_both_return_to_city(self):
        from tio.protocol.asset_count import decode_asset_count
        battle=self.enter()
        with self.hub.journal.unit(battle):self.park_mutants(battle)
        self.advance_round(battle,5)
        self.carry_at_exit(battle,0,101);self.extract_at_map_exit(battle,0)
        self.send(0,b'\x2a\1') # Ordinary result acknowledgement and city return.
        self.assertNotIn(self.owners[0],self.hub.battles)
        self.assertNotIn(self.owners[0],self.hub.completed)
        refresh=next(p for p in self.hub.queues[self.owners[2]] if p[:2]==b'\xc8\x39')
        self.assertEqual(decode_asset_count(refresh).spectra_crystals,41)
        self.assertEqual(CrystalMarket(self.path).balance('alice'),50)
        self.assertEqual(CrystalMarket(self.path).balance('carol'),41)
        self.assertTrue(battle['finished'])

    def test_escort_without_drill_wins_only_after_paired_miner_positive_extraction(self):
        battle=self.enter()
        with self.hub.journal.unit(battle):self.park_mutants(battle)
        self.advance_round(battle,5)
        self.carry_at_exit(battle,0,101);self.extract_at_map_exit(battle,0)
        result=tuple(self.hub.queues[self.owners[2]])
        self.assertEqual(next(p for p in result if p[0]==0x4c)[3],1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT gross FROM mine_crystal_extractions WHERE extractor='carol'").fetchone(),(0,))

    def test_dead_mutants_do_not_finish_mine_or_revive_after_join_and_crash(self):
        battle=self.enter((0,),load=False);field=battle['field']
        mobs=field.actor_ids(next(iter(battle['bots'])))
        with self.hub.journal.unit(battle):
            for identity in mobs:field._actors[identity]=replace(field.actor(identity),health=0)
        for index in (1,2):self.send(index,bytes((0xb0,0x14,index+1)))
        for index in (0,1,2):self.send(index,b'\x36')
        self.hub.tick()
        self.assertFalse(battle['finished']);self.assertNotIn(self.owners[0],self.hub.results)
        self.assertEqual(field.actor_ids(next(iter(battle['bots']))),mobs)
        self.assertTrue(all(field.actor(i).health==0 for i in mobs))
        clone=self.restore();fresh=clone.battles[self.owners[0]]
        self.assertEqual(fresh['field'].actor_ids(next(iter(fresh['bots']))),mobs)
        self.assertTrue(all(fresh['field'].actor(i).health==0 for i in mobs))
        self.assertFalse(fresh['finished'])

    def test_disconnect_reconnect_cannot_reset_raider_lift_deadline_or_actor_ids(self):
        battle=self.enter();field=battle['field']
        identities=tuple(field.actor_ids(owner) for owner in self.owners[:3])
        deadline=field.mining.lift_blocked_until
        self.assertTrue(self.hub.disconnect(self.case.sessions[0]))
        self.assertIs(self.hub.battles[self.owners[0]],battle)
        self.assertTrue(self.hub.resume(self.case.sessions[0]))
        self.assertIn(b'\xb2\x0a\1',self.hub.queues[self.owners[0]])
        self.assertIn(b'\xb2\x16\0',self.hub.queues[self.owners[0]])
        self.send(0,b'\x36');self.send(0,b'\xb0\x14\1')
        self.assertEqual((battle['field'].mining.round,battle['field'].mining.lift_blocked_until),(0,deadline))
        self.assertEqual(tuple(battle['field'].actor_ids(owner) for owner in self.owners[:3]),identities)
        self.carry_at_exit(battle,0,50)
        self.assertTrue(any(p[0]==0xf0 for p in self.send(0,b'\x2a\1')))
        self.assertNotIn(self.owners[0],self.hub.results)

    def test_real_damage_persists_hp_xp_and_global_native_result_records_on_crash_replay(self):
        from tio.protocol.battle_soldier import decode_battle_soldier
        battle=self.enter();ids=self.prepare_contact(battle)
        self.send(0,encode_attack_request(AttackRequest(ids[0],11,10)))
        self.send(0,encode_end_turn());self.hub.tick()
        self.send(1,encode_attack_request(AttackRequest(ids[1],10,10)))
        field=battle['field'];health=field.actor(ids[0]).health
        self.assertLess(health,115);gain=field.combat.experience.totals[ids[0]]
        self.assertGreater(gain,0)
        # Projection never sends another owner's private inventory30.
        for index in (1,2):
            inventories=[decode_item_list(p)[0] for p in self.hub.queues[self.owners[index]] if p[0]==0x30]
            self.assertTrue(all(i in field.actor_ids(self.owners[index]) for i in inventories))
        self.advance_round(battle,5);self.carry_at_exit(battle,0,101)
        replies=self.extract_at_map_exit(battle,0);summary=next(p for p in replies if p[0]==0x4c)
        self.assertEqual(summary[28],1)
        self.assertEqual(struct.unpack_from('<II',summary,29),(ids[0],gain))
        updates=[p for p in replies if p[0]==0x4e and int.from_bytes(p[1:5],'little')==ids[0]
                 and p[9:13]==struct.pack('<I',2)]
        self.assertEqual(len(updates),1);self.assertEqual(int.from_bytes(updates[0][13:17],'little'),7355+gain)
        soldiers=[decode_battle_soldier(p,human_equipment=True) for p in replies if p[0]==0x3b]
        own=next(s for s in soldiers if s.soldier_id==ids[0])
        self.assertEqual(own.fields['0x8c514b'],7355+gain)
        pet=decode_pet_info(OwnedPetStore(self.path).list('alice')[0][1],human_equipment=True)
        self.assertEqual((pet.fields['0x8c4b05'],pet.fields['0x8c4ab1']),(7355+gain,health))
        paid=self.economic_rows();clone=self.restore()
        self.assertTrue(clone.resume(self.case.sessions[0]))
        self.assertTrue(clone.handle(self.case.sessions[0],b'\x36'))
        self.assertIn(summary,clone.queues[self.owners[0]])
        self.assertEqual(self.economic_rows(),paid)
        self.assertEqual(clone.completed[self.owners[0]]['mine_retired'][self.owners[0]][ids[0]].health,health)

    def test_dead_miner_is_settled_under_outer_journal_even_during_another_active_turn(self):
        battle=self.enter();field=battle['field'];identity=field.actor_ids(self.owners[0])[0]
        with self.hub.journal.unit(battle):
            self.park_mutants(battle)
            field._actors[identity]=replace(field.actor(identity),health=0)
        self.hub.tick()
        self.assertIn(self.owners[0],self.hub.results)
        self.assertIs(self.hub.battles[self.owners[1]],battle)
        self.assertEqual(next(p for p in self.hub.queues[self.owners[0]] if p[0]==0x4c)[3],0)
        clone=self.restore()
        self.assertNotIn(self.owners[0],clone.battles)
        self.assertIn(self.owners[0],clone.completed)
        self.assertFalse(clone.battles[self.owners[1]].get('faulted'))

    def test_checkpoint_failure_after_real_attack_restores_hp_ap_xp_and_replies(self):
        battle=self.enter();ids=self.prepare_contact(battle)
        before=self.rows();queues=self.queues();actors=dict(battle['field']._actors)
        save=battle_checkpoints.save
        def fail(*args,**kw):save(*args,**kw);raise RuntimeError('Injected action checkpoint failure')
        with patch('server.battle_journal.store.save',side_effect=fail),self.assertRaises(RuntimeError):
            self.hub.battle_action(self.owners[0],encode_attack_request(AttackRequest(ids[0],11,10)))
        self.assertEqual(self.rows(),before);self.assertEqual(self.queues(),queues)
        self.assertEqual(dict(battle['field']._actors),actors)
        self.assertFalse(battle['field'].combat.experience.totals)

    def test_settlement_failure_after_tax_write_rolls_back_all_and_retries_once(self):
        from server.battle_failures import BattleSettlementError
        battle=self.enter();field=battle['field']
        with self.hub.journal.unit(battle):self.park_mutants(battle)
        self.advance_round(battle,field.mining.lift_blocked_until)
        self.carry_at_exit(battle,0,101)
        before=self.rows();queues=self.queues();settle=CrystalMarket.settle_mine
        def fail(*args,**kw):settle(*args,**kw);raise RuntimeError('Injected after crystal/tax writes')
        with patch.object(CrystalMarket,'settle_mine',side_effect=fail),self.assertRaises(BattleSettlementError):
            self.extract_at_map_exit(battle,0)
        self.assertEqual(self.rows(),before);self.assertEqual(self.queues(),queues)
        self.assertNotIn(self.owners[0],battle['field'].mining.exited)
        self.assertIs(self.hub.battles[self.owners[0]],battle)
        self.extract_at_map_exit(battle,0);paid=self.economic_rows()
        self.send(0,b'\x36')
        self.assertEqual(self.economic_rows(),paid)
        self.assertEqual((CrystalMarket(self.path).balance('alice'),CrystalMarket(self.path).balance('carol')),(50,41))

    def test_birth_checkpoint_failure_publishes_nothing_and_rolls_back_database(self):
        before=self.rows();queues=self.queues()
        save=battle_checkpoints.save
        def fail(*args,**kw):save(*args,**kw);raise RuntimeError('Injected birth checkpoint failure')
        with patch('server.battle_journal.store.save',side_effect=fail),self.assertRaises(RuntimeError):
            self.send(0,b'\xb0\x14\1')
        self.assertEqual(self.rows(),before);self.assertEqual(self.queues(),queues)
        self.assertFalse(self.hub.battles);self.assertFalse(self.hub.account_owners)

    def test_four_accounts_fifo_help_second_raider_and_one_shared_result(self):
        from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
        from tio.protocol.mine_requests import decode_queue_change
        self.send(2,b'\xb0\x14\3')
        self.send(1,b'\xb0\x14\2')
        self.send(3,b'\xb0\x14\2')
        self.assertEqual(set(self.hub.mine_requests),set(self.owners[1:]))
        battle=self.enter((0,),load=False)
        self.assertIn(self.owners[1],battle['humans'])
        self.assertNotIn(self.owners[2],battle['humans'])
        self.assertNotIn(self.owners[3],battle['humans'])
        for index in (0,1):
            actor=battle['field'].actor(battle['field'].actor_ids(self.owners[index])[0])
            self.send(index,encode_ability_cast(AbilityCast(28,actor.actor_id,0,actor.x,actor.y)))
        self.hub.tick()
        self.assertEqual(battle['humans'],set(self.owners))
        self.assertFalse(self.hub.mine_requests)
        self.assertEqual(sorted(battle['field'].mining.roles.values()),[1,2,2,3])
        self.assertEqual(battle['mine_raiders'][self.owners[1]],('bob','dave'))
        for index in range(4):
            self.assertIs(self.hub.battles[self.owners[index]],battle)
            self.send(index,b'\x36')
        self.hub.tick();self.park_mutants(battle)
        self.advance_round(battle,5)
        self.carry_at_exit(battle,1,101)
        self.extract_at_map_exit(battle,1)
        self.assertTrue(battle['finished'])
        self.assertEqual(set(self.hub.completed),set(self.owners))
        self.assertEqual((CrystalMarket(self.path).balance('bob'),CrystalMarket(self.path).balance('dave')),(50,51))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mine_round_missions').fetchone()[0],1)
        saved=self.economic_rows()
        for index in range(4):self.send(index,b'\x36')
        self.assertEqual(self.economic_rows(),saved)

    def test_live_join_checkpoint_failure_preserves_original_scene_and_lift(self):
        battle=self.enter((0,),load=False);before=self.rows();queues=self.queues()
        ids=set(battle['field']._actors);save=battle_checkpoints.save
        def fail(*args,**kw):save(*args,**kw);raise RuntimeError('Injected join checkpoint failure')
        with patch('server.battle_journal.store.save',side_effect=fail),self.assertRaises(RuntimeError):
            self.send(1,b'\xb0\x14\2')
        self.assertEqual(self.rows(),before)
        self.assertTrue(self.hub.mine_waiting(self.owners[1]))
        self.assertTrue(any(p[:2]==b'\xb0\x18' for p in self.hub.queues[self.owners[1]]))
        self.assertTrue(all(tuple(self.hub.queues[o])==q for o,q in queues.items() if o!=self.owners[1]))
        self.assertEqual(set(battle['field']._actors),ids)
        self.assertEqual(battle['field'].mining.roles,{self.owners[0]:1})
        self.assertEqual(battle['field'].mining.lift_blocked_until,0)
        self.assertNotIn(self.owners[1],self.hub.battles)

    def make_slash_miner(self,index):
        """Saved miner with an equipped Freak Hammer and learned slash rank1."""
        from tio.ability_learning import AbilityLearning
        from tio.protocol.abilities import AbilityEntry
        from tio.protocol.item_list import ItemRecord
        session=self.case.sessions[index]
        identity,raw,_=OwnedPetStore(self.path).list(session.account)[0]
        pet=decode_pet_info(raw,human_equipment=True)
        hammer=ItemRecord(9001,335,bytes(2),1,1,16,(600,600,600),bytes(4),None,bytes(3))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=?',
                       (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c446f':6})),
                        encode_item_list(identity,(hammer,)),session.account,identity))
        AbilityLearning.from_workspace(self.path,fixtures.ROOT).state.replace(
            session.account,identity,(AbilityEntry(22,1,0,1),),expected_revision=0)

    def test_skill_bar_request_lists_own_battle_skills_and_slash_is_usable(self):
        from tio.protocol.abilities import AbilityEntry,decode_abilities,encode_skill_list_request
        from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
        self.make_slash_miner(0)
        battle=self.enter((0,1));field=battle['field']
        miner,raider=(field.actor_ids(self.owners[i])[0] for i in (0,1))
        def skills(hub,index,actor):
            hub.queues[self.owners[index]].clear()
            self.assertTrue(hub.handle(self.case.sessions[index],encode_skill_list_request(actor)))
            replies=tuple(hub.queues[self.owners[index]]);hub.queues[self.owners[index]].clear()
            self.assertEqual([p[:1] for p in replies if p[:1]!=b'\x80'],[])
            return [decode_abilities(p)[:2] for p in replies]
        # The native client requests this list on battle entry to draw its bar.
        # Mine radio28 stays a mine feature and never appears as a bar skill.
        self.assertEqual(skills(self.hub,0,miner),[(miner,(AbilityEntry(22,1,0,1),))])
        self.assertEqual(skills(self.hub,1,raider),[(raider,())])
        # Another account's fighter is neither disclosed nor rejected.
        self.assertEqual(skills(self.hub,0,raider),[])
        with self.hub.journal.unit(battle):
            self.park_mutants(battle)
            field._actors[raider]=replace(field.actor(raider),x=30,y=30)
            field._actors[miner]=replace(field.actor(miner),x=10,y=10)
            mutant=field.actor_ids(next(iter(battle['bots'])))[0]
            field._actors[mutant]=replace(field.actor(mutant),x=11,y=10)
            field.combat.rng=random.Random(1)
            self.hub.snapshot(battle)
        for queue in self.hub.queues.values():queue.clear()
        turn=battle['arena']._turns[battle['room'].room_id]
        self.assertEqual((turn[0],turn[1]),(self.owners[0],frozenset({miner})))
        points=field.actor(miner).action_points
        result=self.send(0,encode_ability_cast(AbilityCast(22,miner,0,11,10)))
        self.assertTrue(any(p[:1]==b'\x4b' and struct.unpack_from('<I',p,23)[0]==22 for p in result),result)
        self.assertEqual(field.actor(miner).action_points,points-7)
        self.assertLess(field.actor(mutant).health,field.actor(mutant).max_health)
        # A crash-restored hub answers while the client is still reloading.
        clone=self.restore()
        self.assertTrue(clone.resume(self.case.sessions[0]))
        self.assertIn(self.owners[0],clone.returning)
        clone.queues[self.owners[0]].clear()
        self.assertEqual(skills(clone,0,miner),[(miner,(AbilityEntry(22,1,0,1),))])

if __name__=='__main__':unittest.main()
