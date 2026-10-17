import unittest
import xml.etree.ElementTree as ET
from tio.abilities import AbilityCatalog,AbilityLevel
from tools.build_skills_fixture import build

class SkillsFixtureTests(unittest.TestCase):
    def test_level_tables_and_unknowns(self):
        rows=[]
        for level,value in [(1,80),(2,100)]:
            fields=dict(id='26',name='Bite',levels='2',level=str(level),value=str(value),Active='1',AP='8',Range='1',Target='enemy')
            if level==1:fields['Cooldown']='2'
            rows.append(AbilityLevel(26,level,fields))
        xml,included,excluded=build(AbilityCatalog(rows))
        node=ET.fromstring(xml).find('skill')
        self.assertEqual(node.find('table').text,'80 100')
        values={n.get('key'):n.get('val') for n in node.findall('value')}
        self.assertEqual(values['apConsume'],'8');self.assertEqual(values['target'],'target_one')
        self.assertNotIn('reuseTurns',values)
        self.assertEqual(included[0]['unresolved_per_level']['Cooldown'],['2',None])
        self.assertEqual(excluded,[])

    def test_incomplete_table_not_synthesized(self):
        c=AbilityCatalog([AbilityLevel(3,None,dict(id='3',name='Trader',levels='2'))])
        xml,included,excluded=build(c)
        self.assertEqual(len(ET.fromstring(xml)),0)
        self.assertEqual(included,[]);self.assertEqual(excluded[0]['id'],3)
