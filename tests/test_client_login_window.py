"""Execute the login window adapter inside the patched Silver image (Unicorn)."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / 'reports/login-window-20261120/source-silver.dll'
INTER = ROOT / 'reports/login-window-20261120/inter-fonts/manifest.json'

try:
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                                   UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP, UC_X86_REG_EBP)
    from deploy import client_login_window as login
    AVAILABLE = SOURCE.exists() and INTER.exists()
except ImportError:
    AVAILABLE = False

DATA, STACK, STOP = 0x30000000, 0x31000000, 0x31f00000
WINDOW = DATA + 0x1000
# Native stubs: address -> (stack arguments, name)
STUBS = {}
if AVAILABLE:
    STUBS = {login.TEXT_WIDTH: (0, 'width'), login.SET_CAPTION: (0, 'caption'),
             login.SET_BOUNDS: (2, 'bounds'), login.CENTER: (0, 'center'),
             login.LOCALIZE: (0, 'localize'), login.DRAW_TEXT: (4, 'text'),
             login.DRAW_LINE: (2, 'line'), login.STRING_CLEAR: (0, 'clear'),
             login.RENDER_TREE: (0, 'render'), login.WINDOW_DESTROY: (0, 'destroy')}


@unittest.skipUnless(AVAILABLE, 'unicorn, pefile and the reviewed Silver are required')
class LoginWindowAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_bytes()
        cls.candidate = login.patch(source, INTER)
        cls.image = pefile.PE(data=cls.candidate).get_memory_mapped_image()
        cls.source_image = pefile.PE(data=source).get_memory_mapped_image()

    def machine(self, mode=0):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        size = (len(self.image) + 0xfff) & ~0xfff
        u.mem_map(login.BASE, size)
        u.mem_write(login.BASE, self.image)
        u.mem_write(login.BASE + login.MODE, struct.pack('<I', mode))
        for area in (DATA, STACK):
            u.mem_map(area, 0x10000)
        u.mem_map(STOP, 0x1000)
        self.calls = []
        strings = {}

        def hook(uc, address, size, user):
            if address == STOP:
                uc.emu_stop()
                return
            if address not in STUBS:
                return
            arguments, name = STUBS[address]
            sp = uc.reg_read(UC_X86_REG_ESP)
            ret = struct.unpack('<I', bytes(uc.mem_read(sp, 4)))[0]
            stack = struct.unpack(f'<{arguments}I', bytes(uc.mem_read(sp + 4, 4 * arguments))) if arguments else ()
            eax, edx, ecx = (uc.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
            result = eax
            if name == 'width':
                result = 7 * self.read_string(uc, eax)[1]
            elif name == 'localize':
                key = self.read_text(uc, eax)
                pointer = DATA + 0x8000 + 0x100 * len(strings)
                strings[key] = pointer
                self.write_string(uc, pointer, key.upper())
                uc.mem_write(edx, struct.pack('<I', pointer))
            elif name == 'render':
                inter = struct.unpack('<I', bytes(uc.mem_read(login.BASE + login.INTER_ON, 4)))[0]
                self.calls.append(('render', eax, inter))
            if name != 'render':
                self.calls.append((name, eax, edx, ecx, stack))
            uc.reg_write(UC_X86_REG_EAX, result)
            uc.reg_write(UC_X86_REG_ESP, sp + 4 + 4 * arguments)
            uc.reg_write(UC_X86_REG_EIP, ret)

        u.hook_add(UC_HOOK_CODE, hook)
        return u

    @staticmethod
    def write_string(u, pointer, text):
        u.mem_write(pointer - 12, struct.pack('<HHiI', 1200, 2, -1, len(text)) + text.encode('utf-16le') + b'\0\0')

    @staticmethod
    def read_string(u, pointer):
        if not pointer:
            return '', 0
        length = struct.unpack('<I', bytes(u.mem_read(pointer - 4, 4)))[0]
        return bytes(u.mem_read(pointer, 2 * length)).decode('utf-16le'), length

    @staticmethod
    def read_text(u, pointer):
        return LoginWindowAdapterTests.read_string(u, pointer)[0]

    def vmt(self, cls):
        return struct.unpack_from('<I', self.image, cls - login.BASE)[0]

    def native_window(self, u, extra_child=False):
        """The control tree GUI3_CreateLoginWindow builds (geometry from a live client)."""
        children = [(login.CLASS_BUTTON, (362, 6, 64, 16), ''), (login.CLASS_EDIT, (18, 50, 128, 22), ''),
                    (login.CLASS_EDIT, (18, 100, 128, 22), ''), (login.CLASS_LABEL, (20, 30, 100, 16), 'Имя игрока:'),
                    (login.CLASS_LABEL, (20, 80, 100, 16), 'Пароль:'), (login.CLASS_CHECK, (20, 142, 82, 16), 'Запомнить'),
                    (login.CLASS_LABEL, (174, 5, 100, 16), 'Сервисы'), (login.CLASS_AREA, (163, 10, 0, 0), ''),
                    (login.CLASS_LABEL, (174, 30, 100, 16), 'Правила игры'),
                    (login.CLASS_LABEL, (174, 50, 100, 16), 'Польз. соглашение'),
                    (login.CLASS_LABEL, (174, 70, 100, 16), 'Восстановление пароля'),
                    (login.CLASS_LABEL, (174, 90, 100, 16), 'Изменение пароля'),
                    (login.CLASS_BUTTON, (11, 180, 150, 25), 'Вход')]
        if extra_child:
            children.insert(1, (login.CLASS_LABEL, (0, 0, 10, 10), 'x'))
        list_object, items = DATA + 0x100, DATA + 0x200
        u.mem_write(WINDOW, bytes(0x400))
        u.mem_write(WINDOW + 0x2c, struct.pack('<I', list_object))
        u.mem_write(WINDOW + 0x30, struct.pack('<4i', 666, 342, 384, 224))
        u.mem_write(list_object + 4, struct.pack('<II', items, len(children)))
        self.controls = []
        for index, (cls, geometry, caption) in enumerate(children):
            control = DATA + 0x2000 + 0x300 * index
            u.mem_write(control, bytes(0x300))
            u.mem_write(control, struct.pack('<I', self.vmt(cls)))
            u.mem_write(control + 0x30, struct.pack('<4i', *geometry))
            u.mem_write(control + 0x49, b'\1')
            if caption:
                text = DATA + 0x6000 + 0x80 * index
                self.write_string(u, text, caption)
                u.mem_write(control + 0x5c, struct.pack('<I', text))
            u.mem_write(items + 4 * index, struct.pack('<I', control))
            self.controls.append(control)

    def call(self, u, entry, **registers):
        esp = STACK + 0x8000
        u.mem_write(esp, struct.pack('<I', STOP))
        u.reg_write(UC_X86_REG_ESP, esp)
        names = dict(eax=UC_X86_REG_EAX, ebx=UC_X86_REG_EBX, ecx=UC_X86_REG_ECX, edx=UC_X86_REG_EDX,
                     esi=UC_X86_REG_ESI, ebp=UC_X86_REG_EBP)
        for name, value in registers.items():
            u.reg_write(names[name], value)
        u.emu_start(entry, STOP, count=200000)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), esp + 4, 'stack balance')

    def relayout(self, u):
        frame = STACK + 0xc000
        u.mem_write(frame - 0x18, struct.pack('<I', WINDOW))
        u.mem_write(frame - 0x14, struct.pack('<I', DATA + 0x80))
        u.mem_write(DATA + 0x80, struct.pack('<I', 0xabcdef))
        self.call(u, login.BASE + login.RELAYOUT, ebp=frame)
        # The displaced `mov ecx,[ebp-14h]; mov ecx,[ecx]` still runs.
        self.assertEqual(u.reg_read(UC_X86_REG_ECX), 0xabcdef)

    def geometry(self, u, control):
        return struct.unpack('<4i', bytes(u.mem_read(control + 0x30, 16)))

    def state(self, u, offset):
        return struct.unpack('<I', bytes(u.mem_read(login.BASE + offset, 4)))[0]

    def test_new_interface_lays_out_panel_b(self):
        u = self.machine(mode=0)
        self.native_window(u)
        self.relayout(u)
        c = self.controls
        self.assertEqual(self.geometry(u, c[1]), (22, 54, 180, 22))
        self.assertEqual(self.geometry(u, c[2]), (214, 54, 180, 22))
        self.assertEqual(self.geometry(u, c[3])[:2], (24, 36))
        self.assertEqual(self.geometry(u, c[4])[:2], (216, 36))
        self.assertEqual(self.geometry(u, c[5])[:2], (414, 36))
        self.assertEqual(self.geometry(u, c[12])[:3], (410, 52, 142))
        self.assertEqual(self.geometry(u, c[7])[:2], (0, 0))
        self.assertEqual(bytes(u.mem_read(c[6] + 0x49, 1)), b'\0', 'Сервисы heading hidden')
        links = [self.geometry(u, c[i]) for i in range(8, 12)]
        widths = [7 * len(t) for t in ('Правила игры', 'Польз. соглашение', 'Восстановление пароля', 'Изменение пароля')]
        self.assertEqual([g[2] for g in links], widths)
        self.assertTrue(all(g[1] == login.LINK_Y for g in links))
        self.assertEqual(links[0][0], login.MARGIN)
        gaps = [links[i + 1][0] - links[i][0] - links[i][2] for i in range(3)]
        self.assertEqual(len(set(gaps)), 1)
        self.assertLessEqual(links[3][0] + links[3][2], login.WIDTH - login.MARGIN)
        separators = [self.state(u, login.SEPARATORS + 4 * k) for k in range(3)]
        self.assertEqual(separators, [links[k][0] + links[k][2] + gaps[0] // 2 for k in range(3)])
        bounds = next(call for call in self.calls if call[0] == 'bounds')
        self.assertEqual((bounds[1], bounds[4]), (WINDOW, (login.HEIGHT, login.WIDTH)))
        caption = next(call for call in self.calls if call[0] == 'caption')
        self.assertEqual(caption[1:3], (WINDOW, 0))
        self.assertTrue(any(call[0] == 'center' for call in self.calls))
        self.assertEqual(self.state(u, login.LOGIN_WINDOW), WINDOW)

    def test_original_interface_keeps_native_window(self):
        u = self.machine(mode=1)
        self.native_window(u)
        before = [self.geometry(u, c) for c in self.controls]
        self.relayout(u)
        self.assertEqual([self.geometry(u, c) for c in self.controls], before)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state(u, login.LOGIN_WINDOW), 0)

    def test_unknown_control_tree_stays_native(self):
        u = self.machine(mode=0)
        self.native_window(u, extra_child=True)
        before = [self.geometry(u, c) for c in self.controls]
        self.relayout(u)
        self.assertEqual([self.geometry(u, c) for c in self.controls], before)
        self.assertEqual(self.state(u, login.LOGIN_WINDOW), 0)
        self.assertEqual(self.state(u, login.ABORTED), 1)

    def test_paint_draws_title_lines_and_reminder(self):
        u = self.machine(mode=0)
        u.mem_write(login.BASE + login.LOGIN_WINDOW, struct.pack('<I', WINDOW))
        u.mem_write(login.BASE + login.SEPARATORS, struct.pack('<3I', 150, 300, 450))
        self.call(u, login.PAINT_HOOK, eax=0x1234, edx=1000, ecx=500)
        texts = [c for c in self.calls if c[0] == 'text']
        self.assertEqual([self.read_text(u, c[2]) for c in texts], ['MN15', 'M566'])
        title = texts[0]
        self.assertEqual(title[3], 1000 + (login.WIDTH - 7 * 4) // 2)       # centred x
        self.assertEqual(title[4], (0, login.PIXEL_FONT, login.TITLE, 500 + 6))  # flag, font, colour, y
        reminder = texts[1]
        left, top, right, _ = login.BOX
        self.assertEqual((reminder[1], reminder[3]), (right - left - 28, 1000 + left + 14))
        lines = [c for c in self.calls if c[0] == 'line']
        self.assertEqual(len(lines), 4 + 2 + 3 + 4 + 2)
        self.assertIn(('line', 1000 + 300, 500 + login.LINK_Y + 2, 12, (0, login.LINE)), lines)
        self.assertEqual(sum(1 for c in self.calls if c[0] == 'clear'), 2)

    def test_paint_without_layout_runs_native_prologue(self):
        u = self.machine(mode=0)
        hit = []
        u.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: (hit.append(a), uc.emu_stop()),
                   begin=login.PAINT_HOOK + 5, end=login.PAINT_HOOK + 5)
        esp = STACK + 0x8000
        u.mem_write(esp, struct.pack('<I', STOP)); u.reg_write(UC_X86_REG_ESP, esp)
        u.reg_write(UC_X86_REG_EBP, 0x77)
        u.emu_start(login.PAINT_HOOK, STOP, count=1000)
        self.assertEqual(hit, [login.PAINT_HOOK + 5])
        # push ebp; mov ebp,esp; push 0 executed exactly as before.
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), esp - 8)
        self.assertEqual(struct.unpack('<II', bytes(u.mem_read(esp - 8, 8))), (0, 0x77))

    def test_login_window_subtree_renders_inter(self):
        u = self.machine(mode=0)
        u.mem_write(login.BASE + login.LOGIN_WINDOW, struct.pack('<I', WINDOW))
        self.call(u, login.BASE + login.RENDER_WRAP, eax=WINDOW, ebx=0x5151)
        self.call(u, login.BASE + login.RENDER_WRAP, eax=WINDOW + 8, ebx=0x5151)
        self.assertEqual(self.calls, [('render', WINDOW, 1), ('render', WINDOW + 8, 0)])
        self.assertEqual(self.state(u, login.INTER_ON), 0)
        self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x5151)

    def test_destroying_login_window_forgets_it(self):
        u = self.machine(mode=0)
        u.mem_write(login.BASE + login.LOGIN_WINDOW, struct.pack('<I', WINDOW))
        self.call(u, login.BASE + login.DESTROY_WRAP, eax=WINDOW + 8)
        self.assertEqual(self.state(u, login.LOGIN_WINDOW), WINDOW)
        self.call(u, login.BASE + login.DESTROY_WRAP, eax=WINDOW)
        self.assertEqual(self.state(u, login.LOGIN_WINDOW), 0)
        self.assertEqual([c[0] for c in self.calls], ['destroy', 'destroy'])

    def run_font_stub(self, u, font):
        hit = []
        target = login.BASE + login.DRAW_TABLE + len(login.DRAW_TABLE_BYTES)
        u.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: (hit.append(uc.reg_read(UC_X86_REG_ESI)), uc.emu_stop()),
                   begin=target, end=target)
        u.reg_write(UC_X86_REG_EAX, font); u.reg_write(UC_X86_REG_EBX, login.BASE)
        u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        u.emu_start(login.BASE + login.DRAW_TABLE, STOP, count=1000)
        return hit[0]

    def test_pixel_role_uses_inter_table_only_inside_login_window(self):
        pixel = 0x0f0f0f0
        for inter_on, font, textures, expected in ((1, pixel, 1, login.INTER_HEADER),
                                                   (0, pixel, 1, login.FONT_TABLE),
                                                   (1, pixel + 4, 1, login.FONT_TABLE),
                                                   (1, pixel, 0, login.FONT_TABLE)):
            u = self.machine(mode=0)
            u.mem_write(login.BASE + login.PIXEL_HEADER + 4, struct.pack('<I', pixel))
            u.mem_write(login.BASE + login.INTER_ON, struct.pack('<I', inter_on))
            u.mem_write(login.BASE + login.INTER_HEADER + 0x18, struct.pack('<4I', 7, 7, 7, textures))
            self.assertEqual(self.run_font_stub(u, font), login.BASE + expected)

    def test_inter_header_matches_the_loaders_contract(self):
        header = self.image[login.INTER_HEADER:login.INTER_HEADER + 0x80]
        pixel = self.image[login.PIXEL_HEADER:login.PIXEL_HEADER + 0x80]
        self.assertEqual(header[:4], pixel[:4])
        count, glyphs = struct.unpack_from('<II', header, 8)
        self.assertEqual((count, glyphs), (160, login.GLYPHS))
        for density, percent in enumerate((100, 125, 150, 200)):
            path = struct.unpack_from('<I', header, 0x38 + 4 * density)[0]
            length = struct.unpack_from('<I', self.image, path + 8)[0]
            text = self.image[path + 12:path + 12 + 2 * length].decode('utf-16le')
            self.assertEqual(text, f'base\\ui-hd\\fonts\\inter-pixel-{percent}.png')
        self.assertEqual(self.image[login.INIT_COUNT:login.INIT_COUNT + 5], bytes.fromhex('bd0a000000'))
        self.assertEqual(self.image[login.UPLOAD_COUNT:login.UPLOAD_COUNT + 5], bytes.fromhex('b90a000000'))

    def test_only_reviewed_bytes_change(self):
        changed = [i for i, (a, b) in enumerate(zip(self.source_image, self.image)) if a != b]
        allowed = [(login.REGION, login.REGION + login.REGION_SIZE), (login.INTER_HEADER, login.INTER_HEADER + 0x80),
                   (login.rva(login.CREATE_HOOK), login.rva(login.CREATE_HOOK) + 5),
                   (login.rva(login.PAINT_HOOK), login.rva(login.PAINT_HOOK) + 5),
                   (login.DRAW_TABLE, login.DRAW_TABLE + 6), (login.INIT_COUNT + 1, login.INIT_COUNT + 2),
                   (login.UPLOAD_COUNT + 1, login.UPLOAD_COUNT + 2),
                   (login.rva(login.RENDER_SLOT), login.rva(login.RENDER_SLOT) + 4),
                   (login.rva(login.DESTROY_SLOT), login.rva(login.DESTROY_SLOT) + 4)]
        self.assertTrue(changed)
        self.assertTrue(all(any(lo <= i < hi for lo, hi in allowed) for i in changed))

    def test_rejects_other_silver(self):
        data = bytearray(SOURCE.read_bytes()); data[0x400] ^= 1
        with self.assertRaises(ValueError):
            login.patch(bytes(data), INTER)


if __name__ == '__main__':
    unittest.main()
