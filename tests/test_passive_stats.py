import json,unittest
from pathlib import Path
from tio.passive_stats import project_health
from tio.ability_learning import AbilityLearning
from tio.protocol.pet_info import PetInfo,decode_pet_info,encode_pet_info
from tio.protocol.abilities import AbilityEntry
import test_ability_learning

class PassiveStatsTests(unittest.TestCase):
    setUp=test_ability_learning.AbilityLearningTests.setUp
    credits=test_ability_learning.AbilityLearningTests.credits

    def test_human_and_dog_defense_saved_projection(self):
        from tio.owned_pets import OwnedPetStore
        store=OwnedPetStore(self.path)
        for owner,ability,human in ((1,6,True),(2,15,False)):
            baseline=next(p for i,p,_ in store.list('alice') if i==owner)
            base=decode_pet_info(baseline,human_equipment=human)
            self.service.lists('alice',owner)
            reply=self.service.learn('alice',owner,ability)[-1]
            result=decode_pet_info(reply,human_equipment=human)
            self.assertEqual(result.fields['0x8c4ac5'],base.fields['0x8c4ac5']+self.service.catalog.get(ability,1).number('value'))
            self.assertEqual(result.fields['0x8c4ab1'],base.fields['0x8c4ab1'])
            for _ in range(2):self.assertEqual(next(p for i,p,_ in store.list('alice') if i==owner),reply)

    def test_carry_bonus_and_health_compose_without_accumulation(self):
        from tio.owned_pets import OwnedPetStore
        store=OwnedPetStore(self.path)
        original=decode_pet_info(store.list('alice')[0][1],human_equipment=True)
        for ability in (1,2):
            self.service.lists('alice',1)
            replies=self.service.learn('alice',1,ability)
        for _ in range(3):
            result=store.list('alice')[0][1]
            self.assertEqual(result,replies[-1])
            pet=decode_pet_info(result,human_equipment=True)
            self.assertEqual(pet.fields['0x8c4a07'],original.fields['0x8c4a07']+5)
            self.assertEqual(pet.fields['0x8c4b57'],original.fields['0x8c4b57']+80)
    def test_health_projection_relogin_no_accumulation(self):
        from tio.owned_pets import OwnedPetStore
        store=OwnedPetStore(self.path)
        baseline=store.list('alice')[0][1]
        base=decode_pet_info(baseline,human_equipment=True)
        self.service.lists('alice',1)
        replies=self.service.learn('alice',1,1)
        updated=decode_pet_info(replies[-1],human_equipment=True)
        self.assertEqual(updated.fields['0x8c4a07'],base.fields['0x8c4a07']+5)
        self.assertEqual(updated.fields['0x8c4ab1'],base.fields['0x8c4ab1'])
        for _ in range(3):self.assertEqual(store.list('alice')[0][1],replies[-1])
        self.assertEqual(store.list('bob')[0][1],baseline)

    def test_dog_health_rank_replaces_prior_bonus(self):
        from tio.owned_pets import OwnedPetStore
        store=OwnedPetStore(self.path);base=decode_pet_info(store.list('alice')[1][1],human_equipment=False)
        for rank in (1,2):
            self.service.lists('alice',2);replies=self.service.learn('alice',2,16)
            pet=decode_pet_info(replies[-1],human_equipment=False)
            self.assertEqual(pet.fields['0x8c4a07'],base.fields['0x8c4a07']+self.service.catalog.get(16,rank).number('value'))

    def test_overflow_rolls_back_purchase(self):
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.path)) as db,db:
            packet=db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
            pet=decode_pet_info(packet,human_equipment=True)
            packet=encode_pet_info(PetInfo(True,{**pet.fields,'0x8c4a07':65535}))
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",(packet,))
        self.service.lists('alice',1)
        with self.assertRaises(ValueError):self.service.learn('alice',1,1)
        self.assertEqual(self.credits(),10000)
        self.assertEqual(self.service.state.read('alice',1),(0,()))
