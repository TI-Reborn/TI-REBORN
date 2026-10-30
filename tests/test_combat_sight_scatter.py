"""Manual p39/p63-64 combat state, native projection and crash recovery.

Shared tests use independent SQLite accounts through TeamArena. They do not
claim acceptance with graphical game clients or on the hosting server.
"""
from contextlib import closing
from dataclasses import replace
import random
import sqlite3
import unittest
from unittest.mock import patch

from server.battle_events import project_action
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import battle_checkpoints, battle_snapshot
from tio.battle_hazards import apply_damage, add_burns
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat, combat_rules
from tio.owned_pets import OwnedPetStore
from tio.protocol.ability_cast import AbilityCast
from tio.protocol.battle_attack import AttackRequest, decode_attack_result, encode_attack_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_list import encode_item_list, decode_item_list
from tio.protocol.pet_info import decode_pet_info
from tio.visibility import visible_actors, field_sight
from tio.weapons import WeaponCatalog
from test_combat import item, FixedRandom
import test_shared_team_arena as shared_fixture


class ForcedScatter:
    def __init__(self,roll=99,index=0):self.rolls=iter((roll,index))
    def randrange(self,n):
        result=next(self.rolls)
        if not 0<=result<n:raise AssertionError('Forced scatter index is outside candidates')
        return result
    def randint(self,a,b):return a


