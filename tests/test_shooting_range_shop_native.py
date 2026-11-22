"""Execute the shop menu edit at a relocated Silver base."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP

from deploy.client_shooting_range_shop import CHILD_COUNT, ENTRY, IMAGE_BASE, layout_code


class ShootingRangeShopNativeTests(unittest.TestCase):
    def test_only_enabled_range_shop_follows_training_and_refresh_is_idempotent(self):
        client = Uc(UC_ARCH_X86, UC_MODE_32)
        base, memory = 0x15000000, 0x02000000
        client.mem_map(base, 0x900000)
        client.mem_map(memory, 0x10000)

        def va(original):
            return base + original - IMAGE_BASE

        def words(address, *values):
            client.mem_write(address, struct.pack('<' + 'I' * len(values), *values))

        parent, children, array, shop, training, town, table, record = (
            memory + offset * 0x400 for offset in range(1, 9))
        client.mem_write(va(ENTRY), layout_code())
        client.mem_write(va(CHILD_COUNT), bytes.fromhex('8b402c 8b4008 c3'))
        words(va(0xACF044), shop)
        words(va(0xACF058), training)
        words(va(0xAC5D58), town)
        words(va(0xAC63BC), table)
        words(table, table + 4)
        words(table + 4 + 16 * 4, record)
        words(parent + 0x2C, children)
        words(children + 4, array, 5)
        words(array, 100, shop, 200, training, 300)

        def refresh(town_id, shop_enabled):
            words(town, town_id)
            client.mem_write(record + 0x239, bytes((shop_enabled,)))
            client.reg_write(UC_X86_REG_EAX, parent)
            stack = memory + 0x8000
            client.reg_write(UC_X86_REG_ESP, stack)
            words(stack, memory + 4)
            client.emu_start(va(ENTRY), memory + 4, count=200)
            self.assertEqual(client.reg_read(UC_X86_REG_EAX), 5)
            return (struct.unpack('<5I', client.mem_read(array, 20)),
                    bytes(client.mem_read(shop + 0x49, 2)))

        original = (100, shop, 200, training, 300)
        ordered = (100, 200, training, shop, 300)
        self.assertEqual(refresh(17, 0), (original, b'\0\0'))
        self.assertEqual(refresh(17, 1), (ordered, b'\1\1'))
        self.assertEqual(refresh(17, 1), (ordered, b'\1\1'))
        self.assertEqual(refresh(3, 1), (ordered, b'\0\0'))
