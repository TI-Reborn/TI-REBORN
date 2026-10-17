import json,unittest
from pathlib import Path
from tio.matchmaking import SurvivalQueue
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo


class SurvivalQueueTests(unittest.TestCase):
    def roster(self,slots=(1,),level=1):
        f=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet=decode_pet_info(bytes.fromhex(f['packet_hex']),human_equipment=True)
        return tuple((i,encode_pet_info(PetInfo(True,{**pet.fields,'0x8c43eb':i,'0x8c44a6':s,'0x8c4aef':level})),b'') for i,s in enumerate(slots,1))

    def test_search_duplicate_cancel_and_bot_deadline(self):
        now=[0];q=SurvivalQueue(clock=lambda:now[0])
        first=q.join(1,self.roster((1,2,0)))
        self.assertEqual(first.actors,(1,2))
        now[0]=4;self.assertIs(q.join(1,self.roster((1,2,0))),first)
        self.assertIsNone(q.propose(1))
        now[0]=59.999;self.assertIsNone(q.propose(1))
        now[0]=60;self.assertTrue(q.propose(1).uses_bot)
        q.join(2,self.roster((1,2)))
        proposal=q.propose(1);self.assertFalse(proposal.uses_bot)
        self.assertIn(1,q.tickets) # failed scene preparation must not lose search
        q.cancel(1)
        with self.assertRaises(ValueError):q.consume(proposal)
        with self.assertRaises(ValueError):q.join(1,self.roster((1,1)))
        with self.assertRaises(ValueError):q.join(1,self.roster((0,)))

    def test_real_opponent_and_atomic_consume(self):
        now=[0];q=SurvivalQueue(clock=lambda:now[0])
        q.join(1,self.roster());q.join(2,self.roster(level=9))
        q.join(3,self.roster((1,2),level=9))
        now[0]=8;q.join(4,self.roster(level=2))
        proposal=q.propose(1);self.assertEqual(proposal.second.character_id,4)
        q.consume(proposal);self.assertEqual(set(q.tickets),{2,3})
        with self.assertRaises(ValueError):q.consume(proposal)

    def test_manual_bands_and_largest_common_squad(self):
        q=SurvivalQueue(group_wait=0)
        q.join(1,self.roster((1,2,3),level=3))
        q.join(2,self.roster((1,2,3),level=4))
        self.assertIsNone(q.propose(1))
        q.join(3,self.roster((1,),level=1))
        q.join(4,self.roster((1,2),level=2))
        self.assertEqual(q.propose(1).second.character_id,4)
        q.join(5,self.roster((1,2,3),level=1))
        self.assertEqual(q.propose(1).second.character_id,5)
