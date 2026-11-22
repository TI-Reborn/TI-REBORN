"""Execute the font metrics startup and caption swap inside the patched Silver image (Unicorn).

INIT (the Roboto adapter's loader), TI add_font, TI TFontLetterGroups.Spec and the
Silver caption draw are stubbed; TI font objects are plain memory, so the tests
check exactly which native fields the new code writes, which kerning pairs it hands
to the native setter and which font index the caption is drawn with.
"""
from pathlib import Path
import json
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / 'reports/ui-fonts-titles-20261120/source-silver.dll'

try:
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP,
                                   UC_X86_REG_ESP)
    from deploy import client_ui_font_metrics as metrics
    from deploy import client_ui_hd_fonts as roboto
    AVAILABLE = SOURCE.exists() and metrics.ASSET_MANIFEST.exists()
except ImportError:
    AVAILABLE = False

SILVER = 0x10000000           # relocated like the real process; the new code is base-independent
FONTS = 0x20000000            # ten fake TI font objects
FONT_SPAN = 0x200000
STACK, STOP = 0x40000000, 0x40f00000
TI_CODE = (0x6fc000, 0x4000)  # Spec and add_font
TI_DATA = (0x76d000, 0x2000)  # selector globals and the font manager
PIXEL_INDEX, TITLE_INDEX = 1, 42
SELECTOR_VAR = 0x76d100       # where [[0x76df40]] points: the selector-1 font index


