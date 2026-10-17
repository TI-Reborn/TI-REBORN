"""One authoritative mine: live squads, per-owner fog/exits and round locks."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from pathlib import Path

import test_mining as mining_fixture
from tio import battle_snapshot
from tio.matchmaking import SurvivalQueue
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.item_action import ItemAction
from tio.protocol.battle_soldier import decode_battle_soldier
from tools.mining_scene import prepare_shared_mining,append_mining_owner


class SharedMiningStateTests(unittest.TestCase):
    def setUp(self):
        self.fixture=mining_fixture.MiningTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.path=self.fixture.path
        from tio.abilities import AbilityCatalog,AbilityLevel
        import json
        self.catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in
            json.loads((mining_fixture.ROOT/'config/abilities.json').read_text())['records'])
        self.accounts=('probe_user','shared_raider','shared_defender','later_miner')
        self.owners=(42,43,44,45)
        store=OwnedPetStore(self.path)
        for account in self.accounts[1:]:
            for _,packet,inventory in store.list(self.accounts[0]):
                store.ensure(account,packet,inventory,human=True)
        self.tickets=tuple(SurvivalQueue().join(owner,store.list(account))
                           for account,owner in zip(self.accounts,self.owners))

    def prepare(self,indices=(0,1,2)):
        roles=(1,2,3,1)
        return prepare_shared_mining(self.path,
            tuple((self.accounts[i],self.tickets[i],roles[i]) for i in indices),self.catalog,seed=4)

    def test_birth_reserves_all_role_entries_including_previously_blocked_seed256(self):
        from tio.mine_map import generate,spawn_positions
        text=(mining_fixture.ROOT/'config/mine_maps.json').read_text()
        # Reproduce the old all-three-passage obstruction with the private
        # layout, then prove birth-only shared placement reserves nine slots.
        with patch.object(Path,'read_text',return_value=text):
            private=generate(256)
            occupied=set(private.arena.bot_spawns)
            occupied.update(spawn_positions(private,1,1,occupied=occupied,mutants=private.arena.bot_spawns))
            with self.assertRaises(ValueError):
                spawn_positions(private,2,1,occupied=occupied,mutants=private.arena.bot_spawns)
            for seed in (*range(200),256,257,999):
                layout=generate(seed,shared=True);baseline=generate(seed)
                self.assertEqual((layout.resource,layout.deposits,layout.arena.ground,layout.arena.blocked),
                                 (baseline.resource,baseline.deposits,baseline.arena.ground,baseline.arena.blocked))
                self.assertEqual(len(set(layout.arena.bot_spawns)),10)
                occupied=set(layout.arena.bot_spawns)
                for role in (1,2,3):
                    cells=spawn_positions(layout,role,3,occupied=occupied,mutants=layout.arena.bot_spawns)
                    self.assertEqual(len(cells),3)
                    self.assertFalse(set(cells)&occupied);occupied.update(cells)

    def test_three_real_owners_share_one_map_and_ten_hostile_mutants(self):
        before={a:OwnedPetStore(self.path).list(a) for a in self.accounts}
        scene=self.prepare();field=scene.field;combat=field.combat
        self.assertEqual(len(field._actors),13)
        self.assertEqual(len(field.actor_ids(scene.bot_owner)),10)
        self.assertTrue(field.allied(42,44));self.assertFalse(field.allied(42,43))
        for owner in self.owners[:3]:
            self.assertFalse(field.allied(owner,scene.bot_owner))
            ids=field.actor_ids(owner);self.assertEqual(len(ids),1)
            self.assertGreaterEqual(ids[0],0x40000001)
            self.assertLess(ids[0],0x71000000)
            self.assertEqual(combat.storage_ids[ids[0]],self.fixture.identity)
            self.assertEqual(combat.persistence[ids[0]],(self.path,self.accounts[self.owners.index(owner)]))
            self.assertEqual(decode_item_list(combat.inventories[ids[0]])[0],ids[0])
            self.assertEqual(field.actor(ids[0]).sight_radius,5)
        records={decode_battle_soldier(p,human_equipment=True).soldier_id
                 for p in scene.packets if p[:1]==b'\x3b'}
        self.assertEqual(records,set(field._actors))
        self.assertEqual({a:OwnedPetStore(self.path).list(a) for a in self.accounts},before)

    def test_mutant_darkness_applies_once_across_admission_and_restore(self):
        from tio.battle_item_effects import refresh_sight
        scene=self.prepare((0,));field=scene.field
        npc_ids=field.actor_ids(scene.bot_owner)
        def check_sight(current):
            for identity in npc_ids:
                self.assertEqual(current.actor(identity).sight_radius,6)
                self.assertEqual(current.combat.item_effects['base_sight'][identity],9)
                self.assertEqual(current.combat.item_effects['last_sight'][identity],6)
            self.assertEqual(refresh_sight(current.combat),())
        check_sight(field)
        append_mining_owner(field,self.path,self.accounts[1],self.tickets[1],self.catalog,
                            role=2,templates=scene.visibility.templates)
        check_sight(field)
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(field),rebase=False)
        check_sight(restored)

    def test_shared_mutants_retain_provisional_base_sight(self):
        from tio.battle_item_effects import refresh_sight
        from tools import mining_scene
        original=mining_scene.prepare_mining
        def prepare_with_bonus(*args,**kwargs):
            provisional=original(*args,**kwargs)
            identity=provisional.field.actor_ids(provisional.bot_owner)[0]
            provisional.field.combat.item_effects['base_sight'][identity]+=2
            refresh_sight(provisional.field.combat)
            return provisional
        with patch.object(mining_scene,'prepare_mining',side_effect=prepare_with_bonus):
            scene=self.prepare((0,))
        identity=scene.field.actor_ids(scene.bot_owner)[0]
        self.assertEqual(scene.field.actor(identity).sight_radius,8)
        self.assertEqual(scene.field.combat.item_effects['base_sight'][identity],11)

    def test_old_shared_snapshot_upgrades_sight_once_preserving_modifiers_and_memory(self):
        from copy import deepcopy
        from tio.battle_item_effects import refresh_sight
        from tio.mining_ai import ensure_hunters
        for has_memory in (False,True):
            with self.subTest(has_memory=has_memory):
                scene=self.prepare((0,1));field=scene.field
                npc_ids=field.actor_ids(scene.bot_owner)
                bonus,flashed,remembering=npc_ids[:3]
                del field.mine_mutant_sight_version
                state=field.combat.item_effects
                for identity in npc_ids:state['base_sight'][identity]-=3
                refresh_sight(field.combat)
                self.assertTrue(all(field.actor(i).sight_radius==3 for i in npc_ids))
                state['base_sight'][bonus]+=2
                state['flash'][flashed]=7
                refresh_sight(field.combat)
                if has_memory:
                    field.mine_hunter_state[remembering].update(mode='search',
                        target_id=field.actor_ids(42)[0],last_seen=(10,10),last_seen_turn=1,search_index=2)
                    memory=deepcopy(field.mine_hunter_state)
                else:
                    del field.mine_hunter_state
                    for identity in npc_ids:
                        points=field.bot_patrol_waypoints[identity]
                        field.bot_patrol_waypoints[identity]=(points[0],points[-1])
                humans={i:(field.actor(i).sight_radius,state['base_sight'][i])
                        for i in field._actors if i not in npc_ids}
                field,_=battle_snapshot.loads(battle_snapshot.dumps(field),rebase=False)
                ensure_hunters(field,npc_ids)
                self.assertEqual(field.mine_mutant_sight_version,1)
                state=field.combat.item_effects
                for identity in npc_ids:
                    self.assertEqual(state['base_sight'][identity],11 if identity==bonus else 9)
                    self.assertEqual(field.actor(identity).sight_radius,
                                     8 if identity==bonus else 4 if identity==flashed else 6)
                self.assertEqual(state['flash'],{flashed:7})
                self.assertEqual({i:(field.actor(i).sight_radius,state['base_sight'][i])
                                  for i in humans},humans)
                if has_memory:self.assertEqual(field.mine_hunter_state,memory)
                else:
                    self.assertEqual(set(field.mine_hunter_state),set(npc_ids))
                    self.assertTrue(all(len(p)>=3 for p in field.bot_patrol_waypoints.values()))
                before=battle_snapshot.dumps(field,clock=lambda:0,wall=lambda:0)
                ensure_hunters(field,npc_ids)
                self.assertEqual(battle_snapshot.dumps(field,clock=lambda:0,wall=lambda:0),before)
                restored,_=battle_snapshot.loads(before,rebase=False)
                ensure_hunters(restored,npc_ids)
                self.assertEqual(battle_snapshot.dumps(restored,clock=lambda:0,wall=lambda:0),before)

    def test_mutant_observer_uses_own_sight_with_flash_flare_and_smoke_after_restore(self):
        from tio.battle_item_effects import can_observe,refresh_sight
        scene=self.prepare((0,1));field=scene.field
        field.blocked=frozenset();field.transparent_obstacles=frozenset()
        observer,other=field.actor_ids(scene.bot_owner)[:2]
        target=field.actor_ids(42)[0]
        for identity,position in ((observer,(10,10)),(other,(20,10)),(target,(16,10))):
            field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1])
        def observes(current,identity=observer):
            return can_observe(current.combat,current.actor(identity),current.actor(target))
        self.assertTrue(observes(field))
        field._actors[target]=replace(field.actor(target),x=17)
        self.assertFalse(observes(field))
        self.assertTrue(observes(field,other))
        field._actors[target]=replace(field.actor(target),x=15)
        field.combat.item_effects['flash'][observer]=1
        refresh_sight(field.combat)
        self.assertEqual(field.actor(observer).sight_radius,4)
        self.assertFalse(observes(field))
        field,_=battle_snapshot.loads(battle_snapshot.dumps(field),rebase=False)
        self.assertEqual(refresh_sight(field.combat),())
        self.assertEqual(field.actor(observer).sight_radius,4)
        self.assertFalse(observes(field))
        del field.combat.item_effects['flash'][observer]
        refresh_sight(field.combat)
        self.assertEqual(field.actor(observer).sight_radius,6)
        self.assertTrue(observes(field))
        field._actors[target]=replace(field.actor(target),x=18)
        self.assertFalse(observes(field))
        field.combat.item_effects['areas'][1]=dict(kind='flare',center=(18,10),radius=1,
                                                source=target,owner=42,expiry=3)
        self.assertTrue(observes(field))
        field.combat.item_effects['areas'][2]=dict(kind='smoke',center=(14,10),radius=1,
                                                source=target,owner=42,expiry=3)
        field,_=battle_snapshot.loads(battle_snapshot.dumps(field),rebase=False)
        self.assertFalse(observes(field))
        del field.combat.item_effects['areas'][2]
        self.assertTrue(observes(field))
        field.blocked=frozenset(((14,10),))
        self.assertFalse(observes(field))

    def test_live_append_preserves_existing_mutants_deposits_and_global_ids(self):
        scene=self.prepare((0,));field=scene.field;mine=field.mining
        mob=field.actor_ids(scene.bot_owner)[0]
        field._actors[mob]=replace(field.actor(mob),health=0)
        npc_before=tuple(field.actor(i) for i in field.actor_ids(scene.bot_owner))
        deposit=next(iter(mine.deposits.values()));deposit.left-=7
        before=(deposit.left,mine.round,mine.last_tick)
        view,packets=append_mining_owner(field,self.path,self.accounts[1],self.tickets[1],self.catalog,
                                        role=2,templates=scene.visibility.templates)
        first=field.actor_ids(42)[0];raider=field.actor_ids(43)[0]
        self.assertNotEqual(first,raider);self.assertEqual(len(field.actor_ids(scene.bot_owner)),10)
        self.assertEqual(tuple(field.actor(i) for i in field.actor_ids(scene.bot_owner)),npc_before)
        self.assertEqual((deposit.left,mine.round,mine.last_tick),before)
        self.assertEqual(view.field,field);self.assertEqual(packets[-1],b'\x41')
        self.assertEqual({decode_battle_soldier(p,human_equipment=True).soldier_id
                          for p in packets if p[:1]==b'\x3b'},set(field._actors))
        field.remove_owner(43)
        append_mining_owner(field,self.path,self.accounts[3],self.tickets[3],self.catalog,
                            role=1,templates=scene.visibility.templates)
        self.assertGreater(field.actor_ids(45)[0],raider)
        with self.assertRaises(ValueError):
            append_mining_owner(field,self.path,self.accounts[1],replace(self.tickets[1],character_id=46),
                                self.catalog,role=2,templates=scene.visibility.templates)

    def test_lift_waits_five_rounds_after_raider_and_survives_exit_and_snapshot(self):
        scene=self.prepare((0,2));field=scene.field;mine=field.mining
        mine.advance(1)
        append_mining_owner(field,self.path,self.accounts[1],self.tickets[1],self.catalog,
                            role=2,templates=scene.visibility.templates)
        self.assertEqual(mine.lift_blocked_until,6)
        self.assertEqual((mine.exit_blocked_until_by_owner[42],mine.exit_blocked_until_by_owner[44]),(6,6))
        drill=next(iter(field.loot.boxes.values()))[0]
        miner=field.actor_ids(42)[0];defender=field.actor_ids(44)[0]
        for identity,position in zip((miner,defender),sorted(mine.layout.lift)):
            field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1])
        field.combat.inventories[miner]=encode_item_list(miner,(replace(drill,unknown_u32_01=137),))
        with self.assertRaises(ValueError):mine.exit(42)
        with self.assertRaises(ValueError):mine.exit(44)
        self.assertFalse(mine.register_owner(43,2));self.assertEqual(mine.lift_blocked_until,6)
        raider=field.actor_ids(43)[0];position=next(iter(mine.layout.raider_exits))
        field._actors[raider]=replace(field.actor(raider),x=position[0],y=position[1])
        self.assertEqual(mine.exit(43),0)
        field.remove_owner(43)
        for generation in range(2,6):mine.advance(generation)
        self.assertEqual(mine.round,5)
        self.assertFalse(mine.register_owner(43,2));self.assertEqual(mine.lift_blocked_until,6)
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(field),rebase=False)
        with self.assertRaises(ValueError):restored.mining.exit(42)
        restored.mining.advance(6);self.assertEqual(restored.mining.round,6)
        self.assertEqual(restored.mining.exit(42),137)
        self.assertEqual(restored.mining.exit(42),137)
        self.assertIn(miner,restored._actors)
        self.assertNotIn(44,restored.mining.exited)
        self.assertIsNone(restored.mining.extracted_amounts[44])
        self.assertEqual(restored.mining.exit(44),0)
        self.assertFalse(restored.mining.register_owner(42,1))
        with self.assertRaises(ValueError):restored.mining.install(42,ItemAction(miner,drill.instance_id,255))

    def test_late_miner_inherits_remaining_lift_deadline_without_join_tick(self):
        scene=self.prepare((0,1));mine=scene.field.mining
        mine.advance(1);mine.advance(2)
        append_mining_owner(scene.field,self.path,self.accounts[3],self.tickets[3],self.catalog,
                            role=1,templates=scene.visibility.templates)
        self.assertEqual((mine.round,mine.last_tick,mine.exit_blocked_until_by_owner[45]),(2,2,5))
        self.assertEqual(mine.advance(2),());self.assertEqual(mine.round,2)

    def test_drill_is_shared_but_pickup_capacity_and_ownership_are_private(self):
        scene=self.prepare();field=scene.field;mine=field.mining;combat=field.combat
        field.blocked=frozenset();field.transparent_obstacles=frozenset()
        deposit=next(iter(mine.deposits.values()));x,y=deposit.position
        ids={o:field.actor_ids(o)[0] for o in self.owners[:3]}
        for offset,(owner,identity) in enumerate(ids.items()):
            field._actors[identity]=replace(field.actor(identity),x=x+offset,y=y,action_points=30)
            combat.inventories[identity]=encode_item_list(identity,())
            combat.weight_capacities[identity]=500
        drill=next(iter(field.loot.boxes.values()))[0]
        combat.inventories[ids[42]]=encode_item_list(ids[42],(drill,))
        mine.install(42,ItemAction(ids[42],drill.instance_id,255))
        self.assertEqual(mine.advance(1),());mine.advance(2)
        self.assertEqual(deposit.extracted,200)
        combat.weight_capacities[ids[43]]=200
        old_inventory=combat.inventories[ids[43]];old_ap=field.actor(ids[43]).action_points
        with self.assertRaises(ValueError):mine.pickup(43,ids[43],x,y,137)
        self.assertEqual((combat.inventories[ids[43]],field.actor(ids[43]).action_points),(old_inventory,old_ap))
        self.assertIsNotNone(deposit.drill)
        with self.assertRaises(ValueError):mine.pickup(42,ids[43],x,y,137)
        combat.weight_capacities[ids[43]]=500
        mine.pickup(43,ids[43],x,y,137)
        self.assertEqual(decode_item_list(combat.inventories[ids[43]])[1][0].count,137)
        mine.install(43,ItemAction(ids[43],drill.instance_id,255));mine.advance(3)
        field._actors[ids[44]]=replace(field.actor(ids[44]),x=x,y=y+1)
        mine.pickup(44,ids[44],x,y,200)
        self.assertEqual(decode_item_list(combat.inventories[ids[44]])[1][0].count,200)
        self.assertEqual(decode_item_list(combat.inventories[ids[42]])[1],())
        for account in self.accounts[:3]:
            self.assertFalse(any(i.template_id==52 for _,_,inv in OwnedPetStore(self.path).list(account)
                                 for i in decode_item_list(inv)[1]))

    def test_deposit_fog_caches_are_per_owner_and_do_not_reveal_remote_ticks(self):
        scene=self.prepare();field=scene.field;mine=field.mining
        field.blocked=frozenset();field.transparent_obstacles=frozenset()
        from tio.mining import Deposit
        deposit=Deposit(1,(14,10),500,500);mine.deposits={deposit.position:deposit};mine.sent_deposits={}
        for owner,position in ((42,(10,10)),(44,(10,12)),(43,(35,35))):
            identity=field.actor_ids(owner)[0]
            field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1],sight_radius=5)
        self.assertEqual(mine.packets(42),(deposit.packet(),));self.assertEqual(mine.packets(44),(deposit.packet(),))
        self.assertEqual(mine.packets(43),())
        deposit.drill=next(iter(field.loot.boxes.values()))[0]
        self.assertEqual(mine.advance(1),());self.assertEqual(deposit.extracted,100)
        self.assertEqual(mine.packets(43),())
        self.assertEqual(mine.packets(42),(deposit.packet(),));self.assertEqual(mine.packets(42),())
        self.assertEqual(mine.packets(44),(deposit.packet(),))
        identity=field.actor_ids(43)[0]
        field._actors[identity]=replace(field.actor(identity),x=14,y=12)
        self.assertEqual(mine.packets(43),(deposit.packet(),))

    def test_rejected_append_does_not_mutate_scene_and_role_change_is_forbidden(self):
        scene=self.prepare((0,));field=scene.field
        before=battle_snapshot.dumps(field,clock=lambda:0,wall=lambda:0)
        for role,ticket in ((4,self.tickets[1]),(2,replace(self.tickets[1],levels=(7,)))):
            with self.assertRaises(ValueError):
                append_mining_owner(field,self.path,self.accounts[1],ticket,self.catalog,
                                    role=role,templates=scene.visibility.templates)
            self.assertEqual(battle_snapshot.dumps(field,clock=lambda:0,wall=lambda:0),before)
        with self.assertRaises(ValueError):field.mining.register_owner(42,2)
        self.assertEqual(field.mining.roles,{42:1})


if __name__=='__main__':unittest.main()
