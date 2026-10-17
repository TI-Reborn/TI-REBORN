"""Published-byte validation fixtures; no network, accounts or native process."""
import io
import unittest

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from tools.arena_surroundings_native import encode_scene, encode_tile
from tools.verify_hosted_arena_surroundings import published_scene, sha


class PublishedSurroundingsAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = 'as_de_1_38'
        cls.files = {}
        width, height, n, depth = 5504, 2752, 38, 24
        outer = Image.new('L', (width, height))
        ImageDraw.Draw(outer).polygon(((width//2, 0), (width-1, height//2),
                                      (width//2, height-1), (0, height//2)), fill=255)
        outer = outer.filter(ImageFilter.MinFilter(3))
        hole = Image.new('L', (width, height))
        ImageDraw.Draw(hole).polygon(((width//2, 32*depth),
            (width//2+32*n, 32*depth+16*n), (width//2, 32*depth+32*n),
            (width//2-32*n, 32*depth+16*n)), fill=255)
        hole = hole.filter(ImageFilter.MaxFilter(5))
        painting = Image.new('RGBA', (width, height), (110, 120, 100, 0))
        painting.putalpha(ImageChops.subtract(outer, hole))
        records = []
        for py in range(0, height, 1024):
            for px in range(0, width, 1024):
                patch = Image.new('RGBA', (1024, 1024))
                patch.paste(painting.crop((px, py, min(px+1024, width), min(py+1024, height))), (0, 0))
                if patch.getchannel('A').getbbox() is None:
                    continue
                stem = cls.scene+f'_p{len(records):04d}'
                model, texture = stem+'.t', stem+'.png'
                anchor = (19, 19)
                tile = bytearray(encode_tile(texture, 1024, 1024,
                    px-width//2-32*(anchor[1]-anchor[0])+32,
                    py-32*depth-16*(anchor[0]+anchor[1])))
                tile[68] = 1
                cls.files['base/setting/arena_surroundings/'+model] = bytes(tile)
                encoded = io.BytesIO()
                patch.save(encoded, format='PNG')
                cls.files['base/setting/arena_surroundings/'+texture] = encoded.getvalue()
                records.append((model, *anchor))
        cls.files['base/maps/'+cls.scene+'.s'] = encode_scene(records)

    def manifest(self, files):
        return dict(version='offline', files=[dict(path=path, size=len(raw), sha256=sha(raw))
                    for path, raw in files.items()])

    def audit(self, files=None, manifest=None):
        files = files or self.files
        return published_scene('offline.invalid', manifest or self.manifest(files), self.scene, 38,
                               fetch=lambda record: files[record['path']])

    def test_actual_png_alpha_and_native_offset_reconstruction(self):
        proof = self.audit()
        self.assertTrue(proof['alpha_proof']['passed'])
        self.assertEqual(len(proof['alpha_proof']['four_sides']), 4)
        self.assertEqual(len(proof['alpha_proof']['four_corners']), 4)
        self.assertEqual(len(proof['exact_published_records']), len(self.files))

    def test_manifest_sha_is_checked_before_decode(self):
        manifest = self.manifest(self.files)
        manifest['files'][0]['sha256'] = '0'*64
        with self.assertRaisesRegex(AssertionError, 'exact manifest record'):
            self.audit(manifest=manifest)

    def test_wrong_native_pixel_registration_is_rejected(self):
        files = dict(self.files)
        path = next(path for path in files if path.endswith('.t'))
        tile = bytearray(files[path])
        tile[48] ^= 1
        files[path] = bytes(tile)
        with self.assertRaisesRegex(AssertionError, 'offset differs'):
            self.audit(files)

    def test_missing_published_png_is_rejected(self):
        files = dict(self.files)
        del files[next(path for path in files if path.endswith('.png'))]
        with self.assertRaisesRegex(AssertionError, 'absent from the published manifest'):
            self.audit(files)

    def test_alpha_covering_gameplay_is_rejected_despite_valid_manifest_sha(self):
        files = dict(self.files)
        scene = files['base/maps/'+self.scene+'.s']
        # The top gameplay vertex is canvas(2752,768); find its containing patch.
        for i in range((len(scene)-34)//72):
            record = scene[34+72*i:34+72*(i+1)]
            name = record[1:1+record[0]].decode()
            tile = files['base/setting/arena_surroundings/'+name]
            import struct
            sx, sy = struct.unpack_from('<hh', tile, 48)
            ax, ay = struct.unpack_from('<ii', record, 64)
            px, py = 32*(ay-ax)-32+sx+2752, 16*(ax+ay)+sy+768
            if px <= 2752 < px+1024 and py <= 768 < py+1024:
                texture = tile[204:204+tile[203]].decode()
                path = 'base/setting/arena_surroundings/'+texture
                with Image.open(io.BytesIO(files[path])) as image:
                    changed = image.copy()
                changed.putpixel((2752-px, 768-py), (1, 2, 3, 255))
                encoded = io.BytesIO()
                changed.save(encoded, format='PNG')
                files[path] = encoded.getvalue()
                break
        else:
            self.fail('Fixture has no patch over the gameplay vertex')
        with self.assertRaisesRegex(AssertionError, 'covers playable ground'):
            self.audit(files)


if __name__ == '__main__':
    unittest.main()
