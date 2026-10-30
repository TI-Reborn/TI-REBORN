"""The v3 layout can be rebuilt from either supported catalogue generation."""
from copy import deepcopy
from pathlib import Path
import unittest

from tio.locations import TOWNS
from tio.world_completion import policy
from tools.prepare_world_completion_catalog import checked_policy, merge, rows, values


class CurrentWorldCatalogTests(unittest.TestCase):
    def test_current_rectangular_policy_is_accepted(self):
        self.assertEqual(checked_policy(policy()), policy())

    def test_current_catalog_rebuild_keeps_flags_and_updates_all_bounds(self):
        source = (Path(__file__).resolve().parents[1] /
                  'evidence/zones_diagnostic.xml').read_bytes()
        result = rows(merge(source, policy()), 22)
        before = rows(source, 22)
        for town, bounds in TOWNS.items():
            actual = values(result[town])
            self.assertEqual(tuple(int(actual[k]) for k in ('x1','y1','x2','y2')), bounds)
            if town not in (4,7,10,18,19,20,21,22):
                for key, value in values(before[town]).items():
                    if key not in ('x1','y1','x2','y2','size'):
                        self.assertEqual(actual[key], value)

    def test_original_seventeen_row_catalog_can_be_upgraded(self):
        from tools.prepare_world_completion_catalog import ROW
        source = (Path(__file__).resolve().parents[1]/'evidence/zones_diagnostic.xml').read_bytes()
        old = ROW.sub(lambda m: m[0] if int(m[1]) <= 17 else b'',source)
        self.assertEqual(len(rows(merge(old,policy()),22)),22)

    def test_invalid_bounds_still_fail(self):
        bad = deepcopy(policy())
        bad['locations'][0]['bounds'] = [1,2,1,3]
        with self.assertRaises(ValueError):
            checked_policy(bad)
