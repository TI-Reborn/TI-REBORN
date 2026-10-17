"""Bounded tests for native state/slice packing and the approved source guard."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("city_assets", ROOT / "tools" / "build_contracts_city_assets.py")
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


class ContractsCityAssetsTests(unittest.TestCase):
    def test_native_state_order_and_unused_column(self):
        colours = [(120, 0, 0, 255), (0, 120, 0, 255), (0, 0, 120, 255), (120, 120, 0, 255)]
        atlas = assets.pack_button([Image.new("RGBA", (896, 200), colour) for colour in colours])
        self.assertEqual((100, 100), atlas.size)
        for state, colour in enumerate(colours):
            self.assertEqual(colour, atlas.getpixel((38, state * 25 + 12)))
        self.assertEqual((0, 0), atlas.crop((75, 0, 100, 100)).getchannel("A").getextrema())

    def test_repeat_middle_is_exact_at_all_widths_and_cap_boundaries(self):
        source = assets.verified_source(assets.SOURCE)
        atlas = assets.pack_button([assets.source_piece(source, name) for name in assets.STATE_ORDER])
        for state in range(4):
            for width in (50, 51, 74, 224, 360):
                button = assets.assemble_button(atlas, (width, 25), state)
                left = atlas.crop((0, state * 25, 25, state * 25 + 25))
                right = atlas.crop((50, state * 25, 75, state * 25 + 25))
                self.assertEqual(left.tobytes(), button.crop((0, 0, 25, 25)).tobytes())
                self.assertEqual(right.tobytes(), button.crop((width - 25, 0, width, 25)).tobytes())
                for x in range(25, width - 25):
                    self.assertEqual(button.crop((x, 0, x + 1, 25)).tobytes(), atlas.crop((25, state * 25, 26, state * 25 + 25)).tobytes())

    def test_states_preserve_pressed_geometry_and_independent_source_art(self):
        source = assets.verified_source(assets.SOURCE)
        states = [assets.source_piece(source, name) for name in assets.STATE_ORDER]
        atlas = assets.pack_button(states)
        rows = [atlas.crop((0, state * 25, 75, state * 25 + 25)) for state in range(4)]
        self.assertEqual(4, len({row.tobytes() for row in rows}))
        # The pressed inset reverses the inner bevel profile. Multiplying the
        # normal state's brightness could not turn its ridge into a groove.
        normal_ray = rows[0].crop((25, 0, 26, 25)).convert("L")
        pressed_ray = rows[2].crop((25, 0, 26, 25)).convert("L")
        self.assertGreater(normal_ray.getpixel((0, 4)), normal_ray.getpixel((0, 3)))
        self.assertGreater(normal_ray.getpixel((0, 4)), normal_ray.getpixel((0, 5)))
        self.assertLess(pressed_ray.getpixel((0, 4)), pressed_ray.getpixel((0, 3)))
        self.assertLess(pressed_ray.getpixel((0, 4)), pressed_ray.getpixel((0, 5)))

    def test_frame_indices_alpha_and_icon_aspect(self):
        source = assets.verified_source(assets.SOURCE)
        frame = assets.pack_frame(assets.source_piece(source, "frame"))
        self.assertEqual((128, 128), frame.size)
        self.assertEqual((0, 0), frame.crop((32, 32, 64, 64)).getchannel("A").getextrema())
        self.assertEqual((0, 0), frame.crop((96, 0, 128, 128)).getchannel("A").getextrema())
        self.assertEqual((0, 0), frame.crop((0, 96, 128, 128)).getchannel("A").getextrema())
        for name in ("contracts_icon", "group_icon"):
            icon = assets.pack_icon(assets.source_piece(source, name))
            self.assertEqual((32, 32), icon.size)
            self.assertGreater(icon.getchannel("A").getextrema()[1], 200)
        self.assertEqual((0, 0), assets.pack_icon(assets.source_piece(source, "group_icon")).crop((0, 0, 32, 3)).getchannel("A").getextrema())

    def test_pinned_source_rejects_mutation_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            tampered = temporary / "source.png"
            tampered.write_bytes(assets.SOURCE.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "approved immutable"):
                assets.build(tampered, temporary / "runtime", temporary / "qa", temporary / "manifest.json")
            self.assertFalse((temporary / "runtime").exists())

    def test_four_resources_deterministic_and_source_unchanged(self):
        before = assets.sha256(assets.SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            first = assets.build(assets.SOURCE, temporary / "first", temporary / "qa-first", temporary / "manifest-first.json")
            second = assets.build(assets.SOURCE, temporary / "second", temporary / "qa-second", temporary / "manifest-second.json")
            self.assertEqual(first, second)
            self.assertEqual(4, len(first["files"]))
            self.assertEqual(["base/pda/contracts_button.png", "base/pda/contracts_frame.png", "base/pda/contracts_icon.png", "base/pda/group_icon.png"], [entry["path"] for entry in first["files"]])
            for entry in first["files"]:
                self.assertEqual(entry["sha256"], assets.sha256(temporary / "first" / entry["path"]))
                self.assertIsNone(entry["before_sha256"])
        self.assertEqual(before, assets.sha256(assets.SOURCE))


if __name__ == "__main__":
    unittest.main()
