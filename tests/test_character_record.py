import unittest
from dataclasses import replace
from tio.protocol.character_select import *
from tio.protocol.binary import PacketError

class CharacterRecordTests(unittest.TestCase):
    def record(self):return CharacterRecord(7,b'Probe',1,0x12345678,9,0,0,b'',tuple(range(101,120)),8,0xabcdef01,255)
    def test_full_layout_and_conditional(self):
        p=self.record();raw=encode_character_list((p,))
        self.assertEqual(len(raw),62)
        self.assertEqual(raw[:19].hex(),'1001000750726f626500017856341209000065')
        self.assertEqual(decode_character_list(raw),(p,))
        for flag in (1,255):
            q=replace(p,optional_flag=flag,optional_six=bytes(range(1,7)))
            self.assertEqual(len(encode_character_list((q,))),68)
            self.assertEqual(decode_character_list(encode_character_list((q,))),(q,))
    def test_multiple_records(self):
        records=(self.record(),replace(self.record(),record_id=255,name_bytes=b'',words=(65535,)*19))
        self.assertEqual(decode_character_list(encode_character_list(records)),records)
        self.assertEqual(encode_character_list(()),encode_empty_character_list())
    def test_truncation(self):
        raw=encode_character_list((self.record(),))
        for bad in [raw[:n] for n in range(len(raw))]+[raw+b'\0',b'\x11'+raw[1:]]:
            with self.assertRaises(PacketError):decode_character_list(bad)
    def test_bounds(self):
        p=self.record()
        for q in (replace(p,record_id=256),replace(p,name_bytes=b'x'*256),replace(p,name_bytes=b'a\0'),replace(p,words=(0,)*18),replace(p,words=(-1,)*19),replace(p,optional_flag=0,optional_six=b'0'*6),replace(p,optional_flag=1),replace(p,boolean_byte=256)):
            with self.assertRaises(PacketError):encode_character_list((q,))
        with self.assertRaises(PacketError):encode_character_list((p,)*1200)
