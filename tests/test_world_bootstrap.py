import unittest
from tio.protocol.world_bootstrap import *
class BootstrapTests(unittest.TestCase):
    def test_select_conditional(self):
        for p in (SelectResult(0,0x12345678,0xabcdef01),SelectResult(1)):
            data=encode_select_result(p);self.assertEqual(decode_select_result(data),p)
            for n in range(len(data)):
                with self.assertRaises(PacketError):decode_select_result(data[:n])
        with self.assertRaises(PacketError):encode_select_result(SelectResult(1,0,0))
    def test_mychar(self):
        p=MyCharInfo(1,b'ProbeNew',3,(-153)&0xffffffff,(-317)&0xffffffff,0)
        data=encode_mychar_info(p);self.assertEqual(decode_mychar_info(data),p)
        for n in range(len(data)):
            with self.assertRaises(PacketError):decode_mychar_info(data[:n])
        with self.assertRaises(PacketError):decode_mychar_info(data+b'\0')
