import unittest
from tio.protocol.binary import PacketError, Reader, Writer
from tio.protocol.login import LSAuthResult, encode_ls_auth_result, decode_ls_auth_result, transform_auth_value
from tio.protocol.login import LoginFailureStatus, encode_login_failure


class LoginCodecTests(unittest.TestCase):
    def test_golden_success(self):
        # Synthetic diagnostic value; format derives from original parser, not a live capture.
        golden = bytes.fromhex('02 00 78 56 34 12')
        packet = LSAuthResult(0, 0x12345678)
        self.assertEqual(encode_ls_auth_result(packet), golden)
        self.assertEqual(decode_ls_auth_result(golden), packet)

    def test_golden_failure(self):
        self.assertEqual(encode_ls_auth_result(LSAuthResult(0xff)), bytes.fromhex('02 ff'))
        self.assertEqual(decode_ls_auth_result(bytes.fromhex('02 ff')), LSAuthResult(0xff))

    def test_all_nonzero_statuses(self):
        for status in range(1, 256):
            with self.subTest(status=status):
                self.assertEqual(decode_ls_auth_result(encode_ls_auth_result(LSAuthResult(status))), LSAuthResult(status))

    def test_u32_boundaries(self):
        for value in (0, 0x7fffffff, 0x80000000, 0xffffffff):
            self.assertEqual(decode_ls_auth_result(encode_ls_auth_result(LSAuthResult(0,value))), LSAuthResult(0,value))

    def test_invalid_fields(self):
        for status, value in [(-1,None),(256,None),(True,None),(0,None),(0,-1),(0,2**32),(0,True),(1,0)]:
            with self.subTest(status=status,value=value), self.assertRaises(PacketError):
                LSAuthResult(status,value)

    def test_truncation_and_trailing_data(self):
        good = bytes.fromhex('020078563412')
        for data in [good[:n] for n in range(len(good))] + [good+b'\0', b'\x02\x01\0', b'\x04\0']:
            with self.subTest(data=data), self.assertRaises(PacketError):
                decode_ls_auth_result(data)

    def test_transform(self):
        self.assertEqual(transform_auth_value(4), 0x375830)
        # Independently computed golden, also checked against original x86 in native probe.
        self.assertEqual(transform_auth_value(0), 0x374530)

    def test_native_confirmed_login_denial_packets(self):
        for status in LoginFailureStatus:
            self.assertEqual(encode_login_failure(status),bytes((4,status)))
        # Success and the alternate 0x12 string/callback branch are separate.
        for status in (0,1,2,5,0x12,255,-1,256,True):
            with self.subTest(status=status), self.assertRaises(PacketError):
                encode_login_failure(status)


class BinaryTests(unittest.TestCase):
    def test_golden_primitives(self):
        data = Writer().u8(0xab).u16(0x1234).u32(0x89abcdef).build()
        self.assertEqual(data.hex(), 'ab3412efcdab89')
        r = Reader(data)
        self.assertEqual((r.u8(),r.u16(),r.u32()), (0xab,0x1234,0x89abcdef))
        r.finish()

    def test_invalid(self):
        for width in (8,16,32):
            for value in (-1,1<<width,True,'0'):
                with self.subTest(width=width,value=value), self.assertRaises(PacketError):
                    getattr(Writer(),f'u{width}')(value)
            with self.assertRaises(PacketError):
                getattr(Reader(b''), f'u{width}')()
        with self.assertRaises(PacketError): Reader(b'').read(-1)
        with self.assertRaises(PacketError): Reader(b'x').finish()
