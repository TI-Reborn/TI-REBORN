import json
import unittest
from pathlib import Path
from tio.arena_roster import room_soldiers
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo


class ArenaRosterTests(unittest.TestCase):
    def test_saved_level_resource_active_filter_and_limit(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        first=decode_pet_info(bytes.fromhex(data['packet_hex']),human_equipment=True)
        rows=[]
        for owner,level,state,resource in ((1,1,0,1),(2,7,1,2),(3,9,1,1)):
            packet=encode_pet_info(PetInfo(True,{**first.fields,'0x8c43eb':owner,'0x8c4aef':level,'0x8c44a6':state,'0x8c446f':resource}))
            rows.append((owner,packet,b''))
        selected=room_soldiers(rows,1)
        self.assertEqual([(s.level,s.npc_id) for s in selected],[(7,2)])
        self.assertEqual([(s.level,s.npc_id) for s in room_soldiers(rows,3)],[(7,2),(9,1)])
        with self.assertRaises(ValueError): room_soldiers([(99,rows[1][1],b'')],1)
