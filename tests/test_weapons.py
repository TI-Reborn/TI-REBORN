import unittest
from pathlib import Path
import json
from tio.weapons import WeaponCatalog
from tools.import_weapon_catalog import build


class WeaponTests(unittest.TestCase):
    def test_source_values_and_ammo_links(self):
        c=WeaponCatalog()
        self.assertEqual(len({i for i in c.weapons if i not in (65489,321)}),39)
        self.assertEqual((c.weapons[321].damage_base,c.weapons[321].damage_random),(80,10))
        self.assertEqual((c.weapons[65489].damage_base,c.weapons[65489].damage_random,c.weapons[65489].attack_ap),(12,6,4))
        self.assertEqual(len(c.ammunition),13)
        self.assertTrue(c.accepts_ammo(323,317))
        w=c.weapons[301]
        self.assertEqual((w.damage_base,w.damage_random,w.attack_ap,w.ammo_id),(16,8,3,3))
        self.assertIsNone(w.reload_ap)
        for weapon,ammo in ((302,4),(304,7),(306,13),(312,6),(330,5),(338,36),(336,37)):
            self.assertTrue(c.accepts_ammo(weapon,ammo))
            self.assertFalse(c.accepts_ammo(weapon,3))
        self.assertFalse(c.accepts_ammo(333,3))

    def test_import_preserves_missing_reload_and_rejects_dangling_ammo(self):
        raw=b'Section 301: Gun\n{\nitem_id=301\nname=Gun\nweaponType=Light\np_dam=16\nactionPoints=3\nammo_id=3\n}'
        with self.assertRaises(ValueError):build(raw)
        data=build(raw+b'\nSection 3: Ammo\n{\nitem_id=3\nname=Ammo\nitype=ammo\nactionPoints=50\npackamount=50\n}')
        self.assertIsNone(data['weapons']['301']['reload_ap'])
        self.assertEqual(data['ammunition']['3']['source_fields']['actionPoints'],'50')
