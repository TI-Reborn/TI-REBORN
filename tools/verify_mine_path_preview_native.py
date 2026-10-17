"""Read-only execution of actual TI picking, AP truncation and foot geometry.

Native functions 72ca68, 70d42c, 70d2a4, 70cc84 and 740978 execute. The
selected actor, legal pathfinder routes and UI/texture allocation are explicit
fixtures. GPU upload and client/hosted gameplay are not exercised. All fixtures
are private Unicorn memory; neither an installed client nor saves are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_client_ui_scale_native import Fixture, DATA, STACK, API, END, get, put, signed

SILVER = ROOT / 'reports/mine-path-scale-20261010/baseline/silver.dll'
TI = ROOT / 'reports/mine-path-scale-20261010/baseline/ti.exe'
SILVER_SHA = 'a35961b73363d759d6229e793f6265d3efb337dd826509e8efb6104e8b7aa42b'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
BASE = 0x10400000


class PathFixture(Fixture):
    def __init__(self, silver, ti, physical, percent, route, ap, camera=(1600, 200)):
        super().__init__(silver, BASE)
        self.initialize(*physical, percent)
        self.u.mem_write(0x400000, pefile.PE(data=ti).get_memory_mapped_image())
        self.u.mem_map(0, 0x1000)
        self.route = route
        self.ap = ap
        self.actor = DATA + 0x10000
        self.matrix = DATA + 0x11000
        self.list = DATA + 0x12000
        self.texture = DATA + 0x13000
        self.storage = DATA + 0x14000
        self.mouse = (camera[0] + 32 * (route[-1][1] - route[-1][0]),
                      camera[1] + 16 * (route[-1][0] + route[-1][1]) + 16)
        self.foot = []
        self.quads = []
        self.lines = []
        self.picks = []
        self.nextslot = DATA + 0x15000
        for address, value in ((0x76e518, self.mouse[0]), (0x76e440, self.mouse[1]),
                               (0x76e444, camera[0]), (0x76e370, camera[1]),
                               (0x76e314, 100000), (0x76dcf8, 60), (0x76dc08, 60),
                               (0x76e068, 0x5a), (0x76e5cc, 0), (0x76dccc, 0)):
            self.pointer(address, value)
        for address, value in ((0x76e5f4, self.matrix), (0x76e17c, self.actor),
                               (0x76e5dc, self.texture)):
            self.pointer(address, value)
        put(self.u, 0x76e430, self.storage)
        put(self.u, self.storage, self.actor)
        self.u.mem_write(self.actor + 8, struct.pack('<H', 115 ^ 0x5a))
        self.u.mem_write(self.actor + 0x10, bytes([ap ^ 0x5a]))
        put(self.u, self.actor + 0x1bc, route[0][0])
        put(self.u, self.actor + 0x1c0, route[0][1])
        self.u.mem_write(self.actor + 0x34, struct.pack('<ff',
                                                     route[0][0] * 32 + 16,
                                                     route[0][1] * 32 + 16))
        put(self.u, self.list + 8, len(route))
        put(self.u, self.texture + 0x24, 64)
        put(self.u, self.texture + 0x28, 64)
        self.pointer(0x76dc7c, API + 0x90)
        put(self.u, 0x78574c, 0xffffffff)
        # Copies use actual scale setter dimensions, while TI input stays physical.
        for i, rva in enumerate((0x6c5b70, 0x6c5a04)):
            put(self.u, get(self.u, BASE + rva),
                self.mouse[i] * self.state(0xc + i * 4) // physical[i])
        self.logical_mouse = self.copied_mouse()
        self.physical_before = bytes(self.u.mem_read(get(self.u, 0x76e518), 4)) + bytes(
            self.u.mem_read(get(self.u, 0x76e440), 4))
        self.state(0x14, 0)
        self.u.hook_add(UC_HOOK_CODE, self.path_hook)

    def pointer(self, address, value):
        put(self.u, address, self.nextslot)
        put(self.u, self.nextslot, value)
        self.nextslot += 4

    def copied_mouse(self):
        return tuple(signed(get(self.u, get(self.u, BASE + rva)))
                     for rva in (0x6c5b70, 0x6c5a04))

    def path_hook(self, u, address, size, _):
        eax, edx, ecx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        sp = u.reg_read(UC_X86_REG_ESP)
        if address == 0x72ca68:
            self.picks.append((eax, edx))
        elif address == 0x723f44:
            self.ret(result=0)
        elif address in (0x724d84, 0x6f5734, 0x70cbbc, 0x7059e8, 0x7073d0, 0x437360, API + 0x90):
            self.ret(result=0)
        elif address in (0x723fc8, 0x6e4448, 0x6f6fa8, 0x72ab44):
            self.ret(result=1)
        elif address == 0x6e4b6c:
            put(u, ecx, eax)
            put(u, ecx + 4, edx)
            self.ret()
        elif address == 0x6e4ea4:
            self.ret()
        elif address == 0x6e91f0:
            self.ret(result=self.list)
        elif address == 0x6e4c3c:
            assert (ecx, get(u, sp + 4)) == self.route[-1]
            self.ret(4)
        elif address == 0x6e8f44:
            assert eax == self.list and edx < len(self.route)
            put(u, ecx, self.route[edx][0])
            put(u, ecx + 4, self.route[edx][1])
            self.ret()
        elif address in (0x409214, 0x722630, 0x40afb4, 0x434b24):
            self.ret()
        elif address == 0x43a480:
            u.mem_write(eax, bytes(16))
            self.ret()
        elif address == 0x741890:
            self.lines.append((signed(eax), signed(edx), signed(ecx), signed(get(u, sp + 8))))
            self.ret(8)
        elif address == 0x740978:
            self.foot.append((signed(edx), signed(ecx)))
            # Execute native world diamond construction; stop only at the GPU API.
        elif address == 0x661058:
            values = [get(u, sp + 4 + i * 4) for i in range(21)]
            self.quads.append(values)
            self.ret(84)

    def native(self, address, eax=0):
        sp = STACK + 0xf000
        put(self.u, sp, END)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        self.u.reg_write(UC_X86_REG_EAX, eax)
        self.u.reg_write(UC_X86_REG_EBP, STACK + 0xb000)
        self.u.reg_write(UC_X86_REG_EFLAGS, 0x246)
        self.stopping = END
        self.u.emu_start(address, END, count=200000)
        assert self.u.reg_read(UC_X86_REG_EIP) == END
        assert self.u.reg_read(UC_X86_REG_ESP) == sp + 4

    def verify(self, name, obstacles=()):
        assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1
                   for a, b in zip(self.route, self.route[1:]))
        assert not set(self.route).intersection(obstacles)
        assert all(0 <= x < 60 and 0 <= y < 60 for x, y in self.route)
        for a, b in zip(self.route, self.route[1:]):
            if a[0] != b[0] and a[1] != b[1]:
                assert (a[0], b[1]) not in obstacles and (b[0], a[1]) not in obstacles
        self.native(0x70d42c)
        assert (signed(get(self.u, 0x78574c)), signed(get(self.u, 0x785750))) == self.route[-1]
        count = min(len(self.route) - 1, self.ap, 19)
        assert get(self.u, 0x76d9e0) == count
        assert get(self.u, 0x785754) == self.ap - count
        active = []
        for i in range(61):
            if self.u.mem_read(0x785288 + i * 20, 1) != b'\0':
                active.append((signed(get(self.u, 0x78528c + i * 20)),
                               signed(get(self.u, 0x785290 + i * 20))))
        expected = tuple(v * 32 + 16 for v in self.route[count])
        assert active[-1] == expected
        self.native(0x70cc84)
        camera = tuple(signed(get(self.u, get(self.u, va))) for va in (0x76e444, 0x76e370))
        projection = (camera[0] - expected[0] + expected[1],
                      camera[1] + (expected[0] + expected[1]) // 2)
        assert self.foot == [projection], (self.foot, projection)
        assert len(self.quads) == 1
        # 661058 takes dimensions/frame/flags/texture/UV/color, then four XY pairs.
        floats = [struct.unpack('<f', struct.pack('<I', v))[0] for v in self.quads[0]]
        quad = list(reversed(floats[-8:]))
        x, y = projection
        assert quad == [x - 32, y, x, y - 16, x + 32, y, x, y + 16]
        if name == 'near-free-floor':
            assert projection == self.mouse
        if name == 'far-free-floor-ap-limited':
            assert projection != self.mouse and self.ap - count == 0
        assert self.copied_mouse() == self.logical_mouse
        assert self.state(0x14) == 0
        assert self.physical_before == bytes(self.u.mem_read(get(self.u, 0x76e518), 4)) + bytes(
            self.u.mem_read(get(self.u, 0x76e440), 4))
        return dict(case=name, requested_scale=self.state(0x18), effective_scale=self.state(0),
                    physical_size=[self.state(4), self.state(8)],
                    logical_size=[self.state(0xc), self.state(0x10)],
                    physical_mouse=self.mouse, logical_mouse=self.logical_mouse,
                    picked_cell=self.route[-1], actor_cell=self.route[0],
                    available_ap=self.ap, path_steps=count, remaining_ap=self.ap - count,
                    preview_destination=self.route[count], footprint_anchor=self.foot[0],
                    native_quad_xy=quad, route=list(self.route), obstacles=list(obstacles),
                    native_preview_records_hex=bytes(self.u.mem_read(0x7850f8, 0x190)).hex(),
                    native_picking_executed=True, native_ap_truncation_executed=True,
                    native_projection_executed=True, native_world_quad_executed=True,
                    scope=0, logical_and_physical_mouse_preserved=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'reports/mine-path-indicator-20261010/native-proof.json')
    args = parser.parse_args()
    silver, ti = SILVER.read_bytes(), TI.read_bytes()
    assert hashlib.sha256(silver).hexdigest() == SILVER_SHA
    assert hashlib.sha256(ti).hexdigest() == TI_SHA
    near = [(20, 20 + i) for i in range(5)]
    far = [(20, 20 + i) for i in range(19)]
    detour = [(20, 20), (20, 21), (20, 22), (21, 23), (22, 23), (23, 23), (24, 22), (24, 21), (24, 20)]
    obstacles = [(22, 19), (22, 20), (22, 21)]
    scenarios = [('near-free-floor', near, 10, ()), ('far-free-floor-ap-limited', far, 10, ()),
                 ('obstacle-detour', detour, 10, obstacles)]
    cases = []
    for physical in ((2560, 1440), (3840, 2160)):
        for percent in (100, 125, 150, 200):
            for name, route, ap, blocked in scenarios:
                cases.append(PathFixture(silver, ti, physical, percent, route, ap).verify(name, blocked))
    for name in [s[0] for s in scenarios]:
        rows = [c for c in cases if c['case'] == name]
        assert all(r['footprint_anchor'] == rows[0]['footprint_anchor'] for r in rows)
        assert all(r['native_quad_xy'] == rows[0]['native_quad_xy'] for r in rows)
    proof = dict(result='PASS', cases=len(cases), silver_sha256=SILVER_SHA, ti_sha256=TI_SHA,
                 source_silver=SILVER.relative_to(ROOT).as_posix(), source_ti=TI.relative_to(ROOT).as_posix(),
                 mine_grid=[60, 60],
                 native_functions=['72ca68 physical world-cell picking', '70d42c path storage and AP cap',
                                   '724074 native encoded AP', '70d2a4 path interpolation',
                                   '70cc84 path endpoint and draw', '72c9e4 isometric projection',
                                   '740978 world diamond quad'],
                 explicit_fixtures=['selected actor lookup', 'legal pathfinder routes',
                                    'UI occlusion and readiness', 'texture descriptor', 'GPU submission'],
                 actual_gpu_upload=False, actual_client_gui=False, hosted_gameplay=False,
                 native_files_modified=False, database_modified=False, rows=cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: {len(cases)} actual native pick/AP/path/foot-quad cases; GPU/client/server are not exercised')


if __name__ == '__main__':
    main()
