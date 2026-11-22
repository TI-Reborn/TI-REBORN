"""Regression checks for missing faces/fingers after armor catalog conversion."""
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from tools.armor_missing_parts_20261021 import patch,validate,OUT
from tools.normalize_armor_models import normalize

class MissingArmorParts(unittest.TestCase):
 def test_patch_changes_only_render_bindings_and_keeps_pantsu_fix(self):
  before=(OUT/'items-before.xml').read_bytes();after=patch(before);self.assertTrue(validate(before,after)['passed'])
  get=lambda raw,identity:next(i for i in ET.fromstring(raw).iter('item') if i.get('id')==str(identity))
  self.assertEqual(ET.tostring(get(before,206)),ET.tostring(get(after,206)))
  with self.assertRaises(AssertionError):patch(after)

 def test_normalization_retains_hands_instead_of_legacy_arm_names(self):
  for identity,part,model in ((223,'chest','armor_battle_heavy_torso'),(263,'complexarmor','armor_fea'),(264,'complexarmor','armor_fease')):
   with self.subTest(item=identity):
    fields=dict(item_id=str(identity),itype='armor',bodypart=part,model_1=model,durability='300',p_def='15')
    normalize(fields)
    self.assertEqual(fields['w_model_2'],'chr_woman_hands');self.assertEqual(fields['w_texture_2'],'chr_woman_body.jpg')
    self.assertEqual(fields['model_2'],'chr_man_hands' if identity==223 else 'chr_woman_hands')
    self.assertEqual(fields['p_def'],'15');self.assertEqual(fields['durability'],'300')

 def test_same_open_helmet_mesh_has_same_face_policy(self):
  fields=dict(item_id='208',itype='armor',bodypart='head',model_1='helmet',showface='0')
  normalize(fields);self.assertEqual(fields['showface'],'1')
  self.assertEqual(fields['model_1'],'man_armor_combat_light_head')

 def test_regeneration_keeps_pantsu_legs(self):
  fields=dict(item_id='206',itype='armor',bodypart='legs',model_1='pantsukudasai')
  normalize(fields);self.assertEqual(fields['model_2'],'chr_man_legs');self.assertEqual(fields['w_model_2'],'chr_woman_legs')
