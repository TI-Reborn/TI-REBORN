"""Exercise the published marker draw and native mouse scopes in Unicorn."""
from pathlib import Path
import os
import unittest

from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESP
from tools.verify_client_ui_scale_native import DATA, Fixture, get, put

SOURCE = Path(os.environ.get('TIO_MARKER_SOURCE', 'reports/tactical-mark-cursor/source-silver.dll'))
DRAW, CLICK, HOVER = 0x7105c8, 0x710960, 0x710ad8
DRAW_CALL, CLICK_CALL, HOVER_CALL = 0x9c2f5b, 0x9f4a6d, 0x9db355


@unittest.skipUnless(SOURCE.is_file(), 'published 2026.11.14.2 Silver required')
class MarkerCursorTests(unittest.TestCase):
    def load_image(self):
        source = SOURCE.read_bytes()
        if os.environ.get('TIO_MARKER_TEST_BASELINE'):
            return source
        from deploy.client_tactical_mark_cursor import patch
        return patch(source)

    def test_marker_draw_bypasses_ui_vertex_scaling(self):
        image = self.load_image()
        for base in (0x400000, 0x10400000):
            for percent in (100, 125, 150, 200):
                with self.subTest(base=base, percent=percent):
                    f = Fixture(image, base)
                    f.initialize(2560, 1600, percent)
                    f.state(0x14, 1)
                    lst, marker, entries, members = (DATA + i for i in (0xa000, 0xa100, 0xa200, 0xb000))
                    put(f.u, f.va(0xacdd1c), lst)
                    put(f.u, lst+4, entries)
                    put(f.u, lst+8, 1)
                    put(f.u, entries, marker)
                    f.u.mem_write(marker, bytes((1, 12, 26, 0)))
                    put(f.u, marker+4, 0)
                    put(f.u, marker+8, 255)
                    put(f.u, marker+0x14, 0)
                    put(f.u, f.va(0xac62a4), members)
                    f.u.mem_write(members, b'\1')
                    for index, (address, value) in enumerate(((0xac61b0, 230), (0xac6068, 150), (0xac5fe4, 2000))):
                        slot = DATA+0xa300+index*4
                        put(f.u, f.va(address), slot)
                        put(f.u, slot, value)
                    f.u.mem_map(0, 0x1000)
                    drawn = []

                    def hook(u, address, _size, _data):
                        if address == f.va(0x674e78):
                            drawn.append((f.state(0x14), u.reg_read(UC_X86_REG_EDX) + 32,
                                          u.reg_read(UC_X86_REG_ECX) + 48))
                            f.ret(12)
                        elif address == f.va(0x67571c):
                            drawn.append((f.state(0x14), u.reg_read(UC_X86_REG_EDX),
                                          u.reg_read(UC_X86_REG_ECX)))
                            f.ret(12)
                        elif address in (f.va(0x40c0d8), f.va(0x40b09c), f.va(0xa89494)):
                            f.ret()

                    f.u.hook_add(UC_HOOK_CODE, hook)
                    f.run(DRAW_CALL, stop=DRAW_CALL+5)
                    expected = (0, 230+32*(26-12), 150+16*(26+12)+16)
                    self.assertEqual(drawn, [expected, expected])
                    self.assertEqual(f.state(0x14), 1)

    def test_mark_interaction_uses_physical_mouse_and_restores_ui_mouse(self):
        image = self.load_image()
        for site, native in ((CLICK_CALL, CLICK), (HOVER_CALL, HOVER)):
            with self.subTest(site=site):
                f = Fixture(image, 0x10400000)
                f.initialize(2560, 1600, 150)
                f.state(0x14, 1)
                mouse = tuple(get(f.u, f.va(address)) for address in (0xac5b70, 0xac5a04))
                for address, value in zip(mouse, (891, 489)):
                    put(f.u, address, value)
                seen = []

                def hook(u, address, _size, _data):
                    if address == f.va(native):
                        seen.append(tuple(get(u, slot) for slot in mouse))
                        f.ret()

                f.u.hook_add(UC_HOOK_CODE, hook)
                f.run(site, stop=site+5)
                self.assertEqual(seen, [(1337, 733)])
                self.assertEqual(tuple(get(f.u, slot) for slot in mouse), (891, 489))
                self.assertEqual(f.state(0x14), 1)
