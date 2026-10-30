import json,unittest
from pathlib import Path

from tio.ability_prices import PricePolicy

ROOT=Path(__file__).resolve().parents[1]
CONFIG=dict(base_prices={'1':150,'26':400},rank_multipliers=[1,3,8,20],surcharge_percent_per_learned_rank=5)


class PricePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy=PricePolicy.from_config(CONFIG)

    def test_rank_multiplier_without_learned_ranks(self):
        self.assertEqual([self.policy.price(1,rank,0) for rank in (1,2,3,4)],[150,450,1200,3000])

    def test_each_learned_rank_adds_surcharge_rounded_up(self):
        self.assertEqual(self.policy.price(1,2,1),473)
        self.assertEqual(self.policy.price(26,1,3),460)

    def test_unknown_ability_or_rank_is_rejected(self):
        for ability,rank in ((2,1),(1,0),(1,5)):
            with self.assertRaises(ValueError):self.policy.price(ability,rank,0)
        with self.assertRaises(ValueError):self.policy.price(1,1,-1)

    def test_invalid_policy_is_rejected(self):
        for change in (dict(base_prices={'1':0}),dict(rank_multipliers=[]),dict(rank_multipliers=[1,True]),
                       dict(surcharge_percent_per_learned_rank=-1),dict(base_prices={'x':1})):
            with self.assertRaises(ValueError):PricePolicy.from_config({**CONFIG,**change})

    def test_price_beyond_wire_field_is_rejected(self):
        policy=PricePolicy.from_config({**CONFIG,'base_prices':{'1':0xffffffff}})
        with self.assertRaises(ValueError):policy.price(1,2,0)

    def test_every_human_and_dog_perk_rank_has_a_price(self):
        data=json.loads((ROOT/'config/ability_learning.json').read_text(encoding='utf-8'))
        policy=PricePolicy.from_config(data['learning_prices'])
        catalog=json.loads((ROOT/'config/abilities.json').read_text(encoding='utf-8'))['records']
        for ability in data['human_skills']+data['dog_skills']:
            for rank in sorted({r['level'] or 1 for r in catalog if r['id']==ability}):
                self.assertGreater(policy.price(ability,rank,0),0)


if __name__=='__main__':
    unittest.main()
