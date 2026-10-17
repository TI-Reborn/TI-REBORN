"""Native BMP alpha resources must not become opaque RGBA PNG files."""
import io
from pathlib import Path
import struct
import sys
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from reservation_texture_export import encode
from build_visual_asset_catalog import decode

class ReservationTextureCodecTests(unittest.TestCase):
    def test_native_bmp32_alpha_and_row_orientation_survive_export(self):
        reference=Image.new('RGBA',(3,2),(0,0,0,0))
        reference.putpixel((0,0),(70,55,35,61))
        reference.putpixel((2,1),(90,60,40,255))
        raw=io.BytesIO();reference.save(raw,format='BMP');raw=raw.getvalue()
        self.assertEqual(struct.unpack_from('<H',raw,28)[0],32)
        self.assertEqual(Image.open(io.BytesIO(raw)).mode,'RGB')
        original,_=decode(raw)
        self.assertEqual(original.tobytes(),reference.tobytes())
        art=Image.new('RGBA',reference.size,(110,80,50,255))
        result=encode(raw,art,original);decoded,_=decode(result)
        self.assertEqual(result[:54],raw[:54])
        self.assertEqual(decoded.getchannel('A').tobytes(),reference.getchannel('A').tobytes())
        self.assertEqual(decoded.convert('RGB').tobytes(),art.convert('RGB').tobytes())

    def test_bmp_keeps_rgb_format_and_black_padding_pixels(self):
        reference=Image.new('RGB',(8,4),(0,0,0))
        reference.putpixel((3,2),(70,55,35))
        raw=io.BytesIO();reference.save(raw,format='BMP')
        art=reference.convert('RGBA');art.putpixel((3,2),(105,80,45,255))
        result=encode(raw.getvalue(),art,reference.convert('RGBA'))
        self.assertEqual(result[:2],b'BM')
        self.assertEqual(struct.unpack_from('<H',result,28)[0],24)
        decoded=Image.open(io.BytesIO(result))
        self.assertEqual(decoded.mode,'RGB')
        self.assertEqual(decoded.size,reference.size)
        self.assertEqual(decoded.getpixel((0,0)),(0,0,0))
        self.assertEqual(decoded.getpixel((3,2)),(105,80,45))

    def test_rgba_png_keeps_its_original_alpha(self):
        reference=Image.new('RGBA',(8,4),(0,0,0,0))
        reference.putpixel((3,2),(70,55,35,255))
        raw=io.BytesIO();reference.save(raw,format='PNG')
        art=Image.new('RGBA',reference.size,(120,100,70,255))
        decoded=Image.open(io.BytesIO(encode(raw.getvalue(),art,reference)))
        self.assertEqual(decoded.format,'PNG')
        self.assertEqual(decoded.getchannel('A').tobytes(),reference.getchannel('A').tobytes())

if __name__=='__main__':unittest.main()
