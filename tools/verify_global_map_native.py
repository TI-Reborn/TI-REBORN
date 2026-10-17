"""Execute the real appended x86 projection, drawing scope and picking in Unicorn.

Loader/GPU/tooltip/transport boundaries are fixtures; the checked candidate
thunks and original native avatar tail/rounding execute. This is automated ABI
evidence, not graphical-client or hosted multiplayer validation.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_global_map as a

DATA, STACK, STOP = 0x30000000, 0x31000000, 0x300fff00
CALLEE = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
CANARIES = (0x12345678, 0x23456789, 0x3456789a, 0x456789ab)


def put(u, address, value):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get(u, address):
    return struct.unpack('<I', u.mem_read(address, 4))[0]


def signed(value):
    return value - 0x100000000 if value & 0x80000000 else value


@lru_cache(maxsize=2)
def mapped(candidate, base):
    p = pefile.PE(data=candidate); p.relocate_image(base)
    return p.get_memory_mapped_image()


class Fixture:
    def __init__(self, candidate, base, viewport=(144, 42, 1858, 874)):
        self.base = base
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        raw = mapped(candidate, base)
        self.u.mem_map(base, (len(raw) + 4095) & ~4095); self.u.mem_write(base, raw)
        self.u.mem_map(DATA, 0x100000); self.u.mem_map(STACK, 0x10000)
        self.u.mem_map(0, 0x1000)
        self.u.reg_write(UC_X86_REG_FPCW, 0x37f)
        self.quads, self.loads, self.travel, self.town_scopes = [], [], [], []
        self.avatar_calls, self.camera_updates, self.entries = [], 0, 0
        self.paths = []
        self.stock_fallback = []
        self.fail_asset, self.modal, self.input_allowed = None, False, True
        self.viewport, self.towns = viewport, []
        self.table, self.character = DATA + 0x104, DATA + 0x2000
        for va, address in ((0xac5a4c, DATA + 0x40), (0xac5b70, DATA + 0x60),
                            (0xac5a04, DATA + 0x64), (0xac5b7c, self.character),
                            (0xac5d58, DATA + 0x68), (0xac5dec, DATA + 0x70),
                            (0xac5630, DATA + 0x80), (0xac60a4, self.va(0xb749ec))):
            put(self.u, self.va(va), address)
        for i, v in enumerate(viewport): put(self.u, DATA + 0x40 + 4 * i, v)
        put(self.u, DATA + 0x68, -1); put(self.u, DATA + 0x70, 1)
        put(self.u, self.va(0xb749e4), self.table)
        put(self.u, self.va(0xb749ec), 0x43b00000); put(self.u, self.va(0xb749f0), 0x43900000)
        self.u.mem_write(self.character + 0x1c, struct.pack('<ff', 190.0, -20.0))
        put(self.u, self.character + 0x0c, 190); put(self.u, self.character + 0x10, -20)
        put(self.u, self.character + 0x14, 265); put(self.u, self.character + 0x18, -397)
        put(self.u, self.character + 0x224, -1)
        for pointer in (0xac614c, 0xac5668): put(self.u, self.va(pointer), DATA + 0x800)
        catalog = json.loads((ROOT / 'assets/global-map-v2/catalog.json').read_text(encoding='utf-8'))
        from tools.build_global_map_assets import _authority
        authority, _ = _authority(ROOT / 'reports/global-map-integration-20261010/baseline/runtime/evidence/zones_diagnostic.xml')
        for index, item in enumerate(catalog['locations']):
            item = dict(item, server_bounds_world=item['bounds_world'],
                        bounds_world=authority[item['id']]['native_bounds'],
                        authority_enabled=authority[item['id']]['enabled'])
            address = DATA + 0x4000 + index * 0x400
            raw = bytearray(a.TOWN_SIZE); raw[4] = int(item['authority_enabled']); raw[8] = item['id']
            raw[12] = 1; name = item['name'].encode(); raw[13] = len(name); raw[14:14 + len(name)] = name
            struct.pack_into('<4i', raw, 0x210, *item['bounds_world'])
            self.u.mem_write(address, bytes(raw)); put(self.u, self.table + index * 4, address)
            self.towns.append((address, bytes(raw), item))
        put(self.u, self.table - 4, len(self.towns))
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def va(self, address): return self.base + address - a.IMAGE_BASE

    def ret(self, extra=0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, get(self.u, sp)); self.u.reg_write(UC_X86_REG_ESP, sp + 4 + extra)

    def text(self, address):
        length = get(self.u, address - 4)
        return bytes(self.u.mem_read(address, length * 2)).decode('utf-16le')

    def hook(self, u, address, size, _):
        eax, edx, ecx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        sp = u.reg_read(UC_X86_REG_ESP)
        if address == self.va(0x4f2c50):
            path = self.text(eax); self.loads.append(path)
            handle = 0 if path == self.fail_asset else 0x1000 + len(self.loads)
            u.mem_write(ecx, struct.pack('<I4H', handle, 1254, 1254, 1254, 1254)); self.ret()
        elif address == self.va(0x4f2910):
            flags, color, frame, height, width = [get(u, sp + 4 * i) for i in range(1, 6)]
            self.quads.append({'descriptor': eax, 'handle': get(u, eax), 'x': signed(edx), 'y': signed(ecx),
                               'width': width, 'height': height, 'frame': frame, 'color': color, 'flags': flags})
            self.ret(20)
        elif address == self.va(0x9ebda4):
            pointer = get(u, self.va(0xb749e4))
            entries = []
            for i in range(get(u, pointer - 4)):
                town = get(u, pointer + i * 4)
                entries.append({'id': bytes(u.mem_read(town + 8, 1))[0],
                                'bounds': list(struct.unpack('<4i', bytes(u.mem_read(town + 0x210, 16))))})
            assert get(u, self.va(0xb749ec)) == get(u, self.va(0xb749f0)) == 0
            # Simulate the exact mutable native city-info throttle/cache fields.
            hover = get(u, pointer + 4 * 4)
            put(u, hover + 0x250, 10000); u.mem_write(hover + 0x234, bytes((2, 2, 2)))
            self.town_scopes.append(entries); self.ret()
        elif address == self.va(0x9edef4): self.camera_updates += 1; self.ret()
        elif address in (self.va(0x4f2eb4), self.va(0x4f2998), self.va(0x4f2ee8)): self.ret()
        elif address == self.va(0x4f27fc): self.avatar_calls.append((address, edx, ecx)); self.ret(12)
        elif address == self.va(0x4f2788):
            y, x = struct.unpack('<ff', bytes(u.mem_read(sp + 4, 8)))
            self.avatar_calls.append((address, x, y)); self.ret(8)
        elif address == self.va(0xa62988): u.reg_write(UC_X86_REG_EAX, int(self.modal)); self.ret()
        elif address == self.va(0x66754c): u.reg_write(UC_X86_REG_EAX, int(self.input_allowed)); self.ret()
        elif address == self.va(0x889e5c): self.travel.append((signed(eax), signed(edx))); self.ret()
        elif address == self.va(0x8596e0): self.entries += 1; self.ret()
        elif address == self.va(0x6750e4):
            self.paths.append((signed(eax), signed(edx), signed(ecx), signed(get(u, sp + 8)), get(u, sp + 4)))
            self.ret(8)
        elif address in (self.va(a.STOCK_DRAW), self.va(a.STOCK_CLICK)):
            self.stock_fallback.append(address); self.ret()

    def run(self, address, eax=0, edx=0, ecx=0, *, silver_base=False):
        sp = STACK + 0x8000; put(self.u, sp, STOP)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        for r, value in zip(CALLEE, CANARIES): self.u.reg_write(r, value)
        if silver_base: self.u.reg_write(UC_X86_REG_EBX, self.base)
        for r, value in ((UC_X86_REG_EAX, eax), (UC_X86_REG_EDX, edx), (UC_X86_REG_ECX, ecx)):
            self.u.reg_write(r, value)
        self.u.emu_start(self.va(address), STOP, count=1000000)
        assert self.u.reg_read(UC_X86_REG_EIP) == STOP
        assert self.u.reg_read(UC_X86_REG_ESP) == sp + 4
        if not silver_base: assert tuple(self.u.reg_read(r) for r in CALLEE) == CANARIES
        return signed(self.u.reg_read(UC_X86_REG_EAX))

    def mouse(self, x, y): put(self.u, DATA + 0x60, x); put(self.u, DATA + 0x64, y)


def preservation(source, candidate):
    p, q = pefile.PE(data=source), pefile.PE(data=candidate)
    fields = [('section virtual size', p.sections[-1].get_field_absolute_offset('Misc_VirtualSize'), 4),
              ('section raw size', p.sections[-1].get_field_absolute_offset('SizeOfRawData'), 4),
              ('PE image size', p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4),
              ('PE checksum', p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 4)]
    for va, length in ((0x9ee150, 6), (0x9ee684, 6), (0xa6b1aa, 5)):
        fields.append((f'native map hook {va:#x}', p.get_offset_from_rva(va - a.IMAGE_BASE), length))
    for va, before, _ in a.visual.native_edits(a):
        fields.append((f'scoped native ring/name hook {va:#x}', p.get_offset_from_rva(va - a.IMAGE_BASE), len(before)))
    changes = []
    masked = bytearray(candidate[:len(source)])
    for purpose, offset, size in sorted(fields, key=lambda x: x[1]):
        before, after = source[offset:offset + size], candidate[offset:offset + size]
        changes.append({'offset': offset, 'size': size, 'source_sha256': a.sha(before),
                        'candidate_sha256': a.sha(after), 'purpose': purpose,
                        'source_hex': before.hex(), 'candidate_hex': after.hex()})
        masked[offset:offset + size] = before
    assert bytes(masked) == source
    appended = candidate[len(source):]
    assert q.get_data(a.REGION, a.SIZE) == a.extension()
    return {'source_sha256': a.sha(source), 'candidate_sha256': a.sha(candidate),
            'source_size': len(source), 'candidate_size': len(candidate),
            'changes': changes, 'appended_size': len(appended), 'appended_sha256': a.sha(appended),
            'append_padding': len(appended) - a.SIZE, 'region_rva': a.REGION,
            'region_size': a.SIZE, 'mapped_extension_sha256': a.sha(a.extension()),
            'all_undeclared_source_bytes_unchanged': True,
            'number_of_sections_unchanged': p.FILE_HEADER.NumberOfSections == q.FILE_HEADER.NumberOfSections,
            'size_of_image': q.OPTIONAL_HEADER.SizeOfImage, 'metadata': a.metadata()}


def verify(source, output):
    candidate = a.patch(source); cases = []
    for base in (0x10000000, 0x17000000):
        for viewport in ((144, 42, 1858, 874), (144, 42, 2324, 919), (144, 42, 758, 394),
                         (144, 42, 918, 394), (144, 42, 1238, 514)):
            f = Fixture(candidate, base, viewport)
            f.run(a.INITIALIZE); assert len(f.loads) == 23
            assert get(f.u, base + a.STATE) == 1
            original_char = bytes(f.u.mem_read(f.character, 0x22c))
            offsets = bytes(f.u.mem_read(f.va(0xb749ec), 16))
            f.run(0x9ee150)
            left, top, right, bottom = viewport; width, height = right - left, bottom - top
            assert len(f.quads) == 23
            assert [f.quads[0][k] for k in ('x', 'y', 'width', 'height')] == [left, top, width, height]
            for quad, (_, raw, item) in zip(f.quads[1:], f.towns):
                x1, y1, x2, y2 = item['bounds_world']
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                x, y = left + ((cx + 512) * width) // 1024, top + ((cy + 512) * height) // 1024
                assert quad['width'] == quad['height']
                assert quad['x'] == x - quad['width'] // 2 and quad['y'] == y - quad['height'] // 2
                assert quad['color'] == 0xffffffff and quad['frame'] == quad['flags'] == 0
            for actual, (_, raw, item) in zip(f.town_scopes[-1], f.towns):
                b = item['bounds_world']
                expected = [left + ((b[0] + 512) * width) // 1024, top + ((b[1] + 512) * height) // 1024,
                            left + ((b[2] + 512) * width) // 1024, top + ((b[3] + 512) * height) // 1024]
                assert actual['bounds'] == expected
            assert get(f.u, f.va(0xb749e4)) == f.table
            for index, (address, raw, _) in enumerate(f.towns):
                expected = bytearray(raw)
                if index == 4:
                    struct.pack_into('<I', expected, 0x250, 10000); expected[0x234:0x237] = bytes((2, 2, 2))
                assert bytes(f.u.mem_read(address, len(raw))) == bytes(expected)
            assert bytes(f.u.mem_read(f.character, 0x22c)) == original_char
            assert bytes(f.u.mem_read(f.va(0xb749ec), 16)) == offsets
            assert len(f.avatar_calls) >= 1
            assert f.paths == [(left + (702 * width) // 1024, top + (492 * height) // 1024,
                                left + (777 * width) // 1024, top + (115 * height) // 1024, 0xffd1bd82)]
            points = [(left, top), (right - 1, bottom - 1), (left + width // 2, top + height // 2)]
            for px, py in points:
                f.mouse(px, py); f.run(0x9ee684)
                assert f.travel[-1] == (((px - left) * 1024) // width - 512,
                                        ((py - top) * 1024) // height - 512)
            count = len(f.travel)
            for px, py in ((left - 1, top), (right, top), (left, top - 1), (left, bottom)):
                f.mouse(px, py); f.run(0x9ee684)
            assert len(f.travel) == count
            f.modal = True; f.mouse(left + 20, top + 20); f.run(0x9ee684)
            assert len(f.travel) == count; f.modal = False
            town_clicks = []
            for _, _, item in f.towns:
                if not item['authority_enabled']: continue
                x1, y1, x2, y2 = item['bounds_world']
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                px, py = left + ((cx + 512) * width) // 1024, top + ((cy + 512) * height) // 1024
                f.mouse(px, py); f.run(0x9ee684); wx, wy = f.travel[-1]
                sx1, sy1, sx2, sy2 = item['server_bounds_world']
                assert x1 <= wx <= x2 and y1 <= wy <= y2
                assert sx1 <= wx <= sx2 and sy1 <= wy <= sy2
                town_clicks.append({'id': item['id'], 'native_center': [cx, cy],
                                    'mouse': [px, py], 'native_request': [wx, wy]})
            assert len(town_clicks) == 21
            count = len(f.travel)
            put(f.u, DATA + 0x68, 5)
            cx, cy = left + (702 * width) // 1024, top + (492 * height) // 1024
            f.mouse(cx, cy); f.run(0x9ee684); assert f.entries == 1 and len(f.travel) == count
            drawn = len(f.quads); f.run(0x9ee150, 1); assert len(f.quads) == drawn
            # An incomplete resource set delegates both paths back to stock.
            f.fail_asset = a.resources()[12]['path']; f.run(a.INITIALIZE)
            assert get(f.u, base + a.STATE) == 0xffffffff
            f.run(0x9ee150); f.run(0x9ee684)
            assert f.stock_fallback == [f.va(a.STOCK_DRAW), f.va(a.STOCK_CLICK)]
            cases.append({'silver_base': hex(base), 'logical_viewport': viewport, 'resources': len(f.loads),
                          'quads': drawn, 'town_geometry_unchanged': True, 'avatar_unchanged': True,
                          'native_hover_throttle_preserved': True, 'movement_path': f.paths,
                          'enabled_town_center_clicks': town_clicks,
                          'partial_load_uses_original_render_and_click': True,
                          'inside_clicks': f.travel, 'outside_clicks_ignored': True,
                          'modal_click_ignored': True, 'native_city_entry': f.entries,
                          'update_only_does_not_draw': True})
    for bad_sha in ('0' * 64, a.sha(candidate)):
        try: a.patch(source, expected_sha=bad_sha)
        except ValueError: pass
        else: raise AssertionError('SHA guard failed')
    report = preservation(source, candidate)
    report.update({'method': __doc__, 'cases': cases, 'passed': True,
                   'graphical_validation': 'Required separately with actual native clients'})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return candidate, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    args = parser.parse_args()
    candidate, report = verify(args.source.read_bytes(), args.output)
    args.candidate.parent.mkdir(parents=True, exist_ok=True); args.candidate.write_bytes(candidate)
    print(json.dumps({'passed': True, 'cases': len(report['cases']),
                      'candidate_sha256': report['candidate_sha256'], 'candidate_size': len(candidate)}))


if __name__ == '__main__': main()
