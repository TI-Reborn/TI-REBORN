"""Run generated scale preference/radio x86 with explicit native function stubs.

Checks PIC, ABI, defaults, existing preference preservation, radio isolation and
Apply delegation. This is not a renderer, real client, or persistence restart QA.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from functools import lru_cache

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_ui_scale_controls as controls

DATA, STACK, EXIT = 0x30000000, 0x31000000, 0x32000000
CALLEE = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


def put(u, at, value):
    u.mem_write(at, struct.pack('<I', value & 0xffffffff))


def get(u, at):
    return struct.unpack('<I', u.mem_read(at, 4))[0]


@lru_cache(maxsize=2)
def original_image(base):
    pe=pefile.PE(str(ROOT/'reports/screen-settings/client/silver.dll'))
    pe.relocate_image(base)
    return pe.get_memory_mapped_image()


class Fixture:
    def __init__(self, base, physical, preference=None, effective=0, status=1, applied_effective=None):
        self.base, self.physical = base, physical
        self.preference, self.writes, self.controls, self.captions = preference, [], [], {}
        self.native_applies, self.setters, self.native_captions = 0, [], 0
        self.applied_effective=applied_effective
        self.drawing, self.text_draws, self.width_calls = False, [], []
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u.mem_map(base, 0x830000)
        if base != 0x400000:
            self.u.mem_map(0x400000, 0x400000)
        self.u.mem_map(DATA, 0x20000); self.u.mem_map(STACK, 0x10000); self.u.mem_map(EXIT, 0x1000)
        self.u.mem_map(0, 0x1000)  # Native Delphi draw function installs an SEH frame.
        original = original_image(base)
        self.u.mem_write(base, original)
        self.u.mem_write(base+controls.RVA, controls.extension())
        put(self.u, base+controls.CORE_STATE, effective)
        put(self.u, base+controls.CORE_STATE+4, physical[0]); put(self.u, base+controls.CORE_STATE+8, physical[1])
        put(self.u, base+0x823c30, status)
        put(self.u, 0x786788, DATA+0x100)
        put(self.u, base+0xac5b40-controls.BASE, DATA+0x104)
        put(self.u, DATA+0x104, 0x11111111)
        put(self.u, base+0xa309f4-controls.BASE, 0x12345678)
        put(self.u, base+0xa30e38-controls.BASE, 0x76543210)
        for register, value in zip(CALLEE, (0x11111000, DATA+0x1000, 0x33333000, 0x44444000)):
            self.u.reg_write(register, value)
        self.before = tuple(self.u.reg_read(r) for r in CALLEE)
        self.u.reg_write(UC_X86_REG_EFLAGS, 0x202)
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def string(self, at):
        out = bytearray()
        for i in range(256):
            word = self.u.mem_read(at+i*2, 2)
            if word == b'\0\0':
                return out.decode('utf-16le')
            out.extend(word)
        raise ValueError('Unbounded fixture string')

    def ret(self, cleanup=0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, get(self.u, sp))
        self.u.reg_write(UC_X86_REG_ESP, sp+4+cleanup)

    def hook(self, u, actual, size, _):
        va = actual-self.base+controls.BASE
        eax, edx, ecx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        if actual == EXIT:
            u.emu_stop(); return
        if self.drawing and va in (0xa54980,0x40b0fc):
            # Event dispatch and managed temporary-string release are external.
            self.ret(); return
        if self.drawing and va == 0x40c048:
            # Explicit managed UTF16->draw-string conversion fixture.
            put(u,eax,edx); self.ret(); return
        if self.drawing and va == 0x4f2ba8:
            width = 66 if self.string(edx) == 'Интерфейс:' else 282
            self.width_calls.append(dict(font=eax,text=self.string(edx),width=width))
            u.reg_write(UC_X86_REG_EAX,width);self.ret();return
        if self.drawing and va == 0x4f29a8:
            sp=u.reg_read(UC_X86_REG_ESP)
            self.text_draws.append(dict(font=eax,text=self.string(edx),x=ecx,
                                       color=get(u,sp+4),y=get(u,sp+8)))
            self.ret(8);return
        if va == 0x688328:
            assert self.string(eax) == 'ui_scale'
            assert get(u, eax-4) == 8 and get(u, eax-8) == 0xffffffff
            u.reg_write(UC_X86_REG_EAX, self.preference or 0); self.ret()
        elif va == 0x6882f0:
            assert self.string(eax) == 'ui_scale'
            u.reg_write(UC_X86_REG_EAX, self.preference is not None); self.ret()
        elif va == 0x688420:
            sp = u.reg_read(UC_X86_REG_ESP)
            assert self.string(get(u, sp+4)) == 'ui_scale' and get(u, sp+12) == 1
            value = int(self.string(get(u, sp+8)))
            self.preference = value; self.writes.append(value); self.ret(12)
        elif va == 0x884688:
            self.native_captions += 1; self.ret()
        elif va in (0xa44c9c, 0xa47d78):
            obj = DATA+0x2000+len(self.controls)*0x400
            self.controls.append(obj)
            put(u, obj, 0x12345678 if va == 0xa44c9c else 0x76543210)
            put(u,obj+0x4c,ecx if va == 0xa47d78 else get(u,u.reg_read(UC_X86_REG_ESP)+4))
            if va == 0xa47d78:
                # Real constructor a47df6: right_align byte284=0; font28c=1.
                put(u,obj+0x28c,1); put(u,obj+0x38,100);put(u,obj+0x3c,16)
                u.mem_write(obj+0x49,b'\1');put(u,obj+0x288,0xffffffff)
            u.reg_write(UC_X86_REG_EAX, obj); self.ret(4 if va == 0xa44c9c else 0)
        elif va == 0xa42b04:
            assert get(u, edx-4) == len(self.string(edx).encode('utf-16le'))
            self.captions[eax] = self.string(edx);put(u,eax+0x5c,edx); self.ret()
        elif va == 0xa44eac:
            u.mem_write(eax+0x280, bytes([edx&1])); self.ret()
        elif va == 0xa3fca8:
            assert self.string(edx) == 'window_pdamenu_options_video'
            u.reg_write(UC_X86_REG_EAX, 0 if self.controls else 0xffffffff); self.ret()
        elif va == 0xa3f2a0:
            u.reg_write(UC_X86_REG_EAX, DATA+0x1000); self.ret()
        elif va == 0xa424d4:
            u.reg_write(UC_X86_REG_EAX, len(self.controls)); self.ret()
        elif va == 0xa424c4:
            u.reg_write(UC_X86_REG_EAX, self.controls[edx]); self.ret()
        elif va == 0x4095ac:
            u.reg_write(UC_X86_REG_EAX, get(u, eax) == 0x12345678); self.ret()
        elif va == controls.TRAMPOLINE:
            # The original Apply, including D3D, is deliberately external here.
            self.native_applies += 1; self.ret()
        elif va == controls.CORE_SET:
            self.setters.append(eax)
            value=eax if self.applied_effective is None else self.applied_effective
            put(u,self.base+controls.CORE_STATE,value)
            u.reg_write(UC_X86_REG_EAX,value);self.ret()

    def run(self, preferred, eax=0, early=False):
        sp = STACK+0x8000
        self.u.reg_write(UC_X86_REG_EAX, eax)
        if early:
            put(self.u, sp, self.before[3]); put(self.u, sp+4, EXIT); put(self.u, sp+8, 0x11111111)
            self.u.reg_write(UC_X86_REG_EBP, sp)
        else:
            put(self.u, sp, EXIT)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        self.u.emu_start(self.base+preferred-controls.BASE, EXIT, count=150000)
        assert self.u.reg_read(UC_X86_REG_EIP) == EXIT
        assert self.u.reg_read(UC_X86_REG_ESP) == sp+(12 if early else 4)
        assert tuple(self.u.reg_read(r) for r in CALLEE) == self.before
        return self.u.reg_read(UC_X86_REG_EAX)


def verify():
    cases = []
    for base in (0x400000, 0x10400000):
        for physical, expected in (((800,600),100), ((1920,1080),100), ((2560,1390),150),
                                   ((2560,1440),150), ((3440,1440),150), ((3840,2160),200)):
            for old in (None, 0, -100, 999):
                f = Fixture(base, physical, old)
                assert f.run(controls.LOAD) == expected and f.writes == [expected]
                cases.append(dict(kind='default', base=hex(base), physical=physical, old=old, result='PASS'))
        for percent in controls.PERCENTS:
            f = Fixture(base, (2560,1440), percent)
            assert f.run(controls.LOAD) == percent and not f.writes
            f.run(controls.EARLY, early=True)
            assert f.preference == percent and not f.writes
            cases.append(dict(kind='saved_value_not_overwritten', base=hex(base), percent=percent, result='PASS'))
            f.run(controls.CREATE)
            radios = [o for o in f.controls if get(f.u, o) == 0x12345678]
            assert len(radios) == 4 and len(f.controls) == 6
            assert [get(f.u, o+0x278) for o in radios] == list(controls.PERCENTS)
            assert [get(f.u, o+0x284) for o in radios] == [4]*4
            assert [(get(f.u, o+0x30), get(f.u, o+0x34)) for o in radios] == [(128,320),(224,320),(128,336),(224,336)]
            assert [f.captions[o] for o in radios] == ['100%','125%','150%','200%']
            labels = [o for o in f.controls if get(f.u, o) == 0x76543210]
            assert len(labels) == 2 and all(f.u.mem_read(o+0x284,1) == b'\0' for o in labels)
            assert all(get(f.u,o+0x28c) == 1 for o in labels)
            assert sum(f.u.mem_read(o+0x280,1)[0] for o in radios) == 1
            assert f.native_captions == 1
            f.run(controls.APPLY)
            assert f.native_applies == 1 and f.setters == [percent] and f.preference == percent
            cases.append(dict(kind='native_controls_apply', base=hex(base), percent=percent, result='PASS'))
        f = Fixture(base, (2560,1440))
        f.run(controls.EARLY, early=True)
        assert f.preference == 0 and f.writes == [0]
        cases.append(dict(kind='early_register_auto', base=hex(base), result='PASS'))
        for missing in ('host_manager', 'callback_pointer', 'callback'):
            f = Fixture(base, (2560,1440))
            put(f.u, {'host_manager':0x786788, 'callback_pointer':base+0xac5b40-controls.BASE, 'callback':DATA+0x104}[missing], 0)
            f.run(controls.EARLY, early=True)
            assert not f.writes
            cases.append(dict(kind='early_guard', base=hex(base), absent=missing, result='PASS'))
        for invalid in (0, -1, 101, 300):
            f = Fixture(base, (2560,1440), 150)
            f.run(controls.SAVE, invalid)
            assert not f.writes and f.preference == 150
            cases.append(dict(kind='invalid_not_persisted', base=hex(base), value=invalid, result='PASS'))
        f = Fixture(base, (2560,1440), 150, status=4)
        f.run(controls.CREATE); f.run(controls.APPLY)
        assert f.native_applies == 1 and not f.setters and not f.writes
        cases.append(dict(kind='total_device_failure_retains_native_path', base=hex(base), result='PASS'))
        f = Fixture(base, (2560,1440), 150)
        f.run(controls.APPLY)
        assert f.native_applies == 1 and not f.setters and not f.writes
        cases.append(dict(kind='absent_panel_delegates', base=hex(base), result='PASS'))
        for requested,effective in ((200,150),(150,100),(125,100)):
            f=Fixture(base,(2560,1440),requested,applied_effective=effective)
            f.run(controls.CREATE)
            radio=[o for o in f.controls if get(f.u,o)==0x12345678]
            assert [get(f.u,o+0x278) for o in radio if f.u.mem_read(o+0x280,1)==b'\1']==[requested]
            native=DATA+0x10000;f.u.mem_write(native,b'\xa6'*0x400)
            put(f.u,native,0x12345678);put(f.u,native+0x284,2)
            f.controls.append(native);before=bytes(f.u.mem_read(native,0x400))
            f.run(controls.APPLY)
            assert f.native_applies==1 and f.setters==[requested]
            assert f.preference==requested and f.writes==[requested]
            assert [get(f.u,o+0x278) for o in radio if f.u.mem_read(o+0x280,1)==b'\1']==[effective]
            assert bytes(f.u.mem_read(native,0x400))==before
            cases.append(dict(kind='cached_radio_matches_capped_effective_scale',base=hex(base),
                              requested=requested,effective=effective,archived_request= f.preference,
                              original_native_group_preserved=True,native_apply_count=1,result='PASS'))
        f = Fixture(base,(2560,1440),150)
        f.run(controls.CREATE)
        parent=DATA+0x1000
        put(f.u,parent+0x30,700);put(f.u,parent+0x34,100)
        put(f.u,parent+0x38,384);put(f.u,parent+0x3c,420)
        labels=[o for o in f.controls if get(f.u,o)==0x76543210]
        f.drawing=True
        for label in labels:
            f.text_draws=[];f.width_calls=[]
            f.run(0xa47ea0,label)
            assert len(f.text_draws)==1 and not f.width_calls
            draw=f.text_draws[0]
            width=66 if draw['text']=='Интерфейс:' else 282
            assert draw['font']==1 and draw['x']==700+32
            assert draw['y']==100+get(f.u,label+0x34)
            assert 700 <= draw['x'] and draw['x']+width <= 700+384
            cases.append(dict(kind='native_label_draw_left_origin',base=hex(base),result='PASS',
                              draw=draw,font_width_fixture=width,native_draw='a47ea0',
                              parent_bounds=[700,100,384,420]))
            # Reproduce the exact previous failure through the actual draw path:
            # right_align subtracts native measured width independently of font.
            f.u.mem_write(label+0x284,b'\1')
            f.text_draws=[];f.width_calls=[]
            f.run(0xa47ea0,label)
            assert len(f.text_draws)==len(f.width_calls)==1
            assert f.text_draws[0]['x']==700+32-width
            cases.append(dict(kind='native_label_old_right_alignment_reproduced',base=hex(base),
                              result='PASS',draw=f.text_draws[0],width_call=f.width_calls[0]))
    return dict(result='PASS', cases=len(cases), details=cases,
                generated_payload_sha256=hashlib.sha256(controls.extension()).hexdigest(),
                scale_labels_use_native_left_alignment=True,
                native_label_alignment_field='byte +284 (right_align)',
                native_label_font_field='byte +28c (font index); default1',
                native_label_draw_geometry_executed=True,
                label_text_width_and_draw_callbacks_stubbed=True,
                cached_radio_reflects_effective_scale_and_archives_request=True,
                external_native_functions_stubbed=True, real_restart_persistence_verified=False,
                graphical_validation=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--report', type=Path)
    args = parser.parse_args(); report = verify()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'details'}, indent=2))


if __name__ == '__main__':
    main()