class CombatSightScatterTests(unittest.TestCase):
    def combat(self,weapon=301,actors=None,blocked=()):
        actors=actors or [BattleActor(1,7,1,1,40,100,100),BattleActor(2,8,5,1,40,1,100)]
        field=BattleField(24,24,actors,blocked=blocked,step_cost=1)
        combat=Combat(field,WeaponCatalog(),rng=FixedRandom());field.combat=combat
        stats=combat.catalog.weapons[weapon]
        items=[item(100,weapon,2 if weapon==317 else 1,True)]
        if stats.ammo_id:items.append(item(101,stats.ammo_id,100))
        combat.register(1,encode_item_list(1,items),human=True)
        return field,combat

    def test_enemy_kill_expands_real_sight_once_without_changing_other_actors(self):
        field,combat=self.combat(actors=[BattleActor(1,7,1,1,40,100,100),
            BattleActor(2,8,5,1,40,1,100),BattleActor(3,8,11,1,40,100,100)])
        self.assertNotIn(3,visible_actors(field,7))
        combat.attack(7,AttackRequest(1,5,1))
        self.assertEqual(field.actor(1).sight_radius,10)
        self.assertEqual(field.actor(3).sight_radius,9)
        self.assertIn(3,visible_actors(field,7))
        self.assertEqual(combat.sight_kill_victims,{2})
        before=dict(field._actors)
        with self.assertRaises(ValueError):combat.attack(7,AttackRequest(1,5,1))
        self.assertEqual(field._actors,before)
        states={};awards,changed=combat.stage_kill_sight(states,[(1,2)])
        self.assertEqual((states,awards,changed),({}, {2},frozenset()))

    def test_blast_awards_each_enemy_but_no_ally_or_self(self):
        actors=[BattleActor(1,7,1,1,40,100,100),BattleActor(2,8,5,1,40,1,100),
                BattleActor(3,7,5,2,40,1,100),BattleActor(4,9,7,1,40,1,100)]
        field,combat=self.combat(317,actors)
        combat.attack(7,AttackRequest(1,5,1))
        self.assertEqual(field.actor(1).sight_radius,11)
        self.assertEqual(combat.sight_kill_victims,{2,4})
        self.assertEqual(combat.statistics[7]['kills'],2)
        self.assertEqual(tuple(field.actor(i).health for i in (2,3,4)),(0,0,0))

    def test_hazard_uses_current_source_and_repeated_stale_victim_cannot_kill_twice(self):
        field,combat=self.combat()
        source=field.actor(1);victim=field.actor(2)
        field._actors[1]=replace(source,x=2,sight_radius=11)
        apply_damage(combat,source,321,(5,1),(victim,),lambda _:100)
        self.assertEqual(field.actor(1).sight_radius,12)
        self.assertEqual(combat.rank_kills,[(1,2)])
        apply_damage(combat,source,321,(5,1),(victim,victim),lambda _:100)
        self.assertEqual(field.actor(1).sight_radius,12)
        self.assertEqual(combat.statistics[7]['kills'],1)
        self.assertEqual(combat.statistics[8]['losses'],1)
        self.assertEqual(combat.rank_kills,[(1,2)])

    def test_burn_kill_awards_its_owner_once_and_dead_source_never_grants_sight(self):
        field,combat=self.combat()
        source=field.actor(1)
        add_burns(combat,source,324,(2,))
        field._ability_turns[2]+=1
        combat.turn_effects(8,(2,))
        self.assertEqual(field.actor(1).sight_radius,10)
        self.assertEqual(combat.sight_kill_victims,{2})
        self.assertEqual(combat.turn_effects(8,(2,)),())
        field,combat=self.combat()
        field._actors[1]=replace(field.actor(1),health=0)
        apply_damage(combat,source,321,(5,1),(field.actor(2),),lambda _:100)
        self.assertEqual(visible_actors(field,7),{1})
        self.assertEqual(field.actor(1).health,0)

    def test_native_sight_limit_snapshot_roundtrip_and_new_battle_reset(self):
        field,combat=self.combat()
        field._actors[1]=replace(field.actor(1),sight_radius=15)
        combat.attack(7,AttackRequest(1,5,1))
        self.assertEqual(field.actor(1).sight_radius,15)
        combat.rng=random.Random(512)
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(combat),rebase=False)
        self.assertEqual(restored.sight_kill_victims,{2})
        self.assertEqual(restored.field.actor(1).sight_radius,15)
        self.assertEqual(restored.rng.getstate(),combat.rng.getstate())
        fresh,_=self.combat()
        self.assertEqual(fresh.actor(1).sight_radius,9)

    def test_scatter_changes_native_impact_damage_allies_and_cover_together(self):
        actors=[BattleActor(1,7,1,1,40,100,100),BattleActor(2,8,8,11,40,500,500),
            BattleActor(3,8,8,4,40,500,500),BattleActor(4,7,7,6,40,500,500),
            BattleActor(5,8,11,6,40,500,500)]
        field,combat=self.combat(317,actors,blocked=((10,6),))
        combat.rng=ForcedScatter()
        result=decode_attack_result(combat.attack(7,AttackRequest(1,8,8))[0])
        self.assertEqual((result.target,result.impact),((8,8),(8,6)))
        self.assertEqual({h.actor_id for h in result.hits},{3,4})
        self.assertEqual(tuple(field.actor(i).health for i in (2,3,4,5)),(500,401,401,500))
        self.assertEqual(field.actor(1).action_points,33)
        self.assertEqual(decode_item_list(combat.inventories[1])[1][0].count,1)

    def test_subgrenade_and_rocket_use_their_manual_spread(self):
        self.assertEqual(combat_rules()['scatter_radii_manual'],{'316':3,'317':2,'340':1})
        field,combat=self.combat(339)
        combat.inventories[1]=encode_item_list(1,(item(100,339,1,True),item(101,340,1)))
        combat.rng=ForcedScatter()
        result=decode_attack_result(combat.cast_subgrenade(7,AbilityCast(27,1,0,8,8))[0])
        self.assertEqual((result.weapon_id,result.skill_id,result.impact),(340,27,(8,7)))
        field,combat=self.combat(316)
        combat.rng=ForcedScatter()
        result=decode_attack_result(combat.attack(7,AttackRequest(1,10,10))[0])
        self.assertEqual((result.weapon_id,result.impact),(316,(10,7)))

    def test_accuracy_threshold_selects_location_and_never_rolls_each_blast_victim(self):
        for roll,expected in ((59,(8,8)),(60,(8,6))):
            field,combat=self.combat(317)
            combat.rng=ForcedScatter(roll)
            result=decode_attack_result(combat.attack(7,AttackRequest(1,8,8))[0])
            self.assertEqual(result.impact,expected)

    def test_scatter_validates_map_edges_blocked_cells_and_rocket_los(self):
        field,combat=self.combat(316,blocked=((2,0),(2,1),(2,2),(0,1)))
        combat.rng=random.Random(117)
        points={combat.scatter_impact(316,(1,1),(1,4),0) for _ in range(200)}
        self.assertGreater(len(points),3)
        for point in points:
            self.assertTrue(field.inside(*point))
            self.assertNotIn(point,field.blocked)
            self.assertLessEqual((point[0]-1)**2+(point[1]-4)**2,9)
            self.assertTrue(field_sight(field,(1,1),point))
        self.assertNotIn((1,4),points)

    def test_failed_persistence_restores_scatter_rng_hp_ap_inventory_and_awards(self):
        field,combat=self.combat(317)
        combat.rng=random.Random(71)
        before=(dict(field._actors),dict(combat.inventories),combat.rng.getstate())
        with patch.object(combat,'_persist_batch',side_effect=ValueError('stale inventory')):
            with self.assertRaisesRegex(ValueError,'stale inventory'):combat.attack(7,AttackRequest(1,5,1))
        self.assertEqual((field._actors,combat.inventories,combat.rng.getstate()),before)
        self.assertEqual(combat.sight_kill_victims,set())
        self.assertEqual(combat.statistics,{})

    def test_wager_attack_spends_ammunition_and_damages_without_training(self):
        from test_weapon_proficiency import setup
        field,combat=setup(304);combat.wager=True
        profile=combat.proficiencies[1]
        before=decode_item_list(combat.inventories[1])[1][1].count
        combat.attack(7,AttackRequest(1,5,1))
        self.assertEqual(combat.proficiencies[1],profile)
        self.assertLess(field.actor(2).health,1000)
        self.assertEqual(field.actor(1).action_points,40-combat.catalog.weapons[304].attack_ap)
        self.assertEqual(decode_item_list(combat.inventories[1])[1][1].count,before-combat.catalog.weapons[304].bullets_count)


