from wallet_fixture import fund_wallet
import json
import sqlite3
import struct
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from test_combat import item
from tio.weight import (item_weights, inventory_weight, base_capacity, overload_stage,
                        turn_ap, project_base_weight, city_weight_update, encode_weight)
from tio.protocol.item_list import encode_item_list, decode_item_list
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_action import ItemAction
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.item_stacking import merge_stacks
from tio.owned_pets import OwnedPetStore
from tio.warehouse import WarehouseStore
from tio.wallets import WalletStore
from tio.shop import ShopStore
from tio.city_catalogs import CityCatalogs
from tio.protocol.shop_purchase import ShopPurchase
from tio.implants import catalog as implant_catalog, policy as implant_policy

ROOT=Path(__file__).resolve().parents[1]


class WeightTests(unittest.TestCase):
    def setUp(self):
        self.pet=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])

    def test_all_item_weights_match_imported_original_source(self):
        source=json.loads((ROOT/'evidence/items_diagnostic_provenance.json').read_text())['records']
        extension=json.loads((ROOT/'config/battle_item_catalog_extension.json').read_text())
        actual=item_weights()
        expected = {
            51: (1, 0), 52: (100, 51), 129: (50, 0), 353: (0, 0), 5013: (200, 0),
            65487: (20, 0), 65488: (15, 0), 65489: (0, 0), 65490: (0, 0),
            65513: (0, 0), 65514: (0, 0),
        }
        for record in source:
            fields=record['source_fields']
            expected[int(record['id'])] = (int(fields.get('weight', 0)),
                                           int(fields.get('containedItemId', 0)))
        for record in extension['items']:
            expected[record['id']] = (int(record['fields']['weight']), 0)
        expected[35] = (int(extension['amendments']['35']['weight']), 0)
        expected[310] = (100, 0)  # Manual p.60: SKS Carbine.
        expected.update(dict.fromkeys(implant_catalog(), (5, 0)))
        for tool in ('battery', 'repair', 'extraction', 'upgrade'):
            expected[implant_policy()[tool]['template']] = (5, 0)
        self.assertEqual(set(actual), set(expected))
        for template, weight in expected.items():
            with self.subTest(template=template):
                self.assertEqual(actual[template], weight)

    def test_stacks_and_equipment_conserve_mass(self):
        items=(item(1,301,equipped=True),item(2,5,32),item(3,5,40),
               item(4,9,3),item(5,34,8),item(6,8),item(7,317),item(8,246,equipped=True))
        expected=sum(item_weights()[i.template_id][0]*i.count for i in items)
        self.assertEqual(inventory_weight(encode_item_list(1,items)),expected)
        self.assertEqual(inventory_weight(encode_item_list(1,merge_stacks(items))),expected)
        loose=[replace(i,unknown_u8_01=0,location_raw=0) for i in items]
        self.assertEqual(inventory_weight(encode_item_list(1,loose)),expected)

    def test_boundary_penalties_and_all_actor_types(self):
        for weight,stage in ((0,0),(499,0),(500,1),(665,1),(666,2),(799,2),(800,3),(999,3),(1000,4),(50000,4)):
            self.assertEqual(overload_stage(weight,1000),stage)
            self.assertEqual(turn_ap(15,weight,1000),15-3*stage)
        for resource,capacity,ap in ((1,1315,15),(2,1315,15),(3,150,17),(4,150,17),(5,150,17),(6,1510,14)):
            self.assertEqual(base_capacity(resource,1),capacity)
            self.assertEqual(base_capacity(resource,5),capacity+200)
            self.assertEqual(turn_ap(ap,capacity,capacity),ap-12)
        self.assertEqual(turn_ap(5,1000,1000),0)

    def test_invalid_metadata_does_not_silently_make_items_weightless(self):
        for items in ((item(1,64000),),(item(1,5,0),)):
            with self.assertRaises(ValueError):inventory_weight(encode_item_list(1,items))
        for resource,level in ((0,1),(7,1),(1,0)):
            with self.assertRaises(ValueError):base_capacity(resource,level)
        with self.assertRaises(ValueError):overload_stage(1,0)

    def test_large_stack_is_not_wrapped_by_initial_word_field(self):
        inventory=encode_item_list(1,(item(1,5,70000),))
        total=70000*item_weights()[5][0]
        self.assertEqual(inventory_weight(inventory),total)
        pet=decode_pet_info(project_base_weight(self.pet,True,inventory),human_equipment=True)
        self.assertEqual(pet.fields['0x8c4b6d'],65535)
        packet=encode_weight(1,total,1000)
        self.assertEqual(struct.unpack('<BIIIIII B',packet),(0x4e,1,2,7,1000,6,total,0))
        self.assertEqual(turn_ap(15,total,1000),3)

    def test_medical_consumption_and_repeated_turns_use_original_ap_maximum(self):
        mass=item_weights()[9][0]
        self.assertGreater(mass,0)
        quantity=(658+mass-1)//mass
        inventory=encode_item_list(1,(item(1,9,quantity),))
        pet=project_base_weight(self.pet,True,inventory)
        field=BattleField(10,10,[BattleActor(1,7,1,1,15,20,100)],step_cost=1)
        field.combat=combat=Combat(field,WeaponCatalog())
        combat.register(1,inventory,human=True,pet_packet=pet)
        for _ in range(3):
            field.prepare_turn(7,(1,))
            self.assertEqual(field.actor(1).action_points,12)
            field._actors[1]=replace(field.actor(1),action_points=1)
        field.prepare_turn(7,(1,))
        combat.use_medical(7,ItemAction(1,1,255))
        self.assertEqual(field.actor(1).action_points,11)
        self.assertEqual(inventory_weight(combat.inventories[1]),(quantity-1)*mass)
        self.assertEqual(combat.weight_packet(1),encode_weight(1,(quantity-1)*mass,1315))
        field.prepare_turn(7,(1,))
        self.assertEqual(field.actor(1).action_points,15)
        self.assertEqual(field._turn_points[1],15)

    def test_purchase_transfer_and_relogin_use_only_carried_items(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'
            pets=OwnedPetStore(path)
            pets.ensure('alice',self.pet,encode_item_list(1,()),human=True)
            fund_wallet(path, 'alice', credits=10_000, gold=10_000)
            shop=ShopStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'))
            offer=next(o for o in shop.catalogs.items[0] if o.item_id==5)
            result=shop.purchase('alice',ShopPurchase(1,0,offer.unknown_u32_01,3))
            rounds=decode_item_list(result.inventory)[1][0]
            self.assertEqual(rounds.count,120)
            self.assertEqual(city_weight_update(path,'alice',result.inventory),encode_weight(1,120*item_weights()[5][0]))
            store=WarehouseStore(path,capacity=100)
            inventory,_=store.exchange('alice',1,deposits=((rounds.instance_id,100),))
            self.assertEqual(inventory_weight(inventory),20*item_weights()[5][0])
            from tio.passive_stats import project_saved_pet
            with closing(sqlite3.connect(path)) as db:
                row=db.execute('SELECT pet_packet FROM owned_pets').fetchone()
                projected=project_saved_pet(db,'alice',1,row[0],True)
            fields=decode_pet_info(projected,human_equipment=True).fields
            self.assertEqual(fields['0x8c4b6d'],20*item_weights()[5][0])
            self.assertEqual(fields['0x8c4b57'],1315)
            self.assertEqual(city_weight_update(path,'alice',inventory),encode_weight(1,fields['0x8c4b6d']))

    def test_survival_first_turn_and_visibility_snapshot_apply_overload(self):
        from tio.abilities import AbilityCatalog,AbilityLevel
        from tio.matchmaking import SurvivalQueue
        from tools.survival_scene import prepare_survival
        from tio.protocol.battle_soldier import decode_battle_soldier
        source=json.loads((ROOT/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'
            inventory=encode_item_list(1,(item(1,5,1315),))
            pets=OwnedPetStore(path);pets.ensure('alice',self.pet,inventory,human=True)
            ticket=SurvivalQueue().join(42,pets.list('alice'))
            scene=prepare_survival(path,'alice',ticket,catalog)
            for actor_id in scene.field._actors:
                actor=scene.field.actor(actor_id)
                self.assertEqual(actor.action_points,3)
                snapshot=decode_battle_soldier(scene.visibility.snapshot(actor_id),human_equipment=True)
                self.assertEqual(snapshot.fields['0x8c5694'],15)
                self.assertEqual(snapshot.fields['0x8c571d'],3)
                self.assertEqual(snapshot.fields['0x8c57e7'],inventory_weight(inventory))
                self.assertEqual(snapshot.fields['0x8c57d0'],1315)
                scene.field.prepare_turn(actor.owner_id,(actor_id,))
                self.assertEqual(scene.field.actor(actor_id).action_points,3)
