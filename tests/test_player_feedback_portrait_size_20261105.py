"""Execute the native avatar draw call with battle and inventory callers."""
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EBP, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESP)

ROOT = Path(__file__).resolve().parents[1]


class PortraitSizeTests(unittest.TestCase):
    def test_battle_portrait_fits_40_pixels_and_inventory_keeps_native_size(self):
        source = (ROOT/'reports/player-feedback-20261104/avatars/source-silver.dll').read_bytes()
        patcher = ROOT/'deploy/client_portrait_size_20261105.py'
        if patcher.exists():
            from deploy.client_portrait_size_20261105 import patch
            source = patch(source)
        from deploy.client_battle_portrait_size_20261105 import patch
        source = patch(source)
        for base in (0x400000, 0x1400000):
            for caller in (0x8d0b58, 0x9daae5, 0x9b637a, 0x6b0748):
                with self.subTest(base=base, caller=caller):
                    delta = base-0x400000
                    with pefile.PE(data=source) as pe:
                        pe.relocate_image(base)
                        mapped = pe.get_memory_mapped_image()
                    u = Uc(UC_ARCH_X86, UC_MODE_32)
                    u.mem_map(base, (len(mapped)+4095)&~4095)
                    u.mem_write(base, mapped)
                    u.mem_map(0x2000000, 0x20000)
                    frame, stack, record = 0x2001000, 0x2008000, 0x2010000
                    u.mem_write(frame+4, struct.pack('<I', caller+delta))
                    u.mem_write(stack, struct.pack('<ff', 30., 20.))
                    u.reg_write(UC_X86_REG_EBP, frame)
                    u.reg_write(UC_X86_REG_ESP, stack)
                    u.reg_write(UC_X86_REG_EAX, record)
                    u.reg_write(UC_X86_REG_EBX, 0x12345678)
                    u.reg_write(UC_X86_REG_EDX, 0)
                    u.reg_write(UC_X86_REG_ECX, 0)
                    draws = []

                    def hook(_u, address, _size, _data):
                        if address not in (0x4f2788+delta, 0x4f28d4+delta):
                            return
                        sp = u.reg_read(UC_X86_REG_ESP)
                        scaled = address == 0x4f28d4+delta
                        args = struct.unpack('<4I' if scaled else '<2I',
                                             u.mem_read(sp+4, 16 if scaled else 8))
                        draws.append((scaled, u.reg_read(UC_X86_REG_EDX),
                                      u.reg_read(UC_X86_REG_ECX), args))
                        u.reg_write(UC_X86_REG_EIP, struct.unpack('<I', u.mem_read(sp, 4))[0])
                        u.reg_write(UC_X86_REG_ESP, sp+(20 if scaled else 12))

                    u.hook_add(UC_HOOK_CODE, hook)
                    u.emu_start(0x6b02e7+delta, 0x6b02ec+delta, count=3000)
                    self.assertEqual(u.reg_read(UC_X86_REG_EIP), 0x6b02ec+delta)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), stack+8)
                    self.assertEqual(u.reg_read(UC_X86_REG_EBP), frame)
                    self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x12345678)
                    if caller in (0x8d0b58, 0x9daae5):
                        self.assertEqual(draws, [(True, 20, 30, (0, 0, 40, 40))])
                    else:
                        self.assertEqual(draws, [(False, 0, 0,
                            struct.unpack('<2I', struct.pack('<ff', 30., 20.)))])

    def test_player_info_portrait_stays_in_header_corner(self):
        from deploy.client_player_info_portrait import patch

        source = (ROOT/'reports/shooting-range-20261118/native-client/candidate-silver.dll').read_bytes()
        candidate = patch(source)
        for base in (0x400000, 0x1400000):
            with self.subTest(base=base):
                self.check_player_info_corner(candidate, base)

    def test_player_info_header_separates_portrait_status_and_rating(self):
        from deploy.client_player_info_portrait import patch_header

        source = (ROOT/'reports/player-info-portrait-20261118/candidate-silver.dll').read_bytes()
        candidate = patch_header(source)
        for base in (0x400000, 0x1400000):
            with self.subTest(base=base):
                delta = base - 0x400000
                with pefile.PE(data=candidate) as pe:
                    pe.relocate_image(base)
                    mapped = pe.get_memory_mapped_image()
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(base, (len(mapped) + 4095) & ~4095)
                u.mem_write(base, mapped)
                u.mem_map(0x2000000, 0x10000)
                frame, stack, parent_slot, parent = (0x2001000, 0x2002000, 0x2003000, 0x2004000)
                u.mem_write(parent_slot, struct.pack('<I', parent))
                u.mem_write(parent + 0x38, struct.pack('<I', 512))
                u.reg_write(UC_X86_REG_EBP, frame)
                u.reg_write(UC_X86_REG_ESP, stack)
                u.reg_write(UC_X86_REG_EDI, parent_slot)
                portrait = []
                labels = []

                def hook(uc, address, _size, _data):
                    sp = uc.reg_read(UC_X86_REG_ESP)
                    call = address - delta
                    cleanup = 0
                    if call == 0xa4d58c:
                        _, height, width, y = struct.unpack('<4I', uc.mem_read(sp + 4, 16))
                        portrait.append((uc.reg_read(UC_X86_REG_ECX), y, width, height))
                        uc.reg_write(UC_X86_REG_EAX, 0x2005000)
                        cleanup = 16
                    elif call == 0xa47d78:
                        label = 0x2005400 + 0x400 * len(labels)
                        labels.append(label)
                        uc.reg_write(UC_X86_REG_EAX, label)
                    elif call == 0x425c3c:
                        cleanup = 4
                    elif call not in (0x40eca8, 0xa42b04, 0x6675e0, 0x40b47c, 0x40c05c):
                        return
                    uc.reg_write(UC_X86_REG_EIP, struct.unpack('<I', uc.mem_read(sp, 4))[0])
                    uc.reg_write(UC_X86_REG_ESP, sp + 4 + cleanup)

                u.hook_add(UC_HOOK_CODE, hook)
                u.emu_start(0x965e92 + delta, 0x965fc2 + delta, count=500)
                self.assertEqual(u.reg_read(UC_X86_REG_EIP), 0x965fc2 + delta)
                self.assertEqual(portrait, [(22, 26, 512, 32)])
                self.assertEqual([struct.unpack('<2I', u.mem_read(label + 0x30, 8)) for label in labels],
                                 [(22, 74), (76, 58), (22, 90)])

    def check_player_info_corner(self, image, base):
        delta = base - 0x400000
        with pefile.PE(data=image) as pe:
            pe.relocate_image(base)
            mapped = pe.get_memory_mapped_image()
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(base, (len(mapped) + 4095) & ~4095)
        u.mem_write(base, mapped)
        u.mem_map(0x2000000, 0x20000)
        frame, stack = 0x2001000, 0x2008000
        origin_x, origin_y, width = 602, 166, 512
        x, y = origin_x + 22, origin_y + 18
        u.mem_write(frame + 4, struct.pack('<I', 0x964b49 + delta))
        u.mem_write(stack, struct.pack('<ff', y, x))
        u.reg_write(UC_X86_REG_EBP, frame)
        u.reg_write(UC_X86_REG_ESP, stack)
        u.reg_write(UC_X86_REG_EAX, 0x2010000)
        draws = []

        def hook(uc, address, _size, _data):
            if address == 0x4f2788 + delta:
                self.fail('Player-card avatar used its full texture dimensions')
            if address == 0x4f28d4 + delta:
                sp = uc.reg_read(UC_X86_REG_ESP)
                draws.append((uc.reg_read(UC_X86_REG_EDX), uc.reg_read(UC_X86_REG_ECX),
                              struct.unpack('<4I', uc.mem_read(sp + 4, 16))))
                uc.reg_write(UC_X86_REG_EIP, struct.unpack('<I', uc.mem_read(sp, 4))[0])
                uc.reg_write(UC_X86_REG_ESP, sp + 20)

        u.hook_add(UC_HOOK_CODE, hook)
        u.emu_start(0x6b02e7 + delta, 0x6b02ec + delta, count=3000)
        self.assertEqual(draws, [(x, y, (0, 0, 40, 40))])
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), stack + 8)
        self.assertLessEqual(x + 40, origin_x + width - 16)
