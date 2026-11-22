import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from tools.normalize_armor_models import normalize,MODELS


class ArmorModelTests(unittest.TestCase):
    def test_installed_resources_for_all_supported_armor(self):
        root=ET.parse(Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml').getroot()
        checked=[]
        for item in root.iter('item'):
            v={x.get('key'):x.get('val') for x in item.findall('value')}
            if v.get('itype')!='armor' or int(item.get('id'))>=65000 or v.get('freaks_only')=='1':continue
            with self.subTest(item=item.get('id')):
                self.assertIn('model_1',v)
                if v.get('dogs_only')!='1':self.assertIn('w_model_1',v)
                for k,value in v.items():
                    if k.startswith(('model_','w_model_')):self.assertTrue((MODELS/(value+'.mdjx')).is_file(),value)
                    elif k.startswith(('texture_','w_texture_','mask_','w_mask_')):self.assertTrue((MODELS/value).is_file(),value)
            checked.append(int(item.get('id')))
        self.assertTrue({243,251,252,253,255,265,266}.issubset(checked))

    def test_legacy_parts_removed_and_gender_models_selected(self):
        fields=dict(item_id='252',itype='armor',bodypart='chest',model_1='armor_battle_heavy_se_torso',
                    model_2='armor_battle_heavy_se_arms',model_3='armor_battle_heavy_se_hands',texture_1='battle_se.jpg',p_def='85')
        normalize(fields)
        self.assertEqual(fields['model_1'],'man_armor_battlese_chest')
        self.assertEqual(fields['w_model_1'],'woman_armor_battlese_chest')
        self.assertEqual(fields['texture_1'],'armor_battlese.jpg')
        self.assertEqual(fields['model_2'],'chr_man_hands');self.assertNotIn('model_3',fields)
        self.assertEqual(fields['w_model_2'],'chr_woman_hands')
        self.assertEqual(fields['p_def'],'85')
