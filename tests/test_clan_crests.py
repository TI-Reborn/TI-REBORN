from pathlib import Path
import json,struct,unittest
from tio.protocol.binary import PacketError
from tio.protocol.clan_crests import CLAN,ALLIANCE,CrestRequest,CrestContent,encode_request,decode_request,encode_content,decode_content

ROOT=Path(__file__).resolve().parents[1]


def bmp():return b'BM'+struct.pack('<III',822,0,54)+struct.pack('<IiiHHIIiiII',40,16,16,1,24,0,768,0,0,0,0)+b'\7'*768


class ClanCrestCodecTests(unittest.TestCase):
    def test_original_c2s_builder_vectors_and_positive_u32_boundaries(self):
        proof=json.loads((ROOT/'evidence/clan_crest_native.json').read_text());self.assertTrue(proof['passed'])
        self.assertEqual(encode_request(19),bytes.fromhex(proof['cache']['c2s'][0]))
        self.assertEqual(encode_request(23,ALLIANCE),bytes.fromhex(proof['cache']['c2s'][1]))
        for kind in (CLAN,ALLIANCE):
            for identity in (1,19,0x80000000,0xffffffff):self.assertEqual(decode_request(encode_request(identity,kind)),CrestRequest(kind,identity))

    def test_original_s2c_shape_and_real_bitmap_bytes(self):
        for kind,opcode in ((CLAN,b'\x5a'),(ALLIANCE,b'\xaf\x07')):
            encoded=encode_content(19,bmp(),kind);self.assertEqual(encoded,opcode+struct.pack('<IH',19,822)+bmp())
            self.assertEqual(len(encoded),829 if kind==CLAN else 830);self.assertEqual(decode_content(encoded),CrestContent(kind,19,bmp()))

    def test_invalid_id_kind_and_wrong_opcode_are_rejected(self):
        for value in (0,-1,0x100000000,True,'19'):
            with self.assertRaises(PacketError):encode_request(value)
            with self.assertRaises(PacketError):encode_content(value,bmp())
        for kind in (-1,2,True,'0'):
            with self.assertRaises(PacketError):encode_request(19,kind)
            with self.assertRaises(PacketError):encode_content(19,bmp(),kind)
        for request in (b'\x59'+bytes(4),b'\x5a'+struct.pack('<I',19),b'\xaf\x07'+struct.pack('<I',19),b'\xaf\x05'+struct.pack('<I',19),b''):
            with self.assertRaises(PacketError):decode_request(request)

    def test_every_truncation_trailing_and_bounded_length_fail_closed(self):
        for kind in (CLAN,ALLIANCE):
            request=encode_request(19,kind);content=encode_content(19,bmp(),kind)
            for length in range(len(request)):
                with self.assertRaises(PacketError):decode_request(request[:length])
            for length in range(len(content)):
                with self.assertRaises(PacketError):decode_content(content[:length])
            with self.assertRaises(PacketError):decode_request(request+b'x')
            with self.assertRaises(PacketError):decode_content(content+b'x')
            prefix=b'\x5a' if kind==CLAN else b'\xaf\x07'
            with self.assertRaises(PacketError):decode_content(prefix+struct.pack('<IH',19,825)+bytes(825))

    def test_noncanonical_or_executable_body_never_encodes_or_decodes(self):
        for raw in (bytearray(bmp()),bmp()+b'x',bmp()[:700],b'<script>bad</script>',bmp()[:28]+b'\x08\0'+bmp()[30:],bmp()[:30]+struct.pack('<I',1)+bmp()[34:],bmp()[:22]+struct.pack('<i',-16)+bmp()[26:]):
            with self.assertRaises(PacketError):encode_content(19,raw)
        for raw in (bmp()+b'x',bmp()[:700],bmp()[:2]+bytes(4)+bmp()[6:]):
            with self.assertRaises(PacketError):decode_content(b'\x5a'+struct.pack('<IH',19,len(raw))+raw)


if __name__=='__main__':unittest.main()
