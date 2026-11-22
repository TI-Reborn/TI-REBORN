import unittest
from tio.warehouse_service import warehouse_error_reply
from tio.warehouse import WarehouseRejected
from tio.protocol.binary import Reader


class WarehouseErrorTests(unittest.TestCase):
    def test_localized_error_wire_and_no_internal_details(self):
        for error, expected in (
            ('Warehouse capacity exceeded','недостаточно свободных мест'),
            ('Insufficient item quantity','недостаточно предметов'),
            ('Unequip item before transferring','сначала снимите'),
            ('private internal database detail','не удалось перенести предметы'),
        ):
            r=Reader(warehouse_error_reply(WarehouseRejected(error)))
            self.assertEqual((r.u8(),r.u32(),r.u32(),r.u32()),(0xf0,394,1,5))
            text=r.read(len(r.data)-r.offset)
            self.assertEqual(text[-2:],b'\0\0')
            self.assertIn(expected,text[:-2].decode('utf-16-le'))
            self.assertNotIn(error,text[:-2].decode('utf-16-le'))
