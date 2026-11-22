"""Execute the HD map texture adapter around the native LoadFromFile call."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT/'work/battle-screen-fixes-20261016/deps'

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX, UC_X86_REG_EIP,
                                   UC_X86_REG_ESI, UC_X86_REG_ESP)
    sys.path.insert(0, str(ROOT))
    from tools import build_native_hd_map_textures as adapter
    AVAILABLE = DEPS.exists()
except ImportError:
    AVAILABLE = False

ALLOCATION, IAT_PAGE, DATA, STACK, STOP = 0x20000000, 0x789000, 0x30000000, 0x31000000, 0x31f00000
STREAM = 0x12345678


@unittest.skipUnless(AVAILABLE, 'unicorn and keystone required')
class NativeHdMapTextureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = adapter.build()

    def run_adapter(self, path, existing=(), directories=()):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        code = adapter.code_at(self.plan, ALLOCATION)
        u.mem_map(ALLOCATION, 0x1000); u.mem_write(ALLOCATION, code)
        u.mem_map(0x4b9000, 0x1000)
        u.mem_map(IAT_PAGE, 0x1000)
        u.mem_map(0x40000000, 0x1000)
        u.mem_write(adapter.GET_FILE_ATTRIBUTES_W_IAT, struct.pack('<I', 0x40000000))
        u.mem_map(DATA, 0x10000); u.mem_map(STACK, 0x10000); u.mem_map(STOP, 0x1000)
        text = path.encode('utf-16le')
        u.mem_write(DATA, struct.pack('<HHiI', 1200, 2, 1, len(path)) + text + b'\0\0')
        esp = STACK + 0x8000
        u.mem_write(esp, struct.pack('<I', STOP))
        u.reg_write(UC_X86_REG_ESP, esp)
        u.reg_write(UC_X86_REG_EAX, STREAM); u.reg_write(UC_X86_REG_EDX, DATA + 12)
        u.reg_write(UC_X86_REG_EBX, 0x0b0b0b0b); u.reg_write(UC_X86_REG_ESI, 0x05050505)
        seen = dict(queries=[], loaded=None)

        def read_wide(address):
            raw = bytearray()
            while True:
                pair = bytes(u.mem_read(address + len(raw), 2))
                if pair == b'\0\0':
                    return raw.decode('utf-16le')
                raw += pair

        def hook(uc, address, size, user):
            if address == 0x40000000:
                sp = uc.reg_read(UC_X86_REG_ESP)
                ret, name = struct.unpack('<II', bytes(uc.mem_read(sp, 8)))
                query = read_wide(name)
                seen['queries'].append(query)
                result = 0x10 if query in directories else 0x20 if query in existing else 0xffffffff
                uc.reg_write(UC_X86_REG_EAX, result)
                uc.reg_write(UC_X86_REG_ESP, sp + 8); uc.reg_write(UC_X86_REG_EIP, ret)
            elif address == adapter.LOAD_FROM_FILE:
                name = uc.reg_read(UC_X86_REG_EDX)
                header = struct.unpack('<HHiI', bytes(uc.mem_read(name - 12, 12)))
                seen['loaded'] = (uc.reg_read(UC_X86_REG_EAX), read_wide(name), header)
                sp = uc.reg_read(UC_X86_REG_ESP)
                uc.reg_write(UC_X86_REG_EIP, struct.unpack('<I', bytes(uc.mem_read(sp, 4)))[0])
                uc.reg_write(UC_X86_REG_ESP, sp + 4)
        u.hook_add(UC_HOOK_CODE, hook)
        u.emu_start(ALLOCATION, STOP, count=200000)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), esp + 4)
        self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x0b0b0b0b)
        self.assertEqual(u.reg_read(UC_X86_REG_ESI), 0x05050505)
        return seen

    def test_existing_hd_sheet_replaces_the_original_path(self):
        original = 'C:\\Games\\TIO\\base\\setting\\assault\\Assault_v1.png'
        hd = 'C:\\Games\\TIO\\base\\hd\\setting\\assault\\Assault_v1.png.hd'
        seen = self.run_adapter(original, existing={hd})
        self.assertEqual(seen['queries'], [hd[:-3] + '.2x.hd', hd])
        stream, loaded, header = seen['loaded']
        self.assertEqual((stream, loaded), (STREAM, hd))
        self.assertEqual(header, (1200, 2, -1, len(hd)))

    def test_double_density_sheet_takes_precedence(self):
        original = 'base\\setting\\military\\steel_box_01b.png'
        hd = 'base\\hd\\setting\\military\\steel_box_01b.png.hd'
        hd2 = hd[:-3] + '.2x.hd'
        seen = self.run_adapter(original, existing={hd, hd2})
        self.assertEqual(seen['queries'], [hd2])
        self.assertEqual(seen['loaded'], (STREAM, hd2, (1200, 2, -1, len(hd2))))

    def test_missing_hd_sheet_keeps_the_original_path(self):
        original = 'C:\\Games\\TIO\\base\\setting\\village\\village_table_02.png'
        seen = self.run_adapter(original)
        self.assertEqual(seen['loaded'][1], original)
        self.assertEqual(seen['loaded'][2][2], 1)

    def test_directory_with_hd_name_is_not_loaded(self):
        original = 'base\\setting\\a\\b.png'
        seen = self.run_adapter(original, directories={'base\\hd\\setting\\a\\b.png.hd'})
        self.assertEqual(seen['loaded'][1], original)

    def test_folder_case_is_ignored_and_relative_start_is_supported(self):
        seen = self.run_adapter('Setting\\NY\\x.png', existing={'hd\\Setting\\NY\\x.png.hd'})
        self.assertEqual(seen['loaded'][1], 'hd\\Setting\\NY\\x.png.hd')

    def test_paths_outside_setting_are_never_queried(self):
        for path in ('C:\\TIO\\base\\items\\ak47.png', 'C:\\TIO\\base\\settings\\x.png',
                     'C:\\TIO\\base\\mysetting\\x.png', 'short'):
            with self.subTest(path=path):
                seen = self.run_adapter(path)
                self.assertEqual(seen['queries'], [])
                self.assertEqual(seen['loaded'][1], path)

    def test_only_marked_png_uses_half_sized_logical_dimensions(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        for address in (ALLOCATION, DATA, STACK, STOP, 0x610000):
            u.mem_map(address, 0x10000)
        u.mem_write(ALLOCATION, adapter.code_at(self.plan, ALLOCATION))
        stream, png, texture = DATA, DATA + 0x100, DATA + 0x200
        esp = STACK + 0x8000
        sizes = (512, 256, 256, 512, 512, 256)
        u.mem_write(stream + 4, struct.pack('<II', png, 45))

        def create(uc, address, size, user):
            self.assertEqual(uc.reg_read(UC_X86_REG_EAX), 0x1234)
            self.assertEqual(uc.reg_read(UC_X86_REG_EDX), stream)
            sp = uc.reg_read(UC_X86_REG_ESP)
            resume, mipmaps, flags = struct.unpack('<III', bytes(uc.mem_read(sp, 12)))
            self.assertEqual((mipmaps, flags), (0, 1))
            uc.reg_write(UC_X86_REG_EAX, texture)
            uc.reg_write(UC_X86_REG_ESP, sp + 12)
            uc.reg_write(UC_X86_REG_EIP, resume)

        u.hook_add(UC_HOOK_CODE, create, begin=adapter.CREATE_TEXTURE, end=adapter.CREATE_TEXTURE)
        for chunk, gpu_handle, expected in ((b'tiOs', 0x123, tuple(n // 2 for n in sizes)),
                                             (b'IDAT', 0x123, sizes), (b'tiOs', 0, sizes)):
            with self.subTest(chunk=chunk, gpu_handle=gpu_handle):
                u.mem_write(png, b'\x89PNG\r\n\x1a\n' + bytes(29) + chunk + bytes(4))
                u.mem_write(texture + 0xc, struct.pack('<8I', gpu_handle, 0, *sizes))
                u.mem_write(esp, struct.pack('<III', STOP, 0, 1))
                u.reg_write(UC_X86_REG_ESP, esp)
                u.reg_write(UC_X86_REG_EAX, 0x1234)
                u.reg_write(UC_X86_REG_EDX, stream)
                u.reg_write(UC_X86_REG_ESI, 0x5678)
                u.emu_start(ALLOCATION + self.plan['dimensionsOffset'], STOP, count=1000)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), esp + 12)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), texture)
                self.assertEqual(u.reg_read(UC_X86_REG_ESI), 0x5678)
                self.assertEqual(struct.unpack('<I', bytes(u.mem_read(texture + 0xc, 4)))[0], gpu_handle)
                self.assertEqual(struct.unpack('<6I', bytes(u.mem_read(texture + 0x14, 24))), expected)

    def test_overlong_path_is_left_to_the_original_loader(self):
        path = 'C:\\' + 'x' * adapter.MAX_PATH_CHARS + '\\setting\\a.png'
        seen = self.run_adapter(path)
        self.assertEqual((seen['queries'], seen['loaded'][1]), ([], path))

    def test_call_site_matches_the_pinned_image_call(self):
        self.assertEqual((self.plan['callSite'], self.plan['callSiteBytes']), (0x6b12f9, 'e8867de0ff'))

    def test_pinned_image_holds_the_expected_call(self):
        image = Path.home()/'AppData/Local/TIO-Online/ti.exe'
        if not image.exists():
            self.skipTest('installed client required')
        import hashlib
        import pefile
        raw = image.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         'd2c2343f89ed253695fff615fd504b80585b8c7fbbfed139b28e1bbe5fe0dfa0')
        with pefile.PE(data=raw, fast_load=True) as pe:
            offset = pe.get_offset_from_rva(adapter.CALL_SITE - 0x400000)
            dimensions_offset = pe.get_offset_from_rva(adapter.DIMENSIONS_SITE - 0x400000)
        self.assertEqual(raw[offset:offset + 5].hex(), self.plan['callSiteBytes'])
        self.assertEqual(raw[dimensions_offset:dimensions_offset + 5].hex(), self.plan['dimensionsSiteBytes'])


if __name__ == '__main__':
    unittest.main()
