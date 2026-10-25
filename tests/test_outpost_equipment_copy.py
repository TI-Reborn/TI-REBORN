"""Two saved owners, empty native battle copies and real persistent CAS."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from tio.abilities import AbilityCatalog,AbilityLevel
from tio.ability_state import AbilityStateStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.abilities import AbilityEntry,decode_abilities
from tio.protocol.battle_loot import LootTransfer
from tio.protocol.item_action import ItemAction
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.pet_info import PetInfo,SCHEMAS,decode_pet_info,encode_pet_info
from tio.weapon_proficiency import SAVED,number
from test_combat import item

ROOT=Path(__file__).resolve().parents[1]


class OutpostEquipmentTests(unittest.TestCase):
    def setUp(self):
        import test_world_core_integration
        test_world_core_integration.WorldSceneCoreTests.setUp(self)
        source=json.loads((ROOT/'config/abilities.json').read_text())
        self.catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        self.abilities=AbilityStateStore(self.path,self.catalog)

    def saved(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.execute('SELECT account,pet_id,human,pet_packet,inventory_packet FROM owned_pets ORDER BY account,pet_id'))

    def gear(self,index,resource,items,learned=(),*,flag=7):
        account=self.seats[index][3]
        with closing(sqlite3.connect(self.path)) as db,db:
            row=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(account,)).fetchone()
            fields=decode_pet_info(row[0],human_equipment=True).fields
            fields={**fields,'0x8c446f':resource,'0x8c4a1b':8 if resource==6 else 9,
                    '0x8c4aef':4,'0x8c4a07':100,'0x8c4ab1':100,'0x8c4ac5':0}
            human=resource in (1,2,6)
            if not human:
                fields={k:fields.get(k,0) for k,_,_ in SCHEMAS[(False,bool(fields['0x6d0203']),bool(fields['0x8c4565']))]}
                fields.update({'0x8c47f5':333,'0x8c4821':items[0].template_id if items else 0})
            packet=encode_pet_info(PetInfo(human,fields))
            db.execute('UPDATE owned_pets SET human=?,pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',
                       (human,packet,encode_item_list(1,items,flag),account))
        self.abilities.replace(account,1,tuple(AbilityEntry(i,1,0,0) for i in learned),expected_revision=0)
        # Ranked admission now rejects wounded fighters; learned passives can
        # raise the projected maximum above the saved 100 HP, so heal to it.
        from tio.passive_stats import project_saved_pet
        with closing(sqlite3.connect(self.path)) as db,db:
            human,raw=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(account,)).fetchone()
            maximum=decode_pet_info(project_saved_pet(db,account,1,bytes(raw),bool(human)),human_equipment=bool(human)).fields['0x8c4a07']
            pet=decode_pet_info(bytes(raw),human_equipment=bool(human))
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',
                       (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4ab1':maximum})),account))

    def prepare(self,town=4,**kwargs):
        from tio.team_scene import prepare
        with patch('tio.ranks.time.time',return_value=1700000000):
            return prepare(self.seats,0,seed=23,town_id=town,selected_ids=True,**kwargs)

    def humans(self):
        self.gear(0,1,(replace(item(1001,254),unknown_u8_01=1,location_raw=4),
                       item(1002,339,1,True),item(1003,1,2000)),learned=(1,2,6))
        self.gear(1,2,(replace(item(1001,264),unknown_u8_01=1,location_raw=4),
                       item(1002,301,1,True),item(1003,9,10)),learned=(1,2))

    def test_two_owners_empty_native_lists_and_equipment_dependent_projection(self):
        self.humans();before=self.saved();equipped=self.prepare(2)[0]
        field,views,_,skills=self.prepare();combat=field.combat
        self.assertEqual(set(combat.personal_inventories),set(field._actors))
        maximum=100+self.catalog.get(1,1).number('value')
        for identity,actor in field._actors.items():
            self.assertEqual(decode_item_list(combat.inventory_packet(identity))[1],())
            self.assertEqual([w.template_id for w in actor.weapons],[300])
            self.assertEqual(actor.action_points,field._turn_points[identity])
            # Admission requires full health, so the copy starts at the projected maximum.
            self.assertEqual((actor.health,actor.max_health),(maximum,maximum))
            self.assertEqual(actor.sight_radius,9)
            template=views[actor.owner_id].snapshot(identity)
            from tio.protocol.battle_soldier import decode_battle_soldier,HUMAN_EQUIPMENT_FIELDS
            native=decode_battle_soldier(template,human_equipment=True).fields
            self.assertTrue(all(native[k]==0 for k in HUMAN_EQUIPMENT_FIELDS.values()))
            self.assertEqual((native['0x8c57e7'],native['0x8c57d0']),(0,combat.weight_capacity(identity)))
            self.assertEqual((native['0x8c566a'],native['0x8c571d']),(maximum,actor.action_points))
            self.assertEqual({e.ability_id for e in decode_abilities(skills[identity])[1]},
                             {e.ability_id for e in combat.learned[identity]})
            self.assertNotIn(27,{e.ability_id for e in combat.skill_lists[identity]})
        a,b=field.actor_ids(51)[0],field.actor_ids(52)[0]
        oldb=equipped.actor_ids(52)[0]
        self.assertEqual(equipped.combat.weight_capacity(oldb)-combat.weight_capacity(b),200)
        self.assertEqual(number(decode_pet_info(combat.proficiencies[a],human_equipment=True).fields[SAVED[0]]),35)
        self.assertEqual(combat.defense(a),0)
        self.assertEqual(self.saved(),before)

    def test_miner_naked_perk_reappears_without_saved_helmet_shield_or_sight(self):
        self.gear(0,6,(replace(item(1001,262),unknown_u8_01=1,location_raw=1),
                       item(1002,341,1,True)),learned=(20,21,24,22))
        field,views,_,skills=self.prepare();identity=field.actor_ids(51)[0];combat=field.combat
        naked=self.catalog.get(24,1).number('value')
        self.assertEqual(combat.defense(identity),naked)
        self.assertEqual(combat.displayed_armor(identity),naked)
        self.assertEqual(field.actor(identity).sight_radius,8)
        self.assertEqual([w.template_id for w in field.actor(identity).weapons],[337])
        self.assertIn((identity,22),field._slash_rules)
        self.assertEqual({e.ability_id for e in decode_abilities(skills[identity])[1]},{20,21,24,22})

    def test_dog_armor_removed_but_learned_health_defense_fangs_rules_remain(self):
        from tio.equipment import armor_rules
        dog_armor=next(i for i,r in armor_rules().items() if r['dog'] and r['level']<=4)
        self.gear(0,3,(replace(item(1001,dog_armor),unknown_u8_01=1,location_raw=4),),learned=(15,16,18,23,26))
        field,views,_,_=self.prepare();identity=field.actor_ids(51)[0];combat=field.combat
        self.assertEqual(combat.defense(identity),self.catalog.get(15,1).number('value'))
        self.assertEqual(field.actor(identity).max_health,100+self.catalog.get(16,1).number('value'))
        self.assertEqual([w.template_id for w in field.actor(identity).weapons],[333])
        self.assertEqual(field.actor(identity).sight_radius,12)
        self.assertIn((identity,23),field._healing_rules);self.assertIn((identity,26),field._dog_rules)
        self.assertEqual(views[51].templates[identity].fields['0x8c546e'],0)

    def collect(self,field):
        from types import SimpleNamespace
        identity=field.actor_ids(51)[0];actor=field.actor(identity)
        position=next(iter(field.loot.boxes));field.blocked=field.blocked-{position}
        field._actors[identity]=replace(actor,x=position[0],y=position[1])
        field.loot.open(51,SimpleNamespace(actor_id=identity,x=position[0],y=position[1]),1)
        med=next(i for i in field.loot.boxes[position] if i.template_id in (9,34))
        field.loot.transfer(51,LootTransfer(identity,*position,withdrawals=((med.instance_id,med.count),)),1)
        return identity,med

    def test_crate_pickup_and_medical_consumption_cas_preserve_exact_personal_packets(self):
        self.humans();before=self.saved();field,_,_,_=self.prepare();identity,med=self.collect(field)
        field._actors[identity]=replace(field.actor(identity),health=1)
        reply=field.combat.use_medical(51,ItemAction(identity,med.instance_id,255))
        self.assertTrue(reply)
        remaining=decode_item_list(field.combat.inventories[identity])[1]
        self.assertEqual(sum(i.count for i in remaining),med.count-1)
        self.assertEqual(self.saved(),before)
        # The same saved item IDs exist in both owners' personal inventories;
        # only the authenticated account-local storage ID is used for CAS.
        for actor_id in field._actors:
            _,original,_=decode_item_list(field.combat.personal_inventories[actor_id])
            persisted=field.combat.persistent_inventory(field.combat.inventories[actor_id])
            self.assertEqual(decode_item_list(persisted)[1],original)
            self.assertFalse({i.instance_id for i in original}&field.combat.temporary_items)

    def test_stale_city_change_rejects_pickup_without_consuming_or_overwriting(self):
        from types import SimpleNamespace
        self.humans();field,_,_,_=self.prepare();combat=field.combat;identity=field.actor_ids(51)[0]
        position=next(iter(field.loot.boxes));field.blocked=field.blocked-{position}
        field._actors[identity]=replace(field.actor(identity),x=position[0],y=position[1])
        field.loot.open(51,SimpleNamespace(actor_id=identity,x=position[0],y=position[1]),1)
        supply=field.loot.boxes[position][0];inventory=dict(combat.inventories);box=field.loot.boxes[position]
        changed=encode_item_list(1,(item(7001,301),))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=1",(changed,))
        with self.assertRaisesRegex(ValueError,'outside battle'):
            field.loot.transfer(51,LootTransfer(identity,*position,withdrawals=((supply.instance_id,supply.count),)),1)
        self.assertEqual(combat.inventories,inventory);self.assertEqual(field.loot.boxes[position],box)
        self.assertEqual(OwnedPetStore(self.path).inventory('alice',1),changed)

    def test_temporary_weapon_attack_trains_saved_base_without_wearing_personal_gear(self):
        from types import SimpleNamespace
        from tio.protocol.battle_attack import AttackRequest,decode_attack_result
        from test_combat import FixedRandom
        self.humans();field,views,_,_=self.prepare();combat=field.combat
        a,b=field.actor_ids(51)[0],field.actor_ids(52)[0]
        position=next(iter(field.loot.boxes));field.blocked=frozenset()
        field.transparent_obstacles=None
        field._actors[a]=replace(field.actor(a),x=position[0],y=position[1])
        field.loot.open(51,SimpleNamespace(actor_id=a,x=position[0],y=position[1]),1)
        supplies=field.loot.boxes[position]
        field.loot.transfer(51,LootTransfer(a,*position,withdrawals=tuple((i.instance_id,i.count) for i in supplies)),1)
        weapon=next(i for i in supplies if i.template_id in combat.catalog.weapons)
        combat.equip(51,ItemAction(a,weapon.instance_id,255),view=views[51])
        field._actors[a]=replace(field.actor(a),x=1,y=1,action_points=15)
        field._actors[b]=replace(field.actor(b),x=2,y=1)
        views[51].refresh()
        combat.rng=FixedRandom();combat.rng.randrange=lambda n:0
        inventory_before=[r[4] for r in self.saved()]
        training_before=dict(combat.proficiencies)
        replies=combat.attack(51,AttackRequest(a,2,1),view=views[51])
        attacks=[decode_attack_result(p) for p in replies if p[:1]==b'\x4b']
        self.assertTrue(attacks);self.assertTrue(any(h.damage>0 for attack in attacks for h in attack.hits))
        self.assertNotEqual(combat.proficiencies[a],training_before[a])
        self.assertEqual([r[4] for r in self.saved()],inventory_before)
        self.assertTrue(all(i.instance_id in combat.temporary_items for i in decode_item_list(combat.inventories[a])[1]))

    def test_multiowner_batch_cas_rolls_back_first_owner_when_second_is_stale(self):
        self.humans();field,_,_,_=self.prepare();combat=field.combat
        first,second=field.actor_ids(51)[0],field.actor_ids(52)[0]
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE cas_probe(account TEXT)')
            db.execute('CREATE TRIGGER observe_inventory AFTER UPDATE OF inventory_packet ON owned_pets BEGIN INSERT INTO cas_probe VALUES(new.account); END')
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='bob'",(encode_item_list(1,(item(7002,9,2),)),))
            db.execute('DELETE FROM cas_probe')
        before=self.saved()
        with self.assertRaisesRegex(ValueError,'outside battle'):
            combat._persist_batch({first:combat.inventories[first],second:combat.inventories[second]})
        self.assertEqual(self.saved(),before)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM cas_probe').fetchone()[0],0)

    def test_temporary_death_drop_and_owner_removal_never_drop_or_consume_personal_gear(self):
        self.humans();before=self.saved();field,_,_,_=self.prepare();identity,med=self.collect(field)
        combat=field.combat;state=replace(field.actor(identity),health=0);changes={}
        old_box=field.loot.boxes[(state.x,state.y)]
        boxes,ground=field.loot.stage_deaths({identity:state},changes)
        self.assertEqual([i.instance_id for i in boxes[(state.x,state.y)]],
                         [i.instance_id for i in old_box]+[med.instance_id])
        self.assertTrue(all(i.instance_id in combat.temporary_items for i in boxes[(state.x,state.y)]))
        combat._persist_batch(changes);combat.inventories.update(changes);field._actors[identity]=state
        field.remove_owner(51)
        self.assertEqual(self.saved(),before)
        self.assertIn(identity,combat.personal_inventories)
        self.assertEqual(decode_item_list(combat.persistent_inventory(combat.inventories[identity]))[1],decode_item_list(combat.personal_inventories[identity])[1])

    def test_snapshot_resumes_consumption_and_native_city_gear_is_restored(self):
        from tio.battle_snapshot import dumps,loads
        from tio.passive_stats import project_saved_pet
        from tools.battle_actor_fixture import actor_packet
        from tio.protocol.battle_soldier import decode_battle_soldier
        self.humans();before=self.saved();field,views,ground,skills=self.prepare();identity,med=self.collect(field)
        restored=loads(dumps((field,views,ground,skills)))[0];new=restored[0];combat=new.combat
        self.assertEqual(combat.personal_inventories,field.combat.personal_inventories)
        self.assertEqual(combat.temporary_items,field.combat.temporary_items)
        self.assertIs(new.loot.combat,combat)
        new._actors[identity]=replace(new.actor(identity),health=1)
        combat.use_medical(51,ItemAction(identity,med.instance_id,255))
        self.assertEqual(self.saved(),before)
        with closing(sqlite3.connect(self.path)) as db:
            raw,inventory=db.execute("SELECT pet_packet,inventory_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()
            city=project_saved_pet(db,'alice',1,raw,True)
        native=decode_battle_soldier(actor_packet(city,51,inventory),human_equipment=True)
        self.assertEqual(native.fields['0x8c52cf'],339)
        self.assertEqual(native.fields['0x8c531b'],254)

    def test_personal_ids_cannot_be_temporary_and_unmarked_supplies_cannot_persist(self):
        self.humans();field,_,_,_=self.prepare();combat=field.combat;identity=field.actor_ids(51)[0]
        with self.assertRaisesRegex(ValueError,'persistent item'):
            combat._persist_inventory(identity,combat.inventories[identity],encode_item_list(identity,(item(99999,9),)))
        combat.temporary_items.add(1001)
        with self.assertRaisesRegex(ValueError,'classified as temporary'):
            combat.persistent_inventory(combat.inventories[identity])

    def test_failed_serialization_leaves_birth_projection_unchanged(self):
        self.humans();field,views,_,_=self.prepare(2);combat=field.combat;identity=field.actor_ids(51)[0]
        before=dict(combat.inventories),dict(combat.proficiencies),dict(field._actors)
        with patch('tio.protocol.battle_soldier.encode_battle_soldier',side_effect=ValueError('serializer fault')):
            with self.assertRaisesRegex(ValueError,'serializer fault'):
                combat.exclude_personal_equipment(identity,self.catalog,views[51].templates[identity])
        self.assertEqual((combat.inventories,combat.proficiencies,field._actors),before)
        self.assertFalse(combat.personal_inventories)

    def test_other_towns_keep_personal_items_and_ordinary_base_admission_is_rejected(self):
        self.humans();field,_,_,_=self.prepare(2)
        self.assertFalse(field.combat.personal_inventories)
        self.assertTrue(all(decode_item_list(inv)[1] for inv in field.combat.inventories.values()))
        with self.assertRaises(ValueError):self.prepare(7)

    def test_trusted_outpost_base_scene_uses_same_copy_with_explicit_assault_layout(self):
        from tio.assault_map import generate
        self.humans();before=self.saved()
        field,_,_,_=self.prepare(7,arena_map=generate(deployment_size=3).arena,profile='assault')
        self.assertEqual(field.scene_metadata['world_policy']['town_id'],7)
        self.assertFalse(field.scene_metadata['world_policy']['carry_items'])
        self.assertEqual(set(field.combat.personal_inventories),set(field._actors))
        self.assertTrue(all(not decode_item_list(inv)[1] for inv in field.combat.inventories.values()))
        self.assertEqual(self.saved(),before)

    def test_actual_host_baseline_has_no_local_contract_patch(self):
        source=ROOT/'reports/gameplay-completion/stage8-world/source/combat.py'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),'d14ce3e7f05aa6e92f73683cf78ae845c707addc1416508da0cbd5089ad902da')

    def test_trusted_training_layout_retains_gear_but_ordinary_admission_rejects(self):
        from tio.assault_map import generate
        self.humans()
        field,_,_,_=self.prepare(19,arena_map=generate(deployment_size=3).arena,profile='assault')
        self.assertEqual(field.scene_metadata['world_policy']['map_geometry'],'original_assault_v1')
        self.assertTrue(field.scene_metadata['world_policy']['carry_items'])
        self.assertFalse(field.combat.personal_inventories)
        self.assertTrue(all(decode_item_list(inv)[1] for inv in field.combat.inventories.values()))
        with self.assertRaises(ValueError):self.prepare(19)

    def test_transient_source_ids_still_reserve_unique_supply_namespace(self):
        self.gear(0,1,(item(1001,301,1,True),))
        self.gear(1,2,(item(0xf0000000,301,1,True),))
        seat=self.seats[1];self.seats[1]=(*seat[:5],True)
        before=self.saved();field,views,_,_=self.prepare()
        self.assertEqual(set(views),{51})
        self.assertEqual(len(field.combat.personal_inventories),2)
        self.assertEqual(len(field.combat.persistence),1)
        self.assertTrue(all(i.instance_id>0xf0000000 for box in field.loot.boxes.values() for i in box))
        self.assertEqual(self.saved(),before)


if __name__=='__main__':unittest.main()
