import unittest
from pathlib import Path
from tio.city_catalogs import CityCatalogs
from tio.protocol.hire import encode_hire_request,decode_hire_request
from tio.protocol.hire import encode_dismiss_request,decode_dismiss_request,encode_pet_deleted,decode_paid_rename
from tio.protocol.binary import PacketError


class HireTests(unittest.TestCase):
    def test_paid_rename_wire(self):
        request = b'\xb9\x06\x03\0\0\0' + 'Пётр'.encode('cp1251') + b'\0'
        self.assertEqual(decode_paid_rename(request), (3, 'Пётр'))
        for invalid in (request[:-1], request + b'\0', b'\xb9\x05' + request[2:],
                        request[:2] + bytes(4) + request[6:], request[:6] + b'Ab\x98\0'):
            with self.subTest(packet=invalid), self.assertRaises(PacketError):
                decode_paid_rename(invalid)

    def test_dismiss_wire(self):
        self.assertEqual(encode_dismiss_request(2),b'\x64\x02\0\0\0')
        self.assertEqual(decode_dismiss_request(encode_dismiss_request(2)),2)
        self.assertEqual(encode_pet_deleted(2),b'\x65\x02\0\0\0')
        for packet in (b'\x64',b'\x63\x02\0\0\0',b'\x64\x02\0\0\0\0'):
            with self.assertRaises(PacketError):decode_dismiss_request(packet)

    def test_request_layout(self):
        for value in (0,1,0xffffffff):
            packet=encode_hire_request(value)
            self.assertEqual(decode_hire_request(packet),value)
            for end in range(len(packet)):
                with self.assertRaises(PacketError):decode_hire_request(packet[:end])
        with self.assertRaises(PacketError):decode_hire_request(b'\x64\x01\0\0\0')
        with self.assertRaises(PacketError):encode_hire_request(-1)

    def test_local_candidates_have_valid_resource_types(self):
        catalog=CityCatalogs(Path(__file__).resolve().parents[1]/'config/city_catalogs.json')
        self.assertEqual([(c.candidate_id,c.resource_type) for c in catalog.candidates],[(1,1),(2,2),(3,3),(4,4),(5,5),(6,6)])
