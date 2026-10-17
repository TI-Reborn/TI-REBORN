import json
import unittest
from pathlib import Path
from tools.battle_actor_fixture import actor_packet
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo
from tio.protocol.item_list import decode_item_list,encode_item_list
from dataclasses import replace


class BattleActorFixtureTests(unittest.TestCase):
    def test_only_equipped_items_project_to_battle(self):
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet=bytes.fromhex(fixture['packet_hex'])
        inv=bytes.fromhex(fixture['inventory_packet_hex'])
        owner,items,_=decode_item_list(inv)
        actor=decode_battle_soldier(actor_packet(pet,1,inv),human_equipment=True)
        self.assertFalse(any(actor.equipment_templates.values()))
        equipped=replace(items[0],unknown_u8_01=1,location_raw=1)
        inv=encode_item_list(owner,(equipped,))
        actor=decode_battle_soldier(actor_packet(pet,1,inv),human_equipment=True)
        self.assertEqual(actor.equipment_templates[1],equipped.template_id)
        for records in ((equipped,replace(equipped,instance_id=9999)),
                        (replace(equipped,unknown_u8_01=2),),
                        (replace(equipped,location_raw=3),)):
            with self.assertRaises(ValueError):actor_packet(pet,1,encode_item_list(owner,records))
        with self.assertRaises(ValueError):actor_packet(pet,1,encode_item_list(owner+1,(equipped,)))

    def test_original_slot_normalization(self):
        root=Path(__file__).resolve().parents[1]
        fixture=json.loads((root/'evidence/owned_pet_trial.json').read_text())
        _,items,_=decode_item_list(bytes.fromhex(fixture['inventory_packet_hex']))
        for case in json.loads((root/'evidence/inventory_slots_native.json').read_text())['cases']:
            item=replace(items[0],location_raw=case['slot'])
            self.assertEqual(item.client_slot,case['client_slot'])

    def test_saved_identity_health_and_level_are_not_reset(self):
        fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        fields=dict(decode_pet_info(bytes.fromhex(fixture['packet_hex']),human_equipment=True).fields)
        fields.update({'0x8c43eb':17,'0x8c4aef':3,'0x8c4a07':120,'0x8c4ab1':73,'0x8c4489':b'Actor'})
        packet=encode_pet_info(PetInfo(True,fields))
        actor=decode_battle_soldier(actor_packet(packet,42),human_equipment=True)
        self.assertEqual((actor.soldier_id,actor.owner_id,actor.level),(17,42,3))
        self.assertEqual((actor.fields['0x8c566a'],actor.fields['0x8c57bb']),(120,73))
        self.assertEqual(actor.fields['0x8c5116'],b'Actor')
        self.assertEqual(actor.position,(2,2))
