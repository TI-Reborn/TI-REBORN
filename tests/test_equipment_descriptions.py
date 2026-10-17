import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tools.normalize_equipment_effects import normalize, EFFECTS


class EquipmentDescriptionTests(unittest.TestCase):
    def test_exact_four_and_cleanup_previous_patch(self):
        self.assertEqual(set(EFFECTS),{256,262,264,341})
        for ident,stat in ((254,'melee'),(263,'maxload')):
            item=ET.fromstring(f'<item id="{ident}"><value key="itype" val="armor"/><for><add stat="pdef" val="220"/><add stat="{stat}" val="25"/></for></item>')
            normalize(item)
            self.assertIsNone(item.find(f"for/add[@stat='{stat}']"))
            self.assertEqual(item.find("for/add[@stat='pdef']").get('val'),'220')
            self.assertEqual(item.find("value[@key='type']").get('val'),'armor')

    def test_catalog_effects_and_other_stats_unchanged(self):
        root=ET.parse(Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml').getroot()
        for item in root:
            before=ET.tostring(item)
            changed=normalize(item)
            self.assertEqual(ET.tostring(item),before)
            if changed:
                stat,val=EFFECTS[int(item.get('id'))]
                nodes=item.findall(f"for/add[@stat='{stat}']")
                self.assertEqual(len(nodes),1)
                self.assertEqual(nodes[0].get('val'),val)

    def test_preserves_armor_and_weapon_properties(self):
        for ident in EFFECTS:
            item=ET.fromstring(f'<item id="{ident}"><for><add stat="pdef" val="220"/><set stat="patk" val="35"/></for></item>')
            normalize(item);normalize(item)
            self.assertEqual(item.find("for/add[@stat='pdef']").get('val'),'220')
            self.assertEqual(item.find("for/set[@stat='patk']").get('val'),'35')
            self.assertEqual(len(item.find('for')),3)
