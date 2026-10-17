"""Execute actual x86 mip/IAT/SEH cleanup and sampler thunks in Unicorn.

Win32, D3DX and native engine calls are ABI fixtures. This proves argument and
state scope, not actual GPU mip generation or graphical quality, which require
the separately owned real client.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_global_map as a
from deploy import client_global_map_filter as f
from tools.verify_global_map_native import Fixture, DATA, get, put
from unicorn.x86_const import *

TI = 0x400000
VP, THREAD, D3DX, EXCEPTION_DONE = (DATA + off for off in (0xe000, 0xe010, 0xe020, 0xe030))


class FilterFixture(Fixture):
    def __init__(self, candidate, base):
        super().__init__(candidate, base)
        self.u.mem_map(TI, 0x400000)
        self.u.mem_write(TI + f.TI_D3DX_STUB_RVA,
                         b'\xff\x25' + struct.pack('<I', TI + f.TI_D3DX_IAT_RVA))
        put(self.u, TI + f.TI_D3DX_IAT_RVA, D3DX)
        put(self.u, self.va(0xac5d5c), DATA + 0xf000)
        put(self.u, DATA + 0xf000, TI + f.TI_IMAGE_LOAD_RVA)
        put(self.u, self.base + f.VP_RVA, VP)
        put(self.u, self.base + f.THREAD_RVA, THREAD)
        put(self.u, 0, 0xffffffff)
        self.renderer, self.sampler = DATA + 0xf100, DATA + 0xf500
        put(self.u, TI + f.TI_RENDERER_RVA, DATA + 0xf040)
        put(self.u, DATA + 0xf040, self.renderer)
        put(self.u, self.renderer + 0x248, DATA + 0xf080)
        put(self.u, DATA + 0xf080 + 12, self.sampler)
        self.original_filters = (1, 1, 0)
        for off, value in zip((0x68, 0x88, 0xa8), self.original_filters):
            put(self.u, self.sampler + off, value)
        self.thread = 101
        self.protection = 2
        self.vp_calls, self.mips, self.sampler_calls, self.quad_filters = [], [], [], []
        self.fail_vp = self.raise_load = self.foreign_thread = False
        self.exception_seen = False
        self.return_address = TI + f.TI_D3DX_RETURN_RVA
        self.d3dx_args = [0x123, 0x456, 8192, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0xabc, 0, 0xdef]

    def filters(self): return tuple(get(self.u, self.sampler + off) for off in (0x68, 0x88, 0xa8))

    def hook(self, u, address, size, extra):
        sp = u.reg_read(UC_X86_REG_ESP)
        if address == VP:
            slot, size_, protection, output = [get(u, sp + 4 * i) for i in range(1, 5)]
            assert slot == TI + f.TI_D3DX_IAT_RVA and size_ == 4
            self.vp_calls.append((protection, self.protection))
            if self.fail_vp and protection == 4:
                u.reg_write(UC_X86_REG_EAX, 0)
            else:
                put(u, output, self.protection); self.protection = protection
                u.reg_write(UC_X86_REG_EAX, 1)
            self.ret(16)
        elif address == THREAD:
            active = get(u, self.base + a.REGION + f.STATE_OFFSET + f.ACTIVE)
            u.reg_write(UC_X86_REG_EAX, self.thread + int(self.foreign_thread and active == 1)); self.ret()
        elif address == self.va(0x4f2c50):
            eax, ecx = u.reg_read(UC_X86_REG_EAX), u.reg_read(UC_X86_REG_ECX)
            path = self.text(eax); self.loads.append(path)
            handle = 0 if path == self.fail_asset else 0x1000 + len(self.loads)
            u.mem_write(ecx, struct.pack('<I4H', handle, 1254, 1254, 1254, 1254))
            if not handle:
                self.ret(); return
            if self.raise_load:
                self.loader_sp = sp
                registration = get(u, 0)
                assert get(u, registration) == 0xffffffff
                handler = get(u, registration + 4)
                assert handler == self.va(a.DRAW + f.EXCEPTION_OFFSET)
                u.mem_write(sp - 20, struct.pack('<5I', EXCEPTION_DONE, 0x123, registration, 0x456, 0x789))
                u.reg_write(UC_X86_REG_ESP, sp - 20); u.reg_write(UC_X86_REG_EIP, handler)
                self.exception_seen = True
            else:
                u.mem_write(sp - 64, struct.pack('<16I', self.return_address, *self.d3dx_args))
                u.reg_write(UC_X86_REG_ESP, sp - 64)
                u.reg_write(UC_X86_REG_EIP, get(u, TI + f.TI_D3DX_IAT_RVA))
        elif address == D3DX:
            args = [get(u, sp + 4 * i) for i in range(1, 16)]
            self.mips.append(args)
            u.reg_write(UC_X86_REG_EAX, 0); self.ret(60)
        elif address == self.return_address:
            self.ret()
        elif address == EXCEPTION_DONE:
            assert u.reg_read(UC_X86_REG_EAX) == 1  # ContinueSearch.
            assert get(u, TI + f.TI_D3DX_IAT_RVA) == D3DX and self.protection == 2
            assert get(u, self.base + a.REGION + f.STATE_OFFSET + f.ACTIVE) == 0
            u.reg_write(UC_X86_REG_ESP, self.loader_sp); self.ret()
        elif address in (TI + f.TI_MAG_RVA, TI + f.TI_MIN_RVA, TI + f.TI_MIP_RVA):
            sampler = u.reg_read(UC_X86_REG_EAX)
            stage, value = u.reg_read(UC_X86_REG_EDX), u.reg_read(UC_X86_REG_ECX)
            assert sampler == self.sampler and stage == 0
            off = {TI + f.TI_MAG_RVA: 0x68, TI + f.TI_MIN_RVA: 0x88, TI + f.TI_MIP_RVA: 0xa8}[address]
            put(u, self.sampler + off, value); self.sampler_calls.append((off, value)); self.ret()
        else:
            if address == self.va(0x4f2910): self.quad_filters.append(self.filters())
            if address == self.va(0x9ebda4): assert self.filters() == self.original_filters
            super().hook(u, address, size, extra)


def verify(candidate):
    cases = []
    for base in (0x10000000, 0x17000000):
        fixture = FilterFixture(candidate, base); fixture.run(a.INITIALIZE)
        assert len(fixture.mips) == 23
        assert fixture.mips[0] == fixture.d3dx_args
        expected = list(fixture.d3dx_args); expected[5] = 0; expected[10] = 5
        assert all(args == expected for args in fixture.mips[1:])
        state = base + a.REGION + f.STATE_OFFSET
        assert get(fixture.u, state + f.MIP_CALLS) == 22
        assert get(fixture.u, state + f.SCOPES) == get(fixture.u, state + f.RESTORES) == 22
        assert get(fixture.u, state + f.ACTIVE) == 0
        assert fixture.protection == 2 and get(fixture.u, TI + f.TI_D3DX_IAT_RVA) == D3DX
        assert get(fixture.u, 0) == 0xffffffff
        fixture.run(a.DRAW)
        assert fixture.quad_filters[0] == fixture.original_filters
        assert fixture.quad_filters[1:] == [(2, 2, 2)] * 22
        assert fixture.filters() == fixture.original_filters
        assert get(fixture.u, state + f.DRAW_ACTIVE) == 0
        for i in range(23):
            assert list(struct.unpack('<4H', bytes(fixture.u.mem_read(base + a.ROWS + i * a.ROW_SIZE + 4, 8)))) == [1254] * 4
        cases.append({'silver_base': hex(base), 'object_mip_chains': 22,
                      'terrain_arguments_unchanged': True, 'all_other_d3dx_arguments_unchanged': True,
                      'source_descriptor_dimensions_unchanged': True,
                      'iat_pointer_and_protection_restored': True,
                      'seh_registration_restored': True,
                      'png_draw_filters': [2, 2, 2], 'ui_filters_restored': list(fixture.filters())})
        # Loader failure before D3DX still restores the installed IAT/protection.
        failed = FilterFixture(candidate, base); failed.fail_asset = a.resources()[1]['path']
        failed.run(a.INITIALIZE)
        assert get(failed.u, base + a.STATE) == 0xffffffff
        assert get(failed.u, TI + f.TI_D3DX_IAT_RVA) == D3DX and failed.protection == 2
        assert get(failed.u, state + f.ACTIVE) == 0 and get(failed.u, 0) == 0xffffffff
        # Protection refusal safely delegates unchanged to the native loader.
        denied = FilterFixture(candidate, base); denied.fail_vp = True; denied.run(a.INITIALIZE)
        assert denied.mips == [denied.d3dx_args] * 23
        assert denied.protection == 2 and get(denied.u, TI + f.TI_D3DX_IAT_RVA) == D3DX
        # Foreign native caller gets untouched arguments even under an active
        # temporary import scope. This isolates unrelated graphics loads.
        foreign = FilterFixture(candidate, base); foreign.return_address -= 1
        foreign.run(a.INITIALIZE); assert foreign.mips == [foreign.d3dx_args] * 23
        assert get(foreign.u, state + f.MIP_CALLS) == 0
        threaded = FilterFixture(candidate, base); threaded.foreign_thread = True
        threaded.run(a.INITIALIZE); assert threaded.mips == [threaded.d3dx_args] * 23
        assert get(threaded.u, state + f.MIP_CALLS) == 0
        # Execute real registered SEH handler with a propagated exception ABI.
        exceptional = FilterFixture(candidate, base); exceptional.raise_load = True
        exceptional.run(a.DRAW + f.LOAD_OFFSET,
                        eax=base + a.NAMES + 0x100 + 12, edx=3, ecx=base + a.ROWS + a.ROW_SIZE)
        assert exceptional.exception_seen and get(exceptional.u, state + f.ACTIVE) == 0
        assert exceptional.protection == 2 and get(exceptional.u, TI + f.TI_D3DX_IAT_RVA) == D3DX
        assert get(exceptional.u, 0) == 0xffffffff
        cases[-1].update({'failed_load_cleanup': True, 'protection_refusal_uses_stock': True,
                          'foreign_d3dx_call_unchanged': True, 'foreign_thread_arguments_unchanged': True,
                          'seh_continue_search_cleanup': True})
    return {'passed': True, 'candidate_sha256': a.sha(candidate), 'method': __doc__,
            'cases': cases, 'actual_gpu_validation': 'Requires actual native GUI client'}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    report = verify(args.candidate.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']),
                      'candidate_sha256': report['candidate_sha256']}))


if __name__ == '__main__': main()
