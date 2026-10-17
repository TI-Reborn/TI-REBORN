from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from tio.characters import CharacterStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.character_select import encode_character_list,decode_character_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list


class CharacterPreviewTests(unittest.TestCase):
    def test_live_saved_equipment_level_hands_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';store=CharacterStore(path);pets=OwnedPetStore(path)
            fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
            for account,resource in (('alice',1),('bob',2)):
                store.create(account,CharacterCreateRequest(account.encode(),0,(resource,0,0,0)))
                pets.ensure(account,bytes.fromhex(fixture['packet_hex']),encode_item_list(1,()),human=True)
            bob=store.list('bob')
            pet=decode_pet_info(pets.list('alice')[0][1],human_equipment=True)
            def save(items,level):
                with closing(sqlite3.connect(path)) as db,db:
                    db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',
                        (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':level})),encode_item_list(1,tuple(items)),'alice'))
            def item(identity,template,slot,equipped=1):
                return ItemRecord(identity,template,bytes(2),1,equipped,slot,(300,300,300),bytes(4),None,bytes(3))
            equipment=[item(1,101,1),item(2,102,4),item(3,103,8),item(4,301,16),item(5,302,128),item(6,399,0,0)]
            save(equipment,2)
            shown=decode_character_list(encode_character_list(store.list('alice')))[0]
            self.assertEqual(shown.unknown_u8_02,2)
            self.assertEqual(tuple(shown.words[i] for i in (0,6,7,4,5)),(101,102,103,301,302))
            self.assertNotIn(399,shown.words)
            # The saved PetInfo still has old equipment fields: inventory is authoritative.
            save([item(4,301,128),item(5,302,16)],3)
            shown=CharacterStore(path).list('alice')[0]
            self.assertEqual(shown.unknown_u8_02,3)
            self.assertEqual(tuple(shown.words[i] for i in (0,6,7,4,5)),(0,0,0,302,301))
            self.assertEqual(store.list('bob'),bob)
            for special in (0x800,0x1000,0x2000):
                save([item(7,401,special)],3)
                self.assertEqual(store.list('alice')[0].words[6],401)
            save([],4)
            self.assertEqual(store.list('alice')[0].words,(0,)*19)
