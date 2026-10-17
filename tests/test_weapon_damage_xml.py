import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from tio.weapons import WeaponCatalog
from tools.normalize_weapon_xml import normalize


class WeaponDamageXmlTests(unittest.TestCase):
    def test_all_source_weapon_damage_and_idempotent_normalization(self):
        root=ET.parse(Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml').getroot()
        items={int(i.get('id')):i for i in root}
        for identity,w in WeaponCatalog().weapons.items():
            with self.subTest(weapon=identity):
                item=items[identity]
                self.assertEqual(item.find("for/set[@stat='patk']").get('val'),str(w.damage_base))
                self.assertEqual(item.find("for/add[@stat='patk']").get('val'),str(w.damage_random))
                source=WeaponCatalog().sources[identity]
                self.assertEqual(item.find("value[@key='damageFade']").get('val'),source.get('damage_fade','100'))
                for stat,key,default in (('accuracy','accuracy','100'),('accuracyGain','accuracy_gain_amount','0')):
                    self.assertEqual(float(item.find(f"for/add[@stat='{stat}']").get('val')),int(source.get(key,default))/100)
                before=ET.tostring(item)
                fields={e.get('key'):e.get('val') for e in item.findall('value')}
                fields['item_id']=str(identity)
                normalize(item,fields)
                self.assertEqual(ET.tostring(item),before)
        self.assertIsNone(items[9].find("for/set[@stat='patk']"))
