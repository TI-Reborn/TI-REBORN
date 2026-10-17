import hashlib
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from deploy.client_russian_encoding import patch, ORIGINAL_SHA, PATCHED_SHA, OFFSET, PATCHED

ROOT=Path(__file__).resolve().parents[1]
CLIENT=Path(r'C:\Program Files (x86)\TIOnline')


class RussianEncodingTests(unittest.TestCase):
    def test_unknown_file_rejected(self):
        with self.assertRaises(ValueError):patch(b'unknown executable')

    @unittest.skipUnless((CLIENT/'silver.dll').exists(),'original client unavailable')
    def test_known_binary_patch_is_idempotent_and_changes_only_initialization(self):
        before=(CLIENT/'silver.dll').read_bytes()
        self.assertEqual(hashlib.sha256(before).hexdigest(),ORIGINAL_SHA)
        after=patch(before)
        self.assertEqual(hashlib.sha256(after).hexdigest(),PATCHED_SHA)
        self.assertEqual(after[:OFFSET],before[:OFFSET])
        self.assertEqual(after[OFFSET:OFFSET+5],PATCHED)
        self.assertEqual(after[OFFSET+5:],before[OFFSET+5:])
        self.assertEqual(patch(after),after)

    @unittest.skipUnless((CLIENT/'base/russian.lng').exists(),'Russian localization unavailable')
    def test_every_delivered_ability_effect_resolves_and_survives_1251(self):
        language=dict(line.split('=',1) for line in (CLIENT/'base/russian.lng').read_text(encoding='cp1251').splitlines() if '=' in line)
        skills=ET.parse(ROOT/'evidence/skills_diagnostic.xml').getroot()
        checked=[]
        for skill in skills:
            for value in skill.findall('value'):
                if value.get('key')!='effectText':continue
                with self.subTest(skill=skill.get('id')):
                    text=language[value.get('val')]
                    self.assertNotIn('??',text)
                    self.assertEqual(text.encode('cp1251').decode('cp1251'),text)
                    checked.append(int(skill.get('id')))
        self.assertTrue({1,2,12,20,21,22,24}.issubset(checked))
        text=language['m188']
        self.assertIn('?',text.encode('cp1252',errors='replace').decode('cp1252'))
