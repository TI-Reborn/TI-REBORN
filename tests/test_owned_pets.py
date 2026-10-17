import json
import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo

class OwnedPetTests(unittest.TestCase):
    def test_starter_name_from_character_repairs_existing_without_reset(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        seed=bytes.fromhex(data['packet_hex']);inventory=bytes.fromhex(data['inventory_packet_hex'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';store=OwnedPetStore(path)
            saved,inv=store.ensure('alice',seed,inventory,human=True)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute("CREATE TABLE characters(account TEXT, slot INTEGER, name BLOB, request BLOB DEFAULT X'1150726f626500000000000000')")
                db.executemany('INSERT INTO characters(account,slot,name) VALUES (?,1,?)', [('alice',b'Sanjok'),('bob',b'Bob')])
            actual,actual_inv=store.ensure('alice',seed,encode_item_list(1,()),human=True)
            before=decode_pet_info(saved,human_equipment=True).fields
            after=decode_pet_info(actual,human_equipment=True).fields
            self.assertEqual(after,{**before,'0x8c4489':b'Sanjok'})
            self.assertEqual(actual_inv,inv)
            self.assertEqual(store.ensure('alice',seed,inventory,human=True),(actual,actual_inv))
            bob,_=store.ensure('bob',seed,inventory,human=True)
            self.assertEqual(decode_pet_info(bob,human_equipment=True).fields['0x8c4489'],b'Bob')
            recruit=encode_pet_info(PetInfo(True,{**before,'0x8c43eb':2}))
            returned,_=store.ensure('alice',recruit,encode_item_list(2,()),human=True)
            self.assertEqual(decode_pet_info(returned,human_equipment=True).fields['0x8c4489'],b'ProbeNew')

    def test_custom_starter_name_is_preserved(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        original=decode_pet_info(bytes.fromhex(data['packet_hex']),human_equipment=True)
        seed=encode_pet_info(PetInfo(True,{**original.fields,'0x8c4489':b'Custom'}))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';store=OwnedPetStore(path)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute("CREATE TABLE characters(account TEXT, slot INTEGER, name BLOB, request BLOB DEFAULT X'1150726f626500000000000000')")
                db.execute('INSERT INTO characters(account,slot,name) VALUES (?,1,?)',('alice',b'Sanjok'))
            returned,_=store.ensure('alice',seed,encode_item_list(1,()),human=True)
            self.assertEqual(decode_pet_info(returned,human_equipment=True).fields['0x8c4489'],b'Custom')

    def test_multi_pet_roster_and_account_isolation(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        first=bytes.fromhex(data['packet_hex'])
        original=decode_pet_info(first,human_equipment=True)
        second=encode_pet_info(PetInfo(True,{**original.fields,'0x8c43eb':2,'0x8c4489':b'Second'}))
        with tempfile.TemporaryDirectory() as folder:
            store=OwnedPetStore(Path(folder)/'state.db')
            store.ensure('alice',second,encode_item_list(2,()),human=True)
            store.ensure('alice',first,encode_item_list(1,()),human=True)
            store.ensure('bob',first,bytes.fromhex(data['inventory_packet_hex']),human=True)
            self.assertEqual([r[0] for r in store.list('alice')],[1,2])
            self.assertEqual(store.inventory('alice',2),encode_item_list(2,()))
            self.assertIsNone(store.inventory('bob',2))
            self.assertEqual(store.list('missing'),())
            self.assertNotEqual(store.inventory('alice',1),store.inventory('bob',1))

    def test_persistence_and_no_reset(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet,inventory=bytes.fromhex(data['packet_hex']),bytes.fromhex(data['inventory_packet_hex'])
        # Legacy rank=0 becomes Recruit without changing inventory/other fields.
        from tio.ranks import project
        pet=project(pet,True,0)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'
            self.assertEqual(OwnedPetStore(path).ensure('alice',pet,inventory,human=True),(pet,inventory))
            # A later seed with an empty inventory cannot erase saved items.
            self.assertEqual(OwnedPetStore(path).ensure('alice',pet,encode_item_list(1,()),human=True),(pet,inventory))
            self.assertEqual(OwnedPetStore(path).ensure('bob',pet,encode_item_list(1,()),human=True),(pet,encode_item_list(1,())))
            with self.assertRaises(ValueError):
                OwnedPetStore(path).ensure('alice',pet,encode_item_list(2,()),human=True)
            self.assertEqual(OwnedPetStore(path).ensure('alice',pet,inventory,human=True),(pet,inventory))
