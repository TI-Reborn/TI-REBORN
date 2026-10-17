import json
import unittest
from pathlib import Path
from tio.protocol.binary import PacketError
from tio.protocol.pet_info import PetInfo,decode_pet_info,encode_pet_info

ROOT=Path(__file__).resolve().parents[1]


class PetInfoTests(unittest.TestCase):
    def test_original_trace_roundtrips(self):
        cases=json.loads((ROOT/'evidence/pet_info_native_variants.json').read_text())
        for case in cases:
            wire=b'\x66'+bytes.fromhex(case['body_hex'])
            pet=decode_pet_info(wire,human_equipment=case['profile']['human'])
            self.assertEqual(encode_pet_info(pet),wire)
            pet.fields['0x8c4489']='Боец'.encode('cp1251')
            changed=encode_pet_info(pet)
            self.assertEqual(decode_pet_info(changed,human_equipment=pet.human_equipment),pet)
            for length in range(len(changed)):
                with self.assertRaises(PacketError):
                    decode_pet_info(changed[:length],human_equipment=pet.human_equipment)
            with self.assertRaises(PacketError):
                decode_pet_info(changed+b'\0',human_equipment=pet.human_equipment)

    def test_unsupported_and_mismatched_state_rejected(self):
        case=json.loads((ROOT/'evidence/pet_info_native_variants.json').read_text())[0]
        pet=decode_pet_info(b'\x66'+bytes.fromhex(case['body_hex']),human_equipment=True)
        for key,value in [('0x8c4c34',1),('0x8c4cb6',1),('0x8c4d38',1),
                          ('0x8c4d88',1),('0x8c4f74',1),('0x6d0203',2),
                          ('0x8c4489',b'a\0b')]:
            bad=PetInfo(True,{**pet.fields,key:value})
            with self.assertRaises(PacketError):encode_pet_info(bad)
        with self.assertRaises(PacketError):encode_pet_info(PetInfo(False,pet.fields))
        with self.assertRaises(PacketError):encode_pet_info(PetInfo(True,{**pet.fields,'extra':0}))
