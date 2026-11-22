"""Execute the published x86 city/shop branches with UI/transport boundaries stubbed."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP

from test_contracts_map_view_native import NativeMapView

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'reports/player-errors-20261103/client/source-silver.dll'
SOURCE_SHA = '076bc1c789f2e3ab086b359f376d13fc7b1661307d44dc821604bb4dd39d94be'
DATA, STACK, STOP = 0x2000000, 0x3000000, 0x3000100


def candidate() -> bytes:
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('Published source changed')
    module = ROOT / 'deploy/client_city_request_fixes.py'
    if module.exists():
        spec = importlib.util.spec_from_file_location('city_patch', module)
        patch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(patch)
        return patch.patch(raw)
    return raw


class CityRequestNativeTests(unittest.TestCase):
    def test_shop_catalogue_is_sent_while_another_response_is_pending(self):
        image = pefile.PE(data=candidate()).get_memory_mapped_image()
        for category in (0, 1, 3):
            with self.subTest(category=category):
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(0x400000, (len(image)+4095)&~4095)
                u.mem_write(0x400000, image)
                u.mem_map(DATA, 0x10000); u.mem_map(STACK, 0x10000)
                def put(at, value):
                    u.mem_write(at, struct.pack('<I', value))
                def get(at):
                    return struct.unpack('<I', u.mem_read(at, 4))[0]
                obj, handle, vtable, flush = DATA+0x1000, DATA+0x3000, DATA+0x3100, DATA+0x3200
                put(0xac600c, handle); put(handle, obj); put(obj, vtable); put(vtable, flush)
                put(0xac5940, DATA+0x3300); u.mem_write(DATA+0x3300, b'\1')
                def hook(_u, address, _size, _data):
                    if address == 0x6748b0:
                        u.reg_write(UC_X86_REG_EAX, handle)
                    elif address not in (flush, 0x9dc760):
                        return
                    sp = u.reg_read(UC_X86_REG_ESP)
                    u.reg_write(UC_X86_REG_EIP, get(sp)); u.reg_write(UC_X86_REG_ESP, sp+4)
                u.hook_add(UC_HOOK_CODE, hook)
                put(STACK+0x8000, STOP); u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
                u.reg_write(UC_X86_REG_EAX, category)
                u.emu_start(0x991940, STOP, count=2000)
                self.assertEqual(u.reg_read(UC_X86_REG_EIP), STOP)
                self.assertEqual(bytes(u.mem_read(obj+4, get(obj+0x1004))), bytes((0x73, category)))

    def test_city_open_selects_renderer_without_localized_level_warning(self):
        native = NativeMapView(SOURCE.read_bytes(), mode=0)
        pe = pefile.PE(data=candidate())
        native.u.mem_write(0x7d26e2, pe.get_data(0x3d26e2, 17))
        formats = []
        def observe(u, address, _size, _data):
            if address == 0x7d1350:
                formats.append(address)
            if address in (0x7d3d59, 0x7d3e0b):
                u.emu_stop()
        native.u.hook_add(UC_HOOK_CODE, observe)
        native.put(STACK+0x8000, STOP)
        native.u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
        native.u.emu_start(0x7d26e2, 0x7d3e0b, count=10000)
        self.assertEqual(native.mode, 1)
        self.assertEqual(formats, [])

    def test_gold_still_requests_ordinary_catalogue_before_premium(self):
        pe = pefile.PE(data=candidate())
        self.assertEqual(pe.get_data(0x574d71, 14), bytes.fromhex('33c0e8c8cb010033c0e801cc0100'))
