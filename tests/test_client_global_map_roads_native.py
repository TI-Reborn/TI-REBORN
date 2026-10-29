"""Execute the road-map (v3) native code of the patched Silver in Unicorn.

Needs pefile/unicorn and the published 2026.10.28.2 Silver: TIO_SILVER, or the
installed client in %LOCALAPPDATA%/TIO-Online. Loader, renderer and GPU calls
are fixtures; the appended code, the original 1D reader and Delphi rounding run.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'assets/global-map-v3/manifest.json').read_text(encoding='utf-8'))
try:
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                                   UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI,
                                   UC_X86_REG_ESP, UC_X86_REG_FPCW)
    from deploy import client_global_map as v2
    from deploy import client_global_map_roads as roads
except ImportError:  # Research extras are optional outside the full suite.
    pefile = None

DATA, STACK, STOP = 0x30000000, 0x31000000, 0x300fff00
CALLEE = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP) if pefile else ()
CANARIES = (0x12345678, 0x23456789, 0x3456789a, 0x456789ab)
VIEWPORT = (144, 42, 1858, 874)  # left, top, right, bottom of the map area


def source():
    path = Path(os.environ.get('TIO_SILVER') or Path(os.environ.get('LOCALAPPDATA', '')) / 'TIO-Online/silver.dll')
    if pefile is None or not path.is_file():
        return None
    raw = path.read_bytes()
    return raw if hashlib.sha256(raw).hexdigest() == roads.BASE_SHA else None


@lru_cache(maxsize=1)
def candidate():
    return roads.patch(source(), MANIFEST)


@lru_cache(maxsize=2)
def mapped(base):
    image = pefile.PE(data=candidate()); image.relocate_image(base)
    return image.get_memory_mapped_image()


def put(u, address, value):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get(u, address):
    return struct.unpack('<I', u.mem_read(address, 4))[0]


def signed(value):
    return value - 0x100000000 if value & 0x80000000 else value


class Fixture:
    def __init__(self, base, towns):
        self.base = base
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        raw = mapped(base)
        self.u.mem_map(base, (len(raw) + 4095) & ~4095); self.u.mem_write(base, raw)
        self.u.mem_map(DATA, 0x100000); self.u.mem_map(STACK, 0x10000)
        self.u.reg_write(UC_X86_REG_FPCW, 0x37f)
        self.loads, self.quads, self.texts, self.renders = [], [], [], 0
        self.lines, self.tips = [], []
        self.table, self.character = DATA + 0x104, DATA + 0x2000
        for va, address in ((0xac5a4c, DATA + 0x40), (0xac5b70, DATA + 0x60), (0xac5a04, DATA + 0x64),
                            (0xac5b7c, self.character), (0xac5d58, DATA + 0x68), (0xac57ac, DATA + 0x6c),
                            (0xac5a98, DATA + 0x70), (0xac60a4, DATA + 0x80)):
            put(self.u, self.va(va), address)
        for i, value in enumerate(VIEWPORT):
            put(self.u, DATA + 0x40 + 4 * i, value)
        put(self.u, DATA + 0x68, -1)
        put(self.u, DATA + 0x70, 42)
        put(self.u, self.va(0xb749e4), self.table)
        self.u.mem_write(self.character + 0x1c, struct.pack('<ff', 0.0, 0.0))
        for index, (town, enabled, bounds) in enumerate(towns):
            address = DATA + 0x4000 + index * 0x400
            record = bytearray(v2.TOWN_SIZE); record[4] = enabled; record[8] = town
            struct.pack_into('<4i', record, 0x210, *bounds)
            self.u.mem_write(address, bytes(record)); put(self.u, self.table + index * 4, address)
        put(self.u, self.table - 4, len(towns))
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def va(self, address):
        return self.base + address - v2.IMAGE_BASE

    def ret(self, extra=0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, get(self.u, sp)); self.u.reg_write(UC_X86_REG_ESP, sp + 4 + extra)

    def text(self, address):
        return bytes(self.u.mem_read(address, get(self.u, address - 4) * 2)).decode('utf-16le')

    def hook(self, u, address, size, _):
        eax, edx, ecx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        sp = u.reg_read(UC_X86_REG_ESP)
        if address == self.va(0x4f2c50):
            self.loads.append(self.text(eax)); u.mem_write(ecx, struct.pack('<I', 0x1000 + len(self.loads))); self.ret()
        elif address == self.va(0x4f2910):
            flags, color, frame, height, width = (get(u, sp + 4 * i) for i in range(1, 6))
            self.quads.append({'row': eax - self.base, 'x': signed(edx), 'y': signed(ecx),
                               'width': width, 'height': height, 'color': color})
            self.ret(20)
        elif address == self.va(0x4f2a0c):
            self.texts.append(eax); self.ret(8)
        elif address == self.va(0x9ebda4):
            self.renders += 1; self.ret()
        elif address == self.va(roads.LINE):
            self.lines.append((signed(eax), signed(edx), signed(ecx), signed(get(u, sp + 8)), get(u, sp + 4)))
            self.ret(8)
        elif address in (self.va(roads.TOWN_TIP), self.va(roads.BASE_TIP)):
            self.tips.append({'function': address - self.base + v2.IMAGE_BASE, 'x': signed(eax), 'y': signed(edx),
                              'index': ecx, 'argument': get(u, sp + 4), 'camera': get(u, DATA + 0x88)})
            self.ret(4)
        elif address in (self.va(0x9edef4), self.va(0x4f2eb4), self.va(0x4f2998), self.va(0x4f2ee8)):
            self.ret()

    def run(self, address, eax=0, *, frame_esi=None):
        sp = STACK + 0x8000; put(self.u, sp, STOP)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        for register, value in zip(CALLEE, CANARIES):
            self.u.reg_write(register, value)
        if frame_esi is not None:
            self.u.reg_write(UC_X86_REG_ESI, frame_esi)
        self.u.reg_write(UC_X86_REG_EAX, eax)
        self.u.emu_start(self.va(address), STOP, count=2000000)
        assert self.u.reg_read(UC_X86_REG_EIP) == STOP

    def state(self, offset):
        return signed(get(self.u, self.base + v2.STATE + offset))

    def draw(self):
        self.quads.clear(); self.run(v2.DRAW)
        return self.quads

    def mouse(self, x, y):
        put(self.u, DATA + 0x60, x); put(self.u, DATA + 0x64, y)

    def squad(self, stepped, rendered, destination, moving):
        put(self.u, self.character + 0x0c, stepped[0]); put(self.u, self.character + 0x10, stepped[1])
        put(self.u, self.character + 0x14, destination[0]); put(self.u, self.character + 0x18, destination[1])
        self.u.mem_write(self.character + 0x1c, struct.pack('<ff', *rendered))
        put(self.u, self.character + 0x224, -1 if moving else 0)


def row(index):
    return roads.ROWS + index * roads.ROW_SIZE


def location_rows():
    order = sorted(location['id'] for location in MANIFEST['locations'])
    return {town: (row(1 + 2 * k), row(2 + 2 * k)) for k, town in enumerate(order)}


@unittest.skipIf(pefile is None or source() is None, 'needs pefile/unicorn and the published 2026.10.28.2 Silver')
class RoadMapNativeTests(unittest.TestCase):
    from tio.locations import TOWNS as _towns
    TOWNS = [(1, 0, (-293, -132, -213, -52))] + [(town, 1, bounds) for town, bounds in sorted(_towns.items())]

    def fixture(self, base=0x10000000):
        f = Fixture(base, self.TOWNS)
        f.run(v2.INITIALIZE)
        self.assertEqual(f.state(v2.READY), 1)
        return f

    def screen(self, f, rect):
        left, top, right, bottom = VIEWPORT
        width, height = right - left, bottom - top
        x0, y0, x1, y1 = rect
        return (left + x0 * width // 1819, top + y0 * height // 865,
                left + x1 * width // 1819 - (left + x0 * width // 1819),
                top + y1 * height // 865 - (top + y0 * height // 865))

    def test_loader_reads_map_highlights_and_marker_in_row_order(self):
        f = self.fixture()
        self.assertEqual(f.loads, roads.rows(MANIFEST))
        self.assertEqual(len(f.loads), 1 + 2 * 21 + 32)

    def test_current_town_is_outlined_and_hover_lights_only_its_location_over_a_dimmed_map(self):
        for base in (0x10000000, 0x17000000):
            f = self.fixture(base)
            put(f.u, DATA + 0x68, 3)
            quads = f.draw()
            self.assertEqual(quads[0]['row'], roads.ROWS)
            self.assertEqual(quads[0]['color'], roads.BASE_COLOR)
            self.assertEqual(quads[0]['width'], VIEWPORT[2] - VIEWPORT[0])
            reservation = next(l for l in MANIFEST['locations'] if l['id'] == 3)
            outlined = [q for q in quads if q['row'] == location_rows()[3][1]]
            self.assertEqual(len(outlined), 1)
            self.assertEqual((outlined[0]['x'], outlined[0]['y'], outlined[0]['width'], outlined[0]['height']),
                             self.screen(f, reservation['rect']))
            # Hover New York: recorded this frame, drawn from the next one.
            ny = next(l for l in MANIFEST['locations'] if l['id'] == 5)
            from tio.locations import TOWNS
            x1, y1, x2, y2 = TOWNS[5]
            cx = VIEWPORT[0] + ((x1 + x2) // 2 + 512) * (VIEWPORT[2] - VIEWPORT[0]) // 1024
            cy = VIEWPORT[1] + ((y1 + y2) // 2 + 512) * (VIEWPORT[3] - VIEWPORT[1]) // 1024
            f.mouse(cx, cy)
            f.draw()
            self.assertEqual(f.state(roads.HOVER), 5)
            quads = f.draw()
            self.assertEqual(quads[0]['color'], roads.DIM_COLOR)
            lit = [q for q in quads if q['row'] == location_rows()[5][0]]
            self.assertEqual([(q['x'], q['y'], q['width'], q['height']) for q in lit], [self.screen(f, ny['rect'])])
            # Only the hovered location is lit; the current town waits.
            self.assertFalse([q for q in quads if q['row'] == location_rows()[3][1]])
            put(f.u, DATA + 0x6c, 1)  # A GUI capture hides the hover like the native tooltip.
            f.draw()
            quads = f.draw()
            self.assertEqual(quads[0]['color'], roads.BASE_COLOR)
            self.assertTrue([q for q in quads if q['row'] == location_rows()[3][1]])
            self.assertEqual(f.renders, 5)

    def test_final_location_is_outlined_only_while_driving(self):
        f = self.fixture()
        put(f.u, f.base + v2.STATE + roads.FINAL, 8)
        f.squad((0, 0), (0, 0), (10, 0), True)
        self.assertTrue([q for q in f.draw() if q['row'] == location_rows()[8][1]])
        f.squad((10, 0), (10, 0), (10, 0), False)
        self.assertFalse([q for q in f.draw() if q['row'] == location_rows()[8][1]])

    def test_disabled_texas_and_the_mouse_outside_the_map_never_highlight(self):
        f = self.fixture()
        f.mouse(VIEWPORT[0] - 5, VIEWPORT[1] + 5)
        f.draw()
        self.assertEqual(f.state(roads.HOVER), 0)
        x = VIEWPORT[0] + (-250 + 512) * (VIEWPORT[2] - VIEWPORT[0]) // 1024
        y = VIEWPORT[1] + (-90 + 512) * (VIEWPORT[3] - VIEWPORT[1]) // 1024
        f.mouse(x, y)
        f.draw()
        self.assertEqual(f.state(roads.HOVER), 0)

    def marker(self, f):
        return next(q for q in f.draw() if q['row'] >= row(roads.marker_row(MANIFEST)))

    def test_marker_turns_with_the_motion_on_screen_and_keeps_heading_when_parked(self):
        f = self.fixture()
        width, height = VIEWPORT[2] - VIEWPORT[0], VIEWPORT[3] - VIEWPORT[1]
        first = roads.marker_row(MANIFEST)
        for stepped, expected in (((5, 0), 0), ((0, 5), 8), ((-5, 0), 16), ((0, -5), 24)):
            f.squad(stepped, (0.0, 0.0), (stepped[0] * 9, stepped[1] * 9), True)
            self.assertEqual(self.marker(f)['row'], row(first + expected))
        # A diagonal in world units turns by the stretched screen angle.
        f.squad((4, 4), (0.0, 0.0), (40, 40), True)
        angle = math.atan2(4 * height, 4 * width)
        self.assertEqual(self.marker(f)['row'], row(first + round(angle * 32 / (2 * math.pi)) % 32))
        # Caught up with the stepped point: the destination gives the heading.
        f.squad((3, 0), (3.0, 0.0), (3, 30), True)
        self.assertEqual(self.marker(f)['row'], row(first + 8))
        f.squad((3, 30), (3.0, 30.0), (3, 30), False)
        quad = self.marker(f)
        self.assertEqual(quad['row'], row(first + 8))
        side = MANIFEST['marker']['pixels'][0] * width // 1819
        self.assertEqual((quad['width'], quad['height']), (side, side))
        x = VIEWPORT[0] + (3 + 512) * width // 1024
        y = VIEWPORT[1] + (30 + 512) * height // 1024
        self.assertEqual((quad['x'], quad['y']), (x - side // 2, y - side // 2))

    def test_original_1d_reader_keeps_the_final_location(self):
        from tio.locations import movement_packet
        f = self.fixture()
        for character, target, expected in ((42, 8, 8), (77, 5, 8), (42, 0, 0)):
            packet = movement_packet(character, 10, 20, destination=(30, 40), target=target)
            f.u.mem_write(DATA + 0x9000, packet[1:])
            f.run(0x88b130, eax=DATA + 0x9000)
            self.assertEqual(f.state(roads.FINAL), expected)
        self.assertEqual(struct.unpack('<ii', f.u.mem_read(f.character + 0x14, 8)), (30, 40))

    def test_route_words_from_the_original_1d_reader_draw_dashes_while_driving(self):
        from tio.locations import Journey
        from tio.roads import ROADS
        from tio.locations import center
        from tio.protocol.map_route import dashes
        f = self.fixture()
        path = ROADS.plan(center(3), center(5))
        burst = Journey(path, 0, 30).announce(42, 0)
        for packet in burst:
            f.u.mem_write(DATA + 0x9000, packet[1:])
            f.run(0x88b130, eax=DATA + 0x9000)
        self.assertEqual(f.state(roads.ROUTE_COUNT), len(burst) - 1)
        self.assertEqual(f.state(roads.FINAL), 5)
        f.lines.clear(); f.draw()
        width, height = VIEWPORT[2] - VIEWPORT[0], VIEWPORT[3] - VIEWPORT[1]
        cut = dashes(path)
        self.assertEqual(len(f.lines), 3 * len(cut))
        x0, y0, x1, y1 = cut[0]
        sx = lambda x: VIEWPORT[0] + x * width // 1819
        sy = lambda y: VIEWPORT[1] + y * height // 865
        shadow, bright = f.lines[0], f.lines[1]
        self.assertEqual(bright, (sx(x0), sy(y0), sx(x1), sy(y1), roads.ROUTE_COLOR))
        self.assertEqual(shadow, (sx(x0) + 1, sy(y0) + 1, sx(x1) + 1, sy(y1) + 1, roads.ROUTE_SHADOW))
        # A new journey header replaces the route; a stop hides it.
        f.squad((0, 0), (0.0, 0.0), (0, 0), False)
        f.lines.clear(); f.draw()
        self.assertEqual(f.lines, [])

    def test_town_tooltip_follows_the_cursor_inside_the_map(self):
        f = self.fixture()
        f.draw()  # Viewport rectangle of this frame.
        put(f.u, f.va(0xb749e4), f.base + v2.TABLE)  # Inside the borrowed-table scope.
        put(f.u, DATA + 0x88, 777)
        left, top, right, bottom = VIEWPORT
        for mouse, expected in (((600, 300), (600 + 18 + 8, 300 + 22 + 8)),
                                ((right - 50, 300), (right - 50 - 318 + 8, 300 + 22 + 8)),
                                # Lower half: above the cursor, clear of the chat panel.
                                ((600, bottom - 20), (600 + 18 + 8, bottom - 20 - 22 - 160 + 8)),
                                ((600, (top + bottom) // 2 + 40), (626, (top + bottom) // 2 + 40 - 182 + 8)),
                                ((left + 5, top + 2), (left + 5 + 18 + 8, top + 2 + 22 + 8))):
            f.tips.clear(); f.mouse(*mouse)
            sp = STACK + 0x8000
            put(f.u, sp, STOP); put(f.u, sp + 4, 0x5a)
            f.u.reg_write(UC_X86_REG_ESP, sp)
            for register, value in zip(CALLEE, CANARIES):
                f.u.reg_write(register, value)
            f.u.reg_write(UC_X86_REG_EAX, 200); f.u.reg_write(UC_X86_REG_EDX, 150); f.u.reg_write(UC_X86_REG_ECX, 4)
            f.u.emu_start(f.va(roads.TIP_TOWN), STOP, count=10000)
            self.assertEqual(f.u.reg_read(UC_X86_REG_ESP), sp + 8)
            self.assertEqual(tuple(f.u.reg_read(r) for r in CALLEE), CANARIES)
            tip, = f.tips
            self.assertEqual((tip['x'], tip['y'], tip['index'], tip['argument']), (*expected, 4, 0x5a))
            # The native "keep off the squad" shift is parked away during the call only.
            self.assertEqual(tip['camera'], 0x40000000)
            self.assertEqual(get(f.u, DATA + 0x88), 777)

    def test_native_labels_of_baked_locations_are_skipped(self):
        f = self.fixture()
        table = f.base + v2.TABLE
        put(f.u, f.va(0xb749e4), table)
        # Borrowed table with a baked town (5) and a contract marker (23).
        for index, town in enumerate((5, 23)):
            record = DATA + 0x6000 + index * 0x400
            f.u.mem_write(record + 8, bytes((town,)))
            put(f.u, table + index * 4, record)
        put(f.u, table - 4, 2)
        for index, forwarded in ((0, False), (1, True)):
            put(f.u, DATA + 0x8100, index)
            f.texts.clear()
            sp = STACK + 0x8000
            put(f.u, sp, STOP); put(f.u, sp + 4, 0x11); put(f.u, sp + 8, 0x22)
            f.u.reg_write(UC_X86_REG_ESP, sp); f.u.reg_write(UC_X86_REG_ESI, DATA + 0x8100)
            f.u.reg_write(UC_X86_REG_EAX, 0xabc)
            f.u.emu_start(f.va(v2.DRAW + 0x13200), STOP, count=10000)
            self.assertEqual(f.u.reg_read(UC_X86_REG_ESP), sp + 12)  # both consume the two arguments
            self.assertEqual(f.texts, [0xabc] if forwarded else [])


if __name__ == '__main__':
    unittest.main()
