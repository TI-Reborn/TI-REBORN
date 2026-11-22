import struct
import unittest

try:
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EIP, UC_X86_REG_ESP
except ImportError:
    Uc = None


@unittest.skipIf(Uc is None, 'Unicorn is needed for the native selector test')
class ImplantSelectorTests(unittest.TestCase):
    def test_selector_keeps_distinct_instance_ids_and_skips_repeated_ids(self):
        from deploy.client_implant_workshop import APPEND, CLEANUP, SELECTOR, selector_code

        panel, items, frame = 0x1000, 0x2020, 0x4000
        for instance, prior, expected in ((1001, (), APPEND), (1002, (1001,), APPEND),
                                           (1001, (1001, 1002), CLEANUP),
                                           (1002, (1001, 1002), CLEANUP)):
            with self.subTest(instance=instance, prior=prior):
                emulator = Uc(UC_ARCH_X86, UC_MODE_32)
                emulator.mem_map(0x1000, 0x4000)
                for address in (APPEND, SELECTOR):
                    emulator.mem_map(address & ~0xfff, 0x1000)
                emulator.mem_write(SELECTOR, selector_code())
                emulator.mem_write(APPEND, b'\xf4')
                emulator.mem_write(CLEANUP, b'\xf4')
                emulator.reg_write(UC_X86_REG_EBX, panel)
                emulator.reg_write(UC_X86_REG_EBP, frame)
                emulator.mem_write(frame - 0x268, struct.pack('<I', instance))
                if prior:
                    emulator.mem_write(panel + 0x2c8, struct.pack('<I', items))
                    emulator.mem_write(items - 4, struct.pack('<I', len(prior)))
                for index, identity in enumerate(prior):
                    emulator.mem_write(items + index * 0x290 + 0x28, struct.pack('<I', identity))
                emulator.emu_start(SELECTOR, 0, count=100)
                self.assertEqual(emulator.reg_read(UC_X86_REG_EIP), expected + 1)
                if expected == APPEND:
                    self.assertEqual(emulator.reg_read(UC_X86_REG_EAX), items if prior else 0)

    def test_shared_rows_use_the_fighters_current_inventory(self):
        from deploy.client_implant_workshop import ACTOR_LOOKUP, FRESHNESS, STOCK_SELECTOR, freshness_code

        record, slots, fighter, items, stack, skip = 0x1000, 0x1400, 0x2000, 0x3040, 0x4ff0, 0x4800
        for kind, owner, slot, current, expected in (
                (5, 2, 3, (1001, 1002), STOCK_SELECTOR),
                (5, 2, 3, (1001,), skip), (5, 2, 3, (), skip),
                (5, 2, -1, (), STOCK_SELECTOR), (0, 0, -1, (), STOCK_SELECTOR)):
            with self.subTest(kind=kind, slot=slot, current=current):
                emulator = Uc(UC_ARCH_X86, UC_MODE_32)
                emulator.mem_map(0x1000, 0x4000)
                for address in (ACTOR_LOOKUP, FRESHNESS, STOCK_SELECTOR, 0xac618c):
                    emulator.mem_map(address & ~0xfff, 0x1000)
                emulator.mem_write(FRESHNESS, freshness_code())
                emulator.mem_write(ACTOR_LOOKUP, b'\xb8' + struct.pack('<i', slot) + b'\xc3')
                for stop in (skip, STOCK_SELECTOR):
                    emulator.mem_write(stop, b'\xf4')
                emulator.mem_write(record + 0x28, struct.pack('<I', 1002))
                emulator.mem_write(record + 0x280, struct.pack('<II', kind, owner))
                emulator.mem_write(0xac618c, struct.pack('<I', slots))
                if slot >= 0:
                    emulator.mem_write(slots + 4 * slot, struct.pack('<I', fighter))
                if current:
                    emulator.mem_write(fighter + 0x6c, struct.pack('<I', items))
                    emulator.mem_write(items - 4, struct.pack('<I', len(current)))
                for index, identity in enumerate(current):
                    emulator.mem_write(items + index * 0x290 + 0x28, struct.pack('<I', identity))
                emulator.mem_write(stack, struct.pack('<I', skip))
                emulator.reg_write(UC_X86_REG_ESP, stack)
                emulator.reg_write(UC_X86_REG_EAX, record)
                emulator.reg_write(UC_X86_REG_EBX, 0x11223344)
                emulator.emu_start(FRESHNESS, 0, count=150)
                self.assertEqual(emulator.reg_read(UC_X86_REG_EIP), expected + 1)
                self.assertEqual(emulator.reg_read(UC_X86_REG_EBX), 0x11223344)
                self.assertEqual(emulator.reg_read(UC_X86_REG_EAX), items + 0x290 if 1002 in current else record)
