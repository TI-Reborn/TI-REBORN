import json,sqlite3,unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path

import test_ability_learning
from tio.ability_progression import AbilityProgression
from tio.abilities import AbilityCatalog,AbilityLevel
from tio.restored_abilities import catalog_with_restored
from tio.protocol.abilities import decode_abilities,encode_ability_request
from tio.protocol.pet_info import decode_pet_info,encode_pet_info

ROOT=Path(__file__).resolve().parents[1]
CYBERNETICS=35
SLOTS='0x8c4a42'  # native reader 8c4a42 stores u8 into PetInfo+0x45.


def raw_catalog():
    data=json.loads((ROOT/'config/abilities.json').read_text(encoding='utf-8'))
    return AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in data['records'])


class RestoredCatalogTests(unittest.TestCase):
    def test_cybernetics_has_four_slot_ranks_with_native_caption(self):
        catalog=catalog_with_restored(raw_catalog())
        rows=[catalog.get(CYBERNETICS,rank) for rank in (1,2,3,4)]
        self.assertEqual([r.number('value') for r in rows],[1,2,3,4])
        self.assertEqual({r.fields['effect_text'] for r in rows},{'m805'})
        self.assertEqual({r.number('levels') for r in rows},{4})

    def test_raw_cfg_import_is_untouched(self):
        self.assertNotIn(CYBERNETICS,{r.ability_id for r in raw_catalog().records})

    def test_overlay_is_idempotent_but_rejects_a_conflicting_definition(self):
        catalog=catalog_with_restored(raw_catalog())
        self.assertIs(catalog_with_restored(catalog),catalog)
        conflicting=AbilityCatalog((*raw_catalog().records,AbilityLevel(CYBERNETICS,1,{'name':'Other','levels':'1','value':'9'})))
        with self.assertRaises(ValueError):catalog_with_restored(conflicting)

    def test_runtime_skills_xml_defines_cybernetics(self):
        node=ET.parse(ROOT/'evidence/skills_diagnostic.xml').getroot().find(f"skill[@id='{CYBERNETICS}']")
        self.assertEqual(node.find('table').text,'1 2 3 4')
        values={e.attrib['key']:e.attrib['val'] for e in node.findall('value')}
        self.assertEqual(values.get('effectText'),'m805')
        self.assertNotIn('operateType',values)


class CyberneticsLearningTests(unittest.TestCase):
    setUp=test_ability_learning.AbilityLearningTests.setUp
    fund=test_ability_learning.AbilityLearningTests.fund

    def level(self,value,account='alice'):
        with closing(sqlite3.connect(self.path)) as db,db:
            packet=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(account,)).fetchone()[0]
            pet=decode_pet_info(packet,human_equipment=True);pet.fields['0x8c4aef']=value
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(pet),account))

    def offers(self,owner=1,account='alice'):
        return {e.ability_id:e.level for e in decode_abilities(self.service.lists(account,owner)[1])[1]}

    def slots(self,replies):
        return decode_pet_info(replies[-1],human_equipment=True).fields[SLOTS]

    def test_offered_to_humans_from_level_four_one_rank_per_level(self):
        self.level(3);self.assertNotIn(CYBERNETICS,self.offers())
        self.level(4);self.assertEqual(self.offers()[CYBERNETICS],1)
        self.fund(100_000)
        self.assertEqual(self.slots(self.service.learn('alice',1,CYBERNETICS)),1)
        self.assertNotIn(CYBERNETICS,self.offers())
        self.level(5);self.assertEqual(self.offers()[CYBERNETICS],2)
        self.assertEqual(self.slots(self.service.learn('alice',1,CYBERNETICS)),2)

    def test_dogs_never_learn_cybernetics(self):
        self.assertNotIn(CYBERNETICS,self.offers(owner=2))

    def test_slots_belong_to_the_learning_account_only(self):
        from tio.passive_stats import project_saved_pet
        for account in ('alice','bob'):self.level(4,account)
        self.fund(100_000);self.offers();self.service.learn('alice',1,CYBERNETICS)
        with closing(sqlite3.connect(self.path)) as db:
            for account,expected in (('alice',1),('bob',0)):
                base=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(account,)).fetchone()[0]
                self.assertEqual(decode_pet_info(base,human_equipment=True).fields[SLOTS],0)
                projected=project_saved_pet(db,account,1,base,True)
                self.assertEqual(decode_pet_info(projected,human_equipment=True).fields[SLOTS],expected)

    def test_saved_slots_require_a_learned_profile(self):
        from tio.passive_stats import project_saved_pet,project_saved_roster
        with closing(sqlite3.connect(self.path)) as db,db:
            base=db.execute("SELECT pet_packet FROM owned_pets WHERE account='bob' AND pet_id=1").fetchone()[0]
            pet=decode_pet_info(base,human_equipment=True)
            pet.fields[SLOTS]=4
            base=encode_pet_info(pet)
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='bob' AND pet_id=1",(base,))
            for legacy in (False,True):
                with self.subTest(legacy=legacy):
                    if legacy:db.execute('DROP TABLE ability_states')
                    single=project_saved_pet(db,'bob',1,base,True)
                    rows=db.execute("SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account='bob'").fetchall()
                    batch=project_saved_roster(db,'bob',rows)[0][2]
                    self.assertEqual(decode_pet_info(single,human_equipment=True).fields[SLOTS],0)
                    self.assertEqual(single,batch)
                    self.assertEqual(db.execute("SELECT pet_packet FROM owned_pets WHERE account='bob' AND pet_id=1").fetchone()[0],base)

    def test_learned_cybernetics_does_not_block_battle_preparation(self):
        from tools.battle_roster_fixture import prepare_actor
        self.level(4);self.fund(100_000);self.offers();self.service.learn('alice',1,CYBERNETICS)
        prepared=prepare_actor(self.path,'alice',1,7,raw_catalog())
        self.assertEqual(prepared.actor_id,1)

    def test_forgetting_cybernetics_closes_the_slots(self):
        service=AbilityProgression.from_workspace(self.path,ROOT)
        self.level(4);self.fund(100_000);service.lists('alice',1)
        service.handle('alice',encode_ability_request(1,CYBERNETICS))
        replies=service.handle('alice',encode_ability_request(1,CYBERNETICS,opcode=0x90))
        self.assertEqual(self.slots(replies),0)


if __name__=='__main__':
    unittest.main()
