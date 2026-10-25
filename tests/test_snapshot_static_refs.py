"""Battle snapshots store unchanged rule catalogues by reference."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import test_ranked_loadout as ranked
from tio import battle_snapshot as codec


def dump(value):
    return codec.dumps(value, clock=lambda: 100., wall=lambda: 200.)


def legacy(value):
    """The previous wire format: every catalogue encoded in full."""
    with patch.object(codec, 'STATIC_CLASSES', ()), patch.object(codec, 'STATIC_ATTRIBUTES', {}):
        return dump(value)


class SnapshotStaticReferenceTests(unittest.TestCase):
    def setUp(self):
        self.case = ranked.RankedLoadoutTests('test_loaned_weapon_fires_and_consumption_never_persists')
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        battle = self.case.start(ranked.join(equipment=((4, 301),)), ranked.join(), journal=True)
        self.data = self.case.hub.journal.data(battle)
        self.combat = battle['field'].combat

    def test_real_battle_snapshot_shrinks_and_old_format_restores_identically(self):
        new, old = dump(self.data), legacy(self.data)
        self.assertLess(len(new), len(old) // 2)
        statics = {n['static'] for n in json.loads(new)['nodes'] if 'static' in n}
        self.assertEqual(statics, set(codec.STATIC_CLASSES))
        self.assertIn('"k":"tio.battle_loot.loot_metadata"', new)
        # Snapshots written before this change restore to the same state.
        for text in (new, old):
            restored, _ = codec.loads(text, rebase=False)
            self.assertEqual(dump(restored), new)
            # Legacy re-encoding is value-identical (frozen WeaponStats shared
            # by actors and the catalogue may become separate equal nodes).
            self.assertEqual(dump(codec.loads(legacy(restored), rebase=False)[0]), new)

    def test_restored_catalogues_are_usable_and_weapon_catalogue_is_owned(self):
        restored, _ = codec.loads(dump(self.data), rebase=False)
        combat = restored['battle']['field'].combat
        self.assertIsNot(combat.catalog, codec.canonical('tio.weapons.WeaponCatalog'))
        self.assertEqual(combat.catalog.weapons[301], self.combat.catalog.weapons[301])
        self.assertIs(combat.armor, codec.canonical('tio.armor.ArmorCatalog'))
        self.assertIs(combat.enhancement_rules, codec.canonical('tio.enhancement.EnhancementRules'))
        self.assertIs(restored['battle']['field'].loot.metadata, codec.canonical('tio.battle_loot.loot_metadata'))

    def test_battle_specific_catalogue_changes_are_kept_in_full(self):
        catalog = self.combat.catalog
        catalog.weapons[301] = replace(catalog.weapons[301], damage_base=77)
        text = dump(self.data)
        self.assertNotIn('"static":"tio.weapons.WeaponCatalog"', text)
        restored, _ = codec.loads(text, rebase=False)
        self.assertEqual(restored['battle']['field'].combat.catalog.weapons[301].damage_base, 77)
        self.assertNotEqual(codec.canonical('tio.weapons.WeaponCatalog').weapons[301].damage_base, 77)

    def test_strict_equality_distinguishes_bool_from_int(self):
        self.assertFalse(codec._equal({'a': True}, {'a': 1}))
        self.assertFalse(codec._equal([1.0], [1]))
        self.assertTrue(codec._equal({'a': (1, [2])}, {'a': (1, [2])}))

    def test_unknown_or_mismatched_static_references_are_rejected(self):
        data = json.loads(dump(self.data))
        node = next(n for n in data['nodes'] if 'static' in n)
        for bad in ('tio.combat.Combat', 'os.system'):
            with self.subTest(bad=bad):
                node['static'] = node['class'] = bad
                with self.assertRaises(ValueError):codec.loads(json.dumps(data), rebase=False)
        text = dump(self.data).replace('"k":"tio.battle_loot.loot_metadata"', '"k":"os.system"')
        self.assertIn('"k":"os.system"', text)
        with self.assertRaises(ValueError):codec.loads(text, rebase=False)


if __name__ == '__main__':
    unittest.main()
