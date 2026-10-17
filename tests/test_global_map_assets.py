"""Meaningful asset identity, authoritative geometry and viewport regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import build_global_map_assets as tool
from tio.locations import TOWNS, center, town_at


class GlobalMapAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((tool.SOURCE / "catalog.json").read_bytes())
        cls.authority = tool.DEFAULT_AUTHORITY if tool.DEFAULT_AUTHORITY.exists() else None
        cls.layout = tool.make_layout(cls.catalog, authority_zones=cls.authority)
        cls.objects = {r["id"]: r for r in cls.layout["objects"]}

    def test_complete_id_contract_and_disabled_texas_has_no_game_target(self):
        self.assertEqual(list(self.objects), list(range(1, 23)))
        self.assertEqual(set(TOWNS), set(range(2, 23)))
        texas = self.objects[1]
        self.assertTrue(texas["decorative_only"])
        self.assertFalse(texas["pickable"])
        self.assertFalse(texas["authority_enabled"])
        self.assertTrue(texas["respect_native_enabled"])
        self.assertIsNone(town_at(*texas["draw_center_world"]))

    def test_native_texture_cache_keys_are_unique_and_do_not_alias_legacy_assets(self):
        images = [self.layout["terrain"], *self.objects.values()]
        keys = [Path(r["filename"]).stem.casefold() for r in images]
        self.assertEqual(len(set(keys)), 23)
        self.assertTrue(all(k.startswith("gm-v2-") for k in keys))
        self.assertTrue(set(keys).isdisjoint({"terrain", "denver", "new-york", "military-zone"}))
        self.assertEqual(self.objects[2]["source_file"], "objects/denver.png")
        self.assertEqual(self.objects[2]["filename"], "gm-v2-denver.png")

    def test_every_live_object_uses_authoritative_bounds_and_arrival_center(self):
        for identity, bounds in TOWNS.items():
            with self.subTest(identity=identity):
                row = self.objects[identity]
                self.assertEqual(row["source_bounds_world"], list(bounds))
                self.assertEqual(row["draw_center_world"], list(center(identity)))
                self.assertEqual(town_at(*row["draw_center_world"]), identity)
                self.assertTrue(row["pickable"])
        self.assertEqual(self.objects[11]["draw_center_world"], [73, 7])
        self.assertEqual(self.objects[11]["source_center_world"], [73, 7.5])

    def test_visual_sizes_are_bounded_and_inherited_colliding_sites_stay_distinct(self):
        for identity, row in self.objects.items():
            width = row["source_bounds_world"][2] - row["source_bounds_world"][0]
            height = row["source_bounds_world"][3] - row["source_bounds_world"][1]
            expected = 12 if identity in (12, 16) else round(min(width, height) * 0.8, 6) if row["kind"] == "city" else 16
            self.assertEqual((row["world_width"], row["world_height"]), (expected, expected))
            for container in (row["source_bounds_world"], row["native_bounds_world"]):
                a = row["draw_bounds_world"]
                self.assertGreaterEqual(a[0], container[0]); self.assertGreaterEqual(a[1], container[1])
                self.assertLessEqual(a[2], container[2]); self.assertLessEqual(a[3], container[3])
        self.assertTrue(tool.intersect(TOWNS[12], TOWNS[16]))
        self.assertEqual(town_at(258, -163), 16)
        self.assertFalse(tool.intersect(self.objects[12]["draw_bounds_world"], self.objects[16]["draw_bounds_world"]))
        self.assertEqual(self.objects[16]["draw_bounds_world"][0] - self.objects[12]["draw_bounds_world"][2], 2)
        self.assertFalse(tool.intersect(TOWNS[11], TOWNS[15]))

    def test_world_geometry_drift_duplicate_ids_and_unsafe_paths_fail_before_packaging(self):
        for case in ("drift", "duplicate", "path"):
            modified = deepcopy(self.catalog)
            if case == "drift": modified["locations"][11]["bounds_world"][0] -= 1
            elif case == "duplicate": modified["locations"][21]["id"] = 21
            else: modified["locations"][0]["object_asset"] = "../texas.png"
            with self.subTest(case=case), self.assertRaises(ValueError):
                tool.make_layout(modified, authority_zones=self.authority)

    def test_viewport_projection_preserves_full_world_and_all_location_centers(self):
        viewports = [(0, 0, 1920, 1080), (0, 0, 2560, 1440), (0, 0, 3840, 2160),
                     (0, 0, 1280, 1024), (0, 70, 1920, 1010), (233, 50, 1454, 980)]
        points = [(-512, -512), (511, 511), (0, 0), *(r["draw_center_world"] for r in self.objects.values())]
        for viewport in viewports:
            for ui_percent in (100, 125, 150, 200):
                logical = tuple(v * 100 / ui_percent for v in viewport)
                for point in points:
                    physical = tool.project(point, viewport)
                    ui = tool.project(point, logical)
                    self.assertAlmostEqual(ui[0] * ui_percent / 100, physical[0], places=9)
                    self.assertAlmostEqual(ui[1] * ui_percent / 100, physical[1], places=9)
                    recovered = tool.unproject(physical, viewport)
                    self.assertAlmostEqual(recovered[0], point[0], places=9)
                    self.assertAlmostEqual(recovered[1], point[1], places=9)
        self.assertEqual(tool.project((-512, -512), (233, 50, 1454, 980)), (233, 50))
        self.assertEqual(tool.project((512, 512), (233, 50, 1454, 980)), (1687, 1030))

    def test_packaged_23_pngs_are_original_bytes_and_layout_is_deterministic(self):
        before = {p.relative_to(tool.SOURCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in tool.SOURCE.rglob("*.png")}
        with tempfile.TemporaryDirectory(prefix="tio-global-map-assets-") as temporary:
            output = Path(temporary) / "candidate"
            first = tool.build(output, authority_zones=self.authority)
            layout_raw = (output / tool.RESOURCE_DIR / "layout.json").read_bytes()
            second = tool.build(output, authority_zones=self.authority)
            self.assertEqual(first, second)
            self.assertEqual(layout_raw, (output / tool.RESOURCE_DIR / "layout.json").read_bytes())
            self.assertEqual(first["png_count"], 23)
            self.assertEqual(first["object_count"], 22)
            self.assertEqual(len(list((output / tool.RESOURCE_DIR).glob("*.png"))), 23)
            for row in first["files"]:
                original = (tool.SOURCE / row["source"]).read_bytes()
                candidate = (output / row["path"]).read_bytes()
                self.assertEqual(candidate, original)
                self.assertEqual(hashlib.sha256(candidate).hexdigest(), row["sha256"])
                self.assertTrue(row["copy_byte_for_byte"])
            self.assertFalse(first["software_pixel_edits"])
            self.assertFalse(first["runtime_world_policies_changed"])
            self.assertFalse(first["installed_client_changed"])
            self.assertFalse(first["database_opened"])
        after = {p.relative_to(tool.SOURCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in tool.SOURCE.rglob("*.png")}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
