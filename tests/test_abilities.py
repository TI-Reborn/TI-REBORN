from pathlib import Path
import tempfile,unittest
from tio.abilities import AbilityCatalog


class AbilityTests(unittest.TestCase):
    def parse(self,text):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'abilities.cfg';p.write_text(text,encoding='cp1251')
            return AbilityCatalog.from_cfg(p)

    def test_preserves_explicit_values_and_missing_cooldown(self):
        c=self.parse('Perk 26: Bite\n{\nid=26\nname=Dog Deathbite\nlevel=1\nlevels=4\nAP=8\nCooldown=2\nvalue=80\n}\nPerk 26: Bite2\n{\nid=26\nname=Dog Deathbite\nlevel=2\nlevels=4\nAP=8\nvalue=100\n}')
        self.assertEqual(c.get(26,1).number('Cooldown'),2)
        self.assertIsNone(c.get(26,2).number('Cooldown'))
        self.assertEqual(c.get(26,2).number('AP'),8)
        with self.assertRaises(KeyError):c.get(26,3)

    def test_rejects_conflicting_source(self):
        row='Perk 1: Health\n{\nid=1\nname=Health\nlevel=1\nlevels=4\n}'
        for text in (row+row,row.replace('id=1','id=2'),row.replace('level=1','level=5')):
            with self.assertRaises(ValueError):self.parse(text)

    def test_missing_level_not_invented(self):
        c=self.parse('Perk 3: Trader\n{\nid=3\nname=Trader\nlevels=2\n}')
        self.assertIsNone(c.get(3,None).level)
        with self.assertRaises(KeyError):c.get(3,1)
