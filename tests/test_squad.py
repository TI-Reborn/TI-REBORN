import json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from tio.squad import SquadStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_state import encode_squad_slot,decode_squad_slot


class SquadTests(unittest.TestCase):
    def test_duplicate_repair_assignment_and_persistence(self):
        root=Path(__file__).resolve().parents[1]
        template=decode_pet_info(bytes.fromhex(json.loads((root/'evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'s.db';owned=OwnedPetStore(path)
            for i in (1,2,3):
                p=encode_pet_info(PetInfo(True,{**template.fields,'0x8c43eb':i,'0x8c44a6':1}))
                owned.ensure('alice',p,encode_item_list(i,()),human=True)
            store=SquadStore(path)
            def states():return [decode_pet_info(p,human_equipment=True).fields['0x8c44a6'] for _,p,_ in owned.list('alice')]
            self.assertEqual(states(),[1,0,0])
            self.assertEqual(decode_squad_slot(encode_squad_slot(2,2)),(2,2))
            with self.assertRaises(ValueError):store.assign('alice',2,1)
            with self.assertRaises(ValueError):store.assign('bob',2,2)
            self.assertEqual(states(),[1,0,0])
            store.assign('alice',2,2);store.assign('alice',3,3)
            self.assertEqual(states(),[1,2,3])
            store.assign('alice',2,0)
            SquadStore(path)
            self.assertEqual(states(),[1,0,3])
