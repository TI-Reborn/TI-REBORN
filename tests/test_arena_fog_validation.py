import json
import struct
import unittest
from pathlib import Path
from tools.arena_fog_validation import validate_fog_tile, published_fog_scene

ROOT = Path(__file__).resolve().parents[1]


class FogValidationTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT/'assets/arena-surroundings-v2/client-overlay/base/setting/arena_surroundings/as_rv_2_38_p0000.t'
        self.raw = self.path.read_bytes()

    def test_native_tint_preserves_all_structural_guards(self):
        result = validate_fog_tile(self.raw)
        self.assertEqual(result['native_vertex_argb'], 'ffb1b1b1')
        self.assertEqual(result['native_alpha'], 255)

    def test_rejects_wrong_color_opacity_or_interactions(self):
        for offset, value in ((52, 0xffffff), (52, 0x4a4a4a), (56, 177), (340, 1)):
            with self.subTest(offset=offset, value=value):
                changed = bytearray(self.raw)
                struct.pack_into('<I', changed, offset, value)
                with self.assertRaises(AssertionError):
                    validate_fog_tile(bytes(changed))

    def test_rejects_foreground_or_uv_geometry_changes(self):
        for offset in (28, 60, 68, 69, 334, 539):
            with self.subTest(offset=offset):
                changed = bytearray(self.raw)
                changed[offset] ^= 1
                with self.assertRaises(AssertionError):
                    validate_fog_tile(bytes(changed))

    def test_manifest_is_version_bound(self):
        with self.assertRaises(AssertionError):
            published_fog_scene('unused', {'version':'2026.10.07.1'}, 'as_rv_2_38', 38,
                                fetch=lambda _: self.fail('Wrong version reached a resource fetch'))

    def test_entire_inventory_only_changes_three_color_bytes(self):
        proof = json.loads((ROOT/'assets/arena-surroundings-v2/fog-proof.json').read_text('utf-8'))
        self.assertEqual(len(proof['changes']), 552)
        for record in proof['changes']:
            old = (ROOT/'assets/arena-surroundings-v1/client-overlay'/record['path']).read_bytes()
            new = (ROOT/'assets/arena-surroundings-v2/client-overlay'/record['path']).read_bytes()
            self.assertEqual([i for i, (a,b) in enumerate(zip(old,new)) if a != b], [52,53,54])
            validate_fog_tile(new)


if __name__ == '__main__':
    unittest.main()
