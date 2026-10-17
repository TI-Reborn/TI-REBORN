import unittest
from tio.protocol.binary import PacketError, Reader
from tio.protocol.system_message import encode_shop_error
from tio.shop_errors import shop_error_reply


class ShopErrorTests(unittest.TestCase):
    def test_error_wire(self):
        packet=shop_error_reply(ValueError('Insufficient credits'))
        reader=Reader(packet)
        self.assertEqual((reader.u8(), reader.u32(), reader.u32(), reader.u32()), (0xf0,47,1,1))
        self.assertEqual(reader.u32(), 1)
        reader.finish()

    def test_unknown_error_does_not_expose_internal_text(self):
        packet=shop_error_reply(ValueError('private database path'))
        self.assertNotIn(b'private',packet)
        self.assertIn('запрос не выполнен'.encode('utf-16-le'),packet)

    def test_cstring_validation(self):
        for value in ('', 'a\0b', 'x'*256, '😀', None):
            with self.assertRaises(PacketError):
                encode_shop_error(value)