class SharedSightScatterTests(unittest.TestCase):
    def setUp(self):
        self.case=shared_fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.wall=1000

    def prepare(self,weapon=301):
        case=self.case
        for index in (0,1):case.add_selected(index,2)
        stats=WeaponCatalog().weapons[weapon]
        items=(item(100,weapon,2 if weapon==317 else 1,True),)
        if stats.ammo_id:items+=(item(101,stats.ammo_id,100),)
        with closing(sqlite3.connect(case.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                (encode_item_list(1,items),'alice'))
        case.hub.journal=BattleJournal(case.hub,case.path,wall=lambda:self.wall)
        for index in (0,1):case.send(index,b'\xba\3\0\2');case.send(index,b'\x2e')
        self.owners=tuple(case.hub.identities[s] for s in case.sessions[:2])
        self.battle=case.hub.battles[self.owners[0]];field=self.battle['field']
        self.ids=tuple(field.actor_ids(o) for o in self.owners)
        self.assertFalse(self.battle['bots'])
        with case.hub.journal.unit(self.battle):
            field.blocked=frozenset();field.doors.states={};field.combat.rng=random.Random(31)
            for identity,position,sight,health in ((self.ids[0][0],(5,5),5,200),
                    (self.ids[0][1],(25,25),1,200),(self.ids[1][0],(6,5),5,1),
                    (self.ids[1][1],(11,5),5,200)):
                field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1],
                    sight_radius=sight,health=health,max_health=200)
            for view in self.battle['views'].values():view.refresh()
        for index in (0,1):case.send(index,b'\x36')
        case.hub.tick()
        if self.battle['arena']._turns[1][0]!=self.owners[0]:
            case.send(1,encode_end_turn());case.hub.tick()
        for queue in case.hub.queues.values():queue.clear()

    def restore(self):
        case=self.case;hub=TeamArena(clock=lambda:case.now)
        hub.journal=BattleJournal(hub,case.path,wall=lambda:self.wall);hub.journal.recover()
        for session in case.sessions[:2]:self.assertTrue(hub.resume(session))
        case.hub=hub;self.battle=hub.battles[self.owners[0]]
        return self.battle['field']

    def test_real_accounts_receive_expanded_sight_and_reconnect_preserves_only_battle_bonus(self):
        self.prepare();killer=self.ids[0][0];victim=self.ids[1][0];hidden=self.ids[1][1]
        field=self.battle['field']
        saved_sight=decode_pet_info(OwnedPetStore(self.case.path).list('alice')[0][1],human_equipment=True).fields['0x8c4a1b']
        self.assertNotIn(hidden,self.battle['views'][self.owners[0]].visible)
        packets=self.case.send(0,encode_attack_request(AttackRequest(killer,6,5)))
        other=tuple(self.case.hub.queues[self.owners[1]])
        self.assertEqual(field.actor(killer).sight_radius,6)
        for replies in (packets,other):
            snapshot=next(p for p in replies if p[0]==0x3b and int.from_bytes(p[1:5],'little')==killer)
            self.assertEqual(decode_battle_soldier(snapshot,human_equipment=True).fields['0x8c567f'],6)
        self.assertTrue(any(p[0]==0x3b and int.from_bytes(p[1:5],'little')==hidden for p in packets))
        self.assertFalse(any(p[0]==0x30 and decode_item_list(p)[0]==killer for p in other))
        restored=self.restore()
        self.assertEqual(restored.actor(killer).sight_radius,6)
        self.assertEqual(restored.combat.sight_kill_victims,{victim})
        packets=self.case.send(0,b'\x36')
        self.assertEqual(decode_battle_soldier(next(p for p in packets if p[0]==0x3b
            and int.from_bytes(p[1:5],'little')==killer),human_equipment=True).fields['0x8c567f'],6)
        self.assertEqual(decode_pet_info(OwnedPetStore(self.case.path).list('alice')[0][1],human_equipment=True).fields['0x8c4a1b'],saved_sight)

    def test_out_of_turn_hazard_sight_projects_only_to_current_visible_clients(self):
        self.prepare();field=self.battle['field'];combat=field.combat
        killer=self.ids[0][0];victim=self.ids[1][0]
        before=dict(field._actors);known={o:v.visible for o,v in self.battle['views'].items()}
        with self.case.hub.journal.unit(self.battle):
            effects=apply_damage(combat,field.actor(killer),321,(6,5),(field.actor(victim),),lambda _:100)
        for owner,view in self.battle['views'].items():
            packets=project_action(view,self.owners[1],before,known[owner],effects)
            soldier=next(p for p in packets if p[0]==0x3b and int.from_bytes(p[1:5],'little')==killer)
            self.assertEqual(decode_battle_soldier(soldier,human_equipment=True).fields['0x8c567f'],6)
        # A viewer who never knew the killer receives no real-position sight packet.
        view=self.battle['views'][self.owners[1]]
        field._actors[self.ids[1][1]]=replace(field.actor(self.ids[1][1]),x=30,y=30,sight_radius=1)
        view.visible=frozenset(self.ids[1]);view.resident_corpses={victim}
        self.assertFalse(any(p[0]==0x3b and int.from_bytes(p[1:5],'little')==killer
            for p in project_action(view,self.owners[1],before,frozenset(self.ids[1]),effects)))

    def test_journal_failure_restores_scatter_rng_and_sight_awards_before_broadcast(self):
        self.prepare(317);field=self.battle['field'];killer=self.ids[0][0]
        before=(dict(field._actors),field.combat.rng.getstate(),dict(field.combat.inventories))
        queues={owner:tuple(q) for owner,q in self.case.hub.queues.items()}
        with patch('server.battle_journal.store.save',side_effect=RuntimeError('checkpoint failure')):
            with self.assertRaisesRegex(RuntimeError,'checkpoint failure'):
                self.case.hub.battle_action(self.owners[0],encode_attack_request(AttackRequest(killer,9,5)))
        field=self.case.hub.battles[self.owners[0]]['field']
        self.assertEqual((field._actors,field.combat.rng.getstate(),field.combat.inventories),before)
        self.assertEqual(field.combat.sight_kill_victims,set())
        self.assertEqual({owner:tuple(q) for owner,q in self.case.hub.queues.items()},queues)


if __name__=='__main__':unittest.main()