@unittest.skipUnless(AVAILABLE, 'unicorn, pefile and the reviewed Silver are required')
class FontMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_bytes()
        cls.candidate = metrics.patch(cls.source)
        cls.image = pefile.PE(data=cls.candidate).get_memory_mapped_image()
        cls.manifest = json.loads(metrics.ASSET_MANIFEST.read_text(encoding='utf-8'))

    def machine(self, mode=0, install=1, prologue=metrics.PROLOGUE):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(SILVER, (len(self.image) + 0xfff) & ~0xfff)
        uc.mem_write(SILVER, bytes(self.image))
        uc.mem_map(FONTS, FONT_SPAN * len(metrics.ROLES))
        uc.mem_map(STACK, 0x100000)
        uc.mem_map(*TI_CODE)
        uc.mem_map(*TI_DATA)
        for native in (metrics.SPEC, metrics.ADD_FONT):
            uc.mem_write(native, prologue)
        uc.mem_write(metrics.SELECTOR_1, struct.pack('<I', SELECTOR_VAR))
        uc.mem_write(SELECTOR_VAR, struct.pack('<i', PIXEL_INDEX))
        uc.mem_write(metrics.FONT_MANAGER, struct.pack('<I', TI_DATA[0] + 0x10))
        uc.mem_write(TI_DATA[0] + 0x10, struct.pack('<I', 0x5a5a))
        uc.mem_write(SILVER + metrics.MODE, bytes([mode]))
        for index in range(len(metrics.ROLES)):  # native extra spacing before the patch
            uc.mem_write(self.font(index) + metrics.TI_EXTRA_SPACING, b'\x02\x05')
        self.calls = {'init': 0, 'add_font': [], 'spec': [], 'caption': []}
        init = SILVER + roboto.INIT - roboto.BASE
        caption = SILVER + metrics.CAPTION_DRAW - roboto.BASE

        def ret(stack_bytes, value=None):
            esp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EIP, struct.unpack('<I', uc.mem_read(esp, 4))[0])
            uc.reg_write(UC_X86_REG_ESP, esp + 4 + stack_bytes)
            if value is not None:
                uc.reg_write(UC_X86_REG_EAX, value & 0xffffffff)

        def hook(uc, address, size, _):
            if address == init:
                self.calls['init'] += 1
                uc.mem_write(SILVER + roboto.STATE, struct.pack('<i', 1))
                uc.mem_write(SILVER + roboto.STATE + 0xc, struct.pack('<i', install))
                for index in range(len(metrics.ROLES)):
                    header = SILVER + roboto.TABLE + index * roboto.HEADER_SIZE
                    uc.mem_write(header + 4, struct.pack('<I', self.font(index)))
                    uc.mem_write(self.font(index) + metrics.TI_KERNING, struct.pack('<I', 0x7000 + index))
                ret(0)
            elif address == metrics.ADD_FONT:
                self.calls['add_font'].append((uc.reg_read(UC_X86_REG_EAX),
                                               self.short(uc, uc.reg_read(UC_X86_REG_EDX)),
                                               self.short(uc, uc.reg_read(UC_X86_REG_ECX))))
                ret(0, TITLE_INDEX)
            elif address == metrics.SPEC:
                esp = uc.reg_read(UC_X86_REG_ESP)
                shift = struct.unpack('<i', uc.mem_read(esp + 4, 4))[0]
                self.calls['spec'].append((uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX),
                                           uc.reg_read(UC_X86_REG_ECX), shift))
                ret(4)
            elif address == caption:
                esp = uc.reg_read(UC_X86_REG_ESP)
                self.calls['caption'].append((
                    struct.unpack('<i', uc.mem_read(SELECTOR_VAR, 4))[0],
                    uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX), uc.reg_read(UC_X86_REG_ECX),
                    struct.unpack('<II', uc.mem_read(esp + 4, 8))))
                ret(8)
        uc.hook_add(UC_HOOK_CODE, hook, begin=TI_CODE[0], end=TI_CODE[0] + TI_CODE[1] - 1)
        uc.hook_add(UC_HOOK_CODE, hook, begin=init, end=init)
        uc.hook_add(UC_HOOK_CODE, hook, begin=caption, end=caption)
        return uc

    @staticmethod
    def short(uc, address):
        return bytes(uc.mem_read(address + 1, uc.mem_read(address, 1)[0])).decode()

    def call(self, uc, address, regs=(), stack=()):
        esp = STACK + 0xff000 - 4 * len(stack)
        uc.mem_write(esp, struct.pack('<I', STOP) + b''.join(struct.pack('<I', v) for v in stack))
        uc.reg_write(UC_X86_REG_ESP, esp)
        for register, value in regs:
            uc.reg_write(register, value)
        uc.emu_start(address, STOP)
        return uc.reg_read(UC_X86_REG_ESP) - esp

    def start(self, **kwargs):
        uc = self.machine(**kwargs)
        self.call(uc, SILVER + metrics.ENTRY)
        return uc

    def draw_caption(self, uc):
        regs = ((UC_X86_REG_EAX, 1), (UC_X86_REG_EDX, 0x1234), (UC_X86_REG_ECX, 77))
        return self.call(uc, SILVER + metrics.TITLE_DRAW, regs, stack=(0xffffffff, 99))

    @staticmethod
    def font(index):
        return FONTS + index * FONT_SPAN

    def record(self, uc, index, character):
        at = self.font(index) + metrics.TI_GLYPH + ord(character) * 28
        return struct.unpack('<7i', uc.mem_read(at, 28))

    def state(self, uc, offset=0):
        return struct.unpack('<i', uc.mem_read(SILVER + metrics.STATE_NEW + offset, 4))[0]

    def selector(self, uc):
        return struct.unpack('<i', uc.mem_read(SELECTOR_VAR, 4))[0]

    def test_original_interface_loads_and_starts_nothing(self):
        uc = self.start(mode=1)
        self.assertEqual((self.calls['init'], self.calls['add_font'], self.calls['spec']), (0, [], []))
        self.assertEqual(self.state(uc), 2)
        self.assertEqual(self.record(uc, 1, 'Т'), (0,) * 7)

    def test_original_interface_draws_captions_with_the_stock_font(self):
        uc = self.start(mode=1)
        self.assertEqual(self.draw_caption(uc), 4 + 8)  # ret 8 keeps the caller's stack ABI
        self.assertEqual(self.calls['caption'][0][0], PIXEL_INDEX)

    def test_new_interface_loads_the_title_font_from_native_pixel_files(self):
        uc = self.start()
        self.assertEqual(self.calls['add_font'], [(0x5a5a, 'base/fonts/pixel.xml', 'base/fonts/pixel.png')])
        title_header = SILVER + roboto.TABLE + metrics.TITLE * roboto.HEADER_SIZE
        pointer = struct.unpack('<I', uc.mem_read(title_header, 4))[0]
        index_at = struct.unpack('<I', uc.mem_read(pointer, 4))[0]
        self.assertEqual(struct.unpack('<i', uc.mem_read(index_at, 4))[0], TITLE_INDEX)

    def test_new_interface_writes_metrics_into_native_records(self):
        uc = self.start()
        self.assertEqual((self.calls['init'], self.state(uc)), (1, 1))
        for index, role in enumerate(self.manifest['fonts']):
            for glyph in role['glyphs']:
                top, x, y, width, height, leading, trailing = self.record(uc, index, chr(glyph['codepoint']))
                self.assertEqual((top, width, height, leading, trailing),
                                 (glyph['top'], glyph['advance'], glyph['height'], 0, 0))
            spacing = uc.mem_read(self.font(index) + metrics.TI_EXTRA_SPACING, 2)
            self.assertEqual(tuple(spacing), (0, role['space_advance']))

    def test_every_kerning_pair_goes_through_the_native_setter(self):
        uc = self.start()
        expected = [(0x7000 + index, a, b, s) for index, role in enumerate(self.manifest['fonts'])
                    for a, b, s in role['kerning']]
        self.assertEqual(self.calls['spec'], expected)
        self.assertEqual(self.state(uc, 8), len(expected))

    def test_caption_is_drawn_with_the_title_font_and_selector_restored(self):
        uc = self.start()
        self.assertEqual(self.draw_caption(uc), 4 + 8)
        index, eax, edx, ecx, stack = self.calls['caption'][0]
        self.assertEqual((index, eax, edx, ecx, stack), (TITLE_INDEX, 1, 0x1234, 77, (0xffffffff, 99)))
        self.assertEqual(self.selector(uc), PIXEL_INDEX)
        self.draw_caption(uc)
        self.assertEqual(self.calls['caption'][1][0], TITLE_INDEX)

    def menu_title_y(self, mode):
        uc = self.machine(mode=mode)
        self.call(uc, SILVER + metrics.MENU_TITLE_Y, ((UC_X86_REG_EAX, 300),), stack=(1, 2, 3, 0))
        slot = STACK + 0xff000  # 4th stack value: the caller's [esp+0Ch], behind the stub's return address
        return struct.unpack('<i', uc.mem_read(slot, 4))[0], uc.reg_read(UC_X86_REG_EAX)

    def test_main_menu_title_drops_in_the_new_interface(self):
        self.assertEqual(self.menu_title_y(0)[0], 300 + 0x16 + metrics.MENU_TITLE_DROP)

    def test_main_menu_title_keeps_its_place_in_the_original_interface(self):
        self.assertEqual(self.menu_title_y(1)[0], 300 + 0x16)

    def test_failed_install_keeps_native_metrics(self):
        uc = self.start(install=-1)
        self.assertEqual(self.state(uc), 0)
        self.assertEqual(self.record(uc, 1, 'Т'), (0,) * 7)
        self.assertFalse(self.calls['spec'])

    def test_changed_native_code_keeps_stock_fonts(self):
        uc = self.start(prologue=b'\xcc\xcc\xcc\xcc')
        self.assertEqual((self.calls['init'], self.calls['add_font']), (0, []))
        self.assertEqual(self.state(uc, 4), 1)
        self.draw_caption(uc)
        self.assertEqual(self.calls['caption'][0][0], PIXEL_INDEX)

    def test_metrics_and_title_font_are_applied_once(self):
        uc = self.machine()
        self.call(uc, SILVER + metrics.ENTRY)
        self.call(uc, SILVER + metrics.ENTRY)
        pairs = sum(len(role['kerning']) for role in self.manifest['fonts'])
        self.assertEqual((self.calls['init'], len(self.calls['add_font']), len(self.calls['spec'])), (2, 1, pairs))

    def test_adapter_headers_point_at_the_package(self):
        for index, role in enumerate(self.manifest['fonts']):
            header = roboto.TABLE + index * roboto.HEADER_SIZE
            count, glyphs = struct.unpack_from('<II', self.image, header + 8)
            self.assertEqual(count, len(role['glyphs']))
            glyph = role['glyphs'][0]
            self.assertEqual(struct.unpack_from('<IhhHH', self.image, glyphs),
                             (glyph['codepoint'], *glyph['visual_logical_box']))
            for density, atlas in enumerate(role['density_sets']):
                text_rva = struct.unpack_from('<I', self.image, header + 0x38 + density * 4)[0] + 0xc
                path = bytes(self.image[text_rva:text_rva + 2 * len(atlas['path'])]).decode('utf-16le')
                self.assertEqual(path, atlas['path'].replace('/', '\\'))

    def test_adapter_counts_ten_fonts(self):
        for rva, opcode in metrics.FONT_COUNT_SITES:
            self.assertEqual(bytes(self.image[rva:rva + 5]), bytes([opcode]) + struct.pack('<I', 10))

    def test_only_documented_bytes_change_in_the_old_image(self):
        changed = [i for i, (a, b) in enumerate(zip(self.source, self.candidate)) if a != b]
        with pefile.PE(data=self.source, fast_load=True) as pe:
            def span(rva, start, end):
                at = pe.get_offset_from_rva(rva)
                return set(range(at + start, at + end))
            allowed = (span(roboto.STARTUP - roboto.BASE, 1, 5) | span(metrics.CAPTION_JUMP, 1, 5)
                       | span(metrics.MENU_TITLE_SITE, 0, 7))
            for rva, _ in metrics.FONT_COUNT_SITES:
                allowed |= span(rva, 1, 5)
            for index in range(len(metrics.ROLES)):
                header = roboto.TABLE + index * roboto.HEADER_SIZE
                allowed |= span(header, 8, 0x10) | span(header, 0x28, 0x48)
            last, optional = pe.sections[-1], pe.OPTIONAL_HEADER
            for field_offset in (last.get_field_absolute_offset('Misc_VirtualSize'),
                                 last.get_field_absolute_offset('SizeOfRawData'),
                                 optional.get_field_absolute_offset('SizeOfImage'),
                                 optional.get_field_absolute_offset('CheckSum')):
                allowed |= set(range(field_offset, field_offset + 4))
        self.assertLessEqual(set(changed), allowed)
        self.assertEqual(len(self.candidate), len(self.source) + metrics.REGION_SIZE)


if __name__ == '__main__':
    unittest.main()
