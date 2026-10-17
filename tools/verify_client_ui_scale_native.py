"""Execute UI-scale native x86 with explicit Windows, renderer and UI stubs.

Checks physical/logical dimensions, hit-test coordinates, relocation, GPU-only
vertex scaling, clip rectangles and guarded installation. No client is launched
and no Direct3D rendering or hosted gameplay is claimed by this harness.
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
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
    UC_X86_REG_EIP, UC_X86_REG_EFLAGS,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_ui_scale as scale

DATA = 0x30000000
STACK = 0x31000000
API = 0x32000000
END = API + 0xf00
FRAME = STACK + 0xc000
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
        UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
VALUES = (0x11111111, 0x22222222, 0x33333333, 0x44444444,
          0x55555555, 0x66666666, FRAME)


def put(u, address, value):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get(u, address):
    return struct.unpack('<I', u.mem_read(address, 4))[0]


def signed(value):
    return value if value < 0x80000000 else value - 0x100000000


class SquadFixture:
    """Synthetic existing PDA tree; the native root bounds routine executes."""
    def __init__(self, fixture, width=1706, height=908):
        self.f = fixture; self.u = fixture.u; self.next = DATA+0x7000
        self.list_next = DATA+0x22000; self.children = {}; self.objects = {}
        self.root = self.control(0xa31a40, 0, 146, 72,
                                 round((width-190)/32)*32,
                                 round((max(height,768)-325)/32)*32)
        self.close = self.control(0xa2ed34, self.root, 0, 0, 16, 16)
        put(self.u,self.root+0x344,self.close)
        self.u.mem_write(self.root+0x340,struct.pack('<HH',32,32))
        fixture.squad_root=self.root
        self.header=self.control(0x8c98b0,self.root,50,0,get(self.u,self.root+0x38)-100,82)
        put(self.u,fixture.va(0xac4bdc),self.header)
        self.panels={}
        for global_va, x, y, w, h in (
            (0xad1094,255,91,width-450,34),(0xad1098,235,127,20,max(height,768)-456),
            (0xad109c,250,127,width-450,max(height,768)-456),
            (0xad10a0,0,91,232,max(height,768)-420),
            (0xad10a4,255,127,min(width-450,785),max(height,768)-456),
            (0xad10a8,0,91,252,max(height,768)-420),
            (0xad10ac,0,91,252,max(height,768)-420)):
            control=self.control(0xa2bf58,self.root,x,y,w,h)
            self.panels[global_va]=control;put(self.u,fixture.va(global_va),control)
        self.bags={};self.bars={}
        for panel,global_va,sub,y in ((0xad10a0,0xac4bd4,660,200),
                                      (0xad10a8,0xac4bbc,630,180),
                                      (0xad10ac,0xac4bc0,490,40)):
            parent=self.panels[panel];h=max(height,768)-sub
            bag=self.control(0x9b23e0,parent,7 if panel==0xad10a0 else 17,y,222,h)
            self.bags[global_va]=bag;put(self.u,fixture.va(global_va),bag)
            put(self.u,bag+0x40,h);put(self.u,bag+0x44,222)
            put(self.u,bag+0x2ac,h//16);put(self.u,bag+0x28c,1200)
            scrollbar=self.control(0xa2b6ec,bag,206,0,16,h)
            put(self.u,bag+0x298,scrollbar)
            self.u.mem_write(scrollbar+0x2a4,struct.pack('<f',71.5))
            if panel==0xad10a0:
                bar=self.control(0x9b0b10,parent,7,y+h+4,222,32)
                self.bars[global_va]=bar
        p=self.panels[0xad10a4];pw=get(self.u,p+0x38);ph=get(self.u,p+0x3c)
        self.table=self.control(0x995ec4,p,0,20,pw-130,ph-80)
        put(self.u,fixture.va(0xac4bd8),self.table)
        put(self.u,self.table+0x40,ph-80);put(self.u,self.table+0x44,pw-130)
        put(self.u,self.table+0x288,ph-112)
        self.table_scroll=self.control(0xa2b6ec,self.table,pw-146,0,16,ph-80)
        put(self.u,self.table+0x280,self.table_scroll)
        self.columns={}
        for global_va,x,w in ((0xad106c,pw-330,81),(0xad1070,pw-250,121),
                               (0xad1068,77,pw-407)):
            child=self.control(0x6c29cc,p,x,3,w,18)
            self.columns[global_va]=child;put(self.u,fixture.va(global_va),child)
        self.filter=self.control(0x6ca000,p,pw-125,3,125,ph-63)
        put(self.u,fixture.va(0xac4bb4),self.filter)
        put(self.u,self.filter+0x40,ph-63);put(self.u,self.filter+0x44,125)
        self.zoom=self.control(0xa2ed34,p,pw-32,ph-92,32,32)
        # A same-sized sibling with another position must remain untouched.
        self.zoom_canary=self.control(0xa2ed34,p,12,55,32,32)
        self.footer=[]
        for i,margin in enumerate((63,56,29,28,54,50,53,52,54)):
            child=self.control(0xa2ed34,p,pw-240 if i>=4 else 5,ph-margin,16,16)
            self.footer.append((child,margin,i>=4))
        self.top=self.control(0xa2ed34,p,5,50,16,16)
        for control, children in self.children.items():
            array=self.list_next+0x20;record=self.list_next;self.list_next+=0x100
            for i,child in enumerate(children):put(self.u,array+i*4,child)
            for offset,value in ((4,array),(8,len(children)),(12,len(children))):put(self.u,record+offset,value)
            put(self.u,control+0x2c,record)
        self.before={p:bytes(self.u.mem_read(p,0x400)) for p in self.objects}
        self.u.hook_add(UC_HOOK_CODE,self.hook)

    def control(self,vmt,parent,x,y,width,height):
        pointer=self.next;self.next+=0x500
        self.u.mem_write(pointer,bytes((i*13+7)&255 for i in range(0x400)))
        for offset,value in ((0,self.f.va(vmt)),(0x4c,parent),(0x30,x),(0x34,y),(0x38,width),(0x3c,height)):
            put(self.u,pointer+offset,value)
        self.children[pointer]=[];self.objects[pointer]=vmt
        if parent:self.children[parent].append(pointer)
        return pointer

    def hook(self,u,address,size,_):
        if address==self.f.va(0x4095ac):self.f.ret(result=1);return
        if address==self.f.va(0xa4176c):
            pointer=u.reg_read(UC_X86_REG_EAX);height=u.reg_read(UC_X86_REG_EDX)
            put(u,pointer+0x3c,height);self.f.ret();return
        if address==self.f.va(0xa417d0):
            pointer=u.reg_read(UC_X86_REG_EAX);sp=u.reg_read(UC_X86_REG_ESP)
            maximum=max(0.,struct.unpack('<f',u.mem_read(sp+4,4))[0])
            current=struct.unpack('<f',u.mem_read(pointer+0x2a4,4))[0]
            u.mem_write(pointer+0x2ac,struct.pack('<f',maximum))
            u.mem_write(pointer+0x2a4,struct.pack('<f',min(current,maximum)))
            self.f.ret(4);return
        if address==self.f.va(0x99efd4):
            self.f.ret();return

    def verify(self,width,height):
        h=max(height,768)
        assert tuple(get(self.u,self.root+o) for o in (0x30,0x34,0x38,0x3c))==(146,72,round((width-190)/32)*32,round((h-325)/32)*32)
        assert get(self.u,self.header+0x38)==get(self.u,self.root+0x38)-100
        for global_va,control in self.panels.items():
            w=20 if global_va==0xad1098 else (232 if global_va==0xad10a0 else 252)
            ph=h-420
            if global_va in (0xad1094,0xad109c):w=width-450
            if global_va==0xad10a4:w=min(width-450,785)
            if global_va in (0xad1098,0xad109c,0xad10a4):ph=h-456
            if global_va==0xad1094:ph=34
            assert (get(self.u,control+0x38),get(self.u,control+0x3c))==(w,ph)
        for global_va,sub in ((0xac4bd4,660),(0xac4bbc,630),(0xac4bc0,490)):
            bag=self.bags[global_va];bh=h-sub;sb=get(self.u,bag+0x298)
            assert tuple(get(self.u,bag+o) for o in (0x38,0x3c,0x40,0x44,0x2ac,0x2b0))==(222,bh,bh,222,bh//16,71)
            assert tuple(get(self.u,sb+o) for o in (0x30,0x34,0x38,0x3c))==(206,0,16,bh)
            if global_va in self.bars:assert get(self.u,self.bars[global_va]+0x34)==200+bh+4
        pw=min(width-450,785);ph=h-456;tw=pw-130;th=ph-80
        assert tuple(get(self.u,self.table+o) for o in (0x38,0x3c,0x40,0x44,0x288))==(tw,th,th,tw,th-32)
        assert tuple(get(self.u,self.table_scroll+o) for o in (0x30,0x34,0x38,0x3c))==(tw-16,0,16,th)
        assert get(self.u,self.columns[0xad106c]+0x30)==tw-200
        assert get(self.u,self.columns[0xad1070]+0x30)==tw-120
        assert get(self.u,self.columns[0xad1068]+0x38)==tw-277
        assert tuple(get(self.u,self.filter+o) for o in (0x30,0x34,0x38,0x3c,0x40,0x44))==(pw-125,3,125,ph-63,ph-63,125)
        assert tuple(get(self.u,self.zoom+o) for o in (0x30,0x34,0x38,0x3c))==(pw-32,ph-92,32,32)
        assert tuple(get(self.u,self.zoom_canary+o) for o in (0x30,0x34,0x38,0x3c))==(12,55,32,32)
        for child,margin,right in self.footer:
            assert get(self.u,child+0x34)==ph-margin
            assert get(self.u,child+0x30)==(pw-240 if right else 5)
        assert get(self.u,self.top+0x34)==50
        geometry=set(range(0x30,0x48))
        for pointer,before in self.before.items():
            allowed=set(geometry)
            if self.objects[pointer]==0x9b23e0:
                allowed|=set(range(0x2ac,0x2b4))
            if self.objects[pointer]==0x995ec4:allowed|=set(range(0x288,0x28c))
            if self.objects[pointer]==0xa2b6ec:allowed|=set(range(0x2a4,0x2a8))|set(range(0x2ac,0x2b0))
            after=bytes(self.u.mem_read(pointer,0x400))
            assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(before,after))),(hex(pointer),self.objects[pointer])


def divide(value, numerator, denominator):
    return int(value*numerator/denominator)


def expected(width, height, requested):
    if requested not in scale.PERCENTS:
        requested = 100
    choices = [p for p in scale.PERCENTS if p <= requested and
               (p == 100 or (width*100//p >= 800 and height*100//p >= 768))]
    actual = max(choices)
    return requested, actual, width*100//actual, height*100//actual


@lru_cache(maxsize=4)
def mapped_image(data, base):
    pe = pefile.PE(data=data); pe.relocate_image(base)
    return bytes(pe.get_memory_mapped_image())


class Fixture:
    def __init__(self, data, base, *, protect_failures=(), flush_failures=(), bad_host=False):
        image = mapped_image(data, base)
        self.base = base; self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        if base != 0x400000:
            self.u.mem_map(0x400000, 0x400000)
        self.u.mem_map(base, (len(image)+0xfff)&~0xfff); self.u.mem_write(base, image)
        self.u.mem_map(DATA, 0x30000); self.u.mem_map(STACK, 0x10000)
        self.u.mem_map(API, 0x1000)
        self.protect_failures = list(protect_failures)
        self.flush_failures = list(flush_failures)
        self.calls = []; self.clip_rects = []; self.ui_sizes = []
        self.world_rects = []
        self.squad_root = None
        self.stopping = END; self.upload_count = 0
        self.phase_native = None; self.phase_expected = None
        self.manager = DATA + 0x2000; self.renderer = DATA + 0x3000
        self.vb = DATA + 0x3800; self.rect = DATA + 0x4000
        for rva, slot, value in ((0x6c56e0, 0x7771e0, 1024),
                                 (0x6c5e60, 0x7771e4, 768),
                                 (0x6c5b70, 0x777150, 0),
                                 (0x6c5a04, 0x777154, 0)):
            put(self.u, base+rva, base+slot); put(self.u, base+slot, value)
        put(self.u, base+0x6c5a4c, base+0x7749d4)
        put(self.u, base+0x776650, self.manager)
        put(self.u, base+0x6c622c, base+0x776650)
        put(self.u, 0x76de0c, DATA+0x80); put(self.u, DATA+0x80, self.renderer)
        # Physical host input is a separate state from the copied Silver input.
        for address, slot, value in ((0x76e518, DATA+0x110, 1337),
                                      (0x76e440, DATA+0x114, 733)):
            put(self.u, address, slot); put(self.u, slot, value)
        self.physical_mouse = bytes(self.u.mem_read(DATA+0x110, 8))
        self.u.mem_write(scale.TI_UPLOAD_CALL, bytes.fromhex('e81964dbff'))
        self.u.mem_write(0x65085c, bytes.fromhex('558bec83'))
        if bad_host:
            self.u.mem_write(scale.TI_UPLOAD_CALL, b'\x90')
        for rva, address in ((0x77a090, API+0x10), (0x77a178, API+0x20),
                             (0x77a170, API+0x30), (0x77a1b0, API+0x50)):
            put(self.u, base+rva, address)
        put(self.u, base+0x6c5f04, base+0x6cc4d0)
        put(self.u, base+0x6cc4d0, API+0x60)
        put(self.u,base+0x6c5a00,DATA+0x140);put(self.u,DATA+0x140,API+0x70)
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def va(self, preferred):
        return self.base+preferred-scale.IMAGE_BASE

    def state(self, offset, value=None):
        address = self.base+scale.STATE+offset
        if value is not None:
            put(self.u, address, value)
        return get(self.u, address)

    def native_dims(self):
        return tuple(get(self.u, get(self.u, self.base+rva)) for rva in (0x6c56e0, 0x6c5e60))

    def ret(self, clean=0, result=None):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        if result is not None:
            self.u.reg_write(UC_X86_REG_EAX, result)
        self.u.reg_write(UC_X86_REG_EIP, get(self.u, sp))
        self.u.reg_write(UC_X86_REG_ESP, sp+4+clean)

    def hook(self, u, address, size, _):
        if address == self.stopping:
            u.emu_stop(); return
        sp = u.reg_read(UC_X86_REG_ESP)
        args = lambda n: [get(u, sp+4+4*i) for i in range(n)]
        if address == API+0x10:
            target, count, flags, out = args(4)
            assert (target, count) == (scale.TI_UPLOAD_CALL, 5)
            assert flags in (0x20, 0x40)
            fail = self.protect_failures.pop(0) if self.protect_failures else False
            self.calls.append(('protect', flags, fail))
            if not fail:
                put(u, out, 0x20 if flags == 0x40 else 0x40)
            self.ret(16, int(not fail)); return
        if address == API+0x20:
            raw = bytes(u.mem_read(args(1)[0], 26))
            assert raw == 'kernel32.dll\0'.encode('utf-16le')
            self.ret(4, 0xfeed0000); return
        if address == API+0x30:
            module, name = args(2)
            assert module == 0xfeed0000
            assert bytes(u.mem_read(name, 22)) == b'FlushInstructionCache\0'
            self.ret(8, API+0x40); return
        if address == API+0x40:
            proc, target, count = args(3)
            assert (proc, target, count) == (0xffffffff, scale.TI_UPLOAD_CALL, 5)
            fail = self.flush_failures.pop(0) if self.flush_failures else False
            self.calls.append(('flush', fail)); self.ret(12, int(not fail)); return
        if address == API+0x50:
            self.ret(result=0xffffffff); return
        if address == API+0x60:
            self.clip_rects.append(tuple(signed(x) for x in args(4)))
            self.ret(16, 0); return
        if address == API+0x70:
            self.world_rects.append(tuple(args(6)))
            assert self.state(0x14)==0
            self.ret(24,0);return
        if address == self.va(0x814608):
            self.ret();return
        if address == self.va(0xa3fca8):
            self.ret(result=0 if self.squad_root else 0xffffffff);return
        if address == self.va(0xa3f2a0):
            self.ret(result=self.squad_root or 0);return
        if address == scale.TI_COPY:
            source = u.reg_read(UC_X86_REG_EAX); dest = u.reg_read(UC_X86_REG_EDX)
            count = u.reg_read(UC_X86_REG_ECX)
            u.mem_write(dest, bytes(u.mem_read(source, count)))
            self.upload_count += 1; self.ret(); return
        if address == self.va(0xa3ec04):
            width, height = (u.reg_read(r) for r in (UC_X86_REG_EDX, UC_X86_REG_ECX))
            manager = u.reg_read(UC_X86_REG_EAX)
            put(u, manager+0x29c, width); put(u, manager+0x2a0, height)
            self.ui_sizes.append((width, height)); self.ret(); return
        if address in (self.va(0xa029dc), self.va(0xc24000), self.va(0xc24300)):
            assert get(u, self.base+0x776650), 'Startup relayout requires a constructed GUI manager'
            self.calls.append(('relayout', hex(address-self.base+0x400000), self.native_dims()))
            self.ret(); return
        if address == self.va(scale.RENDER_NATIVE):
            self.calls.append(('render_scope', self.state(0x14)))
            self.ret(); return
        if self.phase_native and address == self.va(self.phase_native):
            assert self.state(0x14) == self.phase_expected
            self.calls.append(('native_phase',hex(self.phase_native),self.state(0x14)))
            if self.phase_native == 0xa6a408:
                assert tuple(signed(get(u,get(u,self.base+rva))) for rva in (0x6c5b70,0x6c5a04)) == (1337,733)
            for index in (0,1,2,3,4,5):
                assert u.reg_read(REGS[index]) == VALUES[index]
            self.ret(result=0xdeadbeef);u.reg_write(UC_X86_REG_EFLAGS,0x202);return
        if address == self.va(scale.CORE_RVA+0x400000+0x3d00):
            self.ret(result=self.bootstrap_value); return

    def initialize(self, width, height, percent=150):
        for offset, value in ((4, width), (8, height), (0x18, percent)):
            self.state(offset, value)
        self.run(scale.SETTER, eax=percent)
        put(self.u, self.renderer+0x299, width)
        put(self.u, self.renderer+0x29d, height)

    def run(self, entry, *, eax=None, args=(), stop=None):
        for reg, value in zip(REGS, VALUES):
            self.u.reg_write(reg, value)
        if eax is not None:
            self.u.reg_write(UC_X86_REG_EAX, eax)
        sp = STACK+0xf000; put(self.u, sp, END)
        for i, value in enumerate(args):
            put(self.u, sp+4+i*4, value)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        self.u.reg_write(UC_X86_REG_EFLAGS, 0x246)
        self.stopping = self.va(stop) if stop else END
        self.u.emu_start(self.va(entry), END, count=100000)
        assert self.u.reg_read(UC_X86_REG_EIP) == self.stopping
        if not stop:
            assert self.u.reg_read(UC_X86_REG_ESP) == sp+4+4*len(args)
        assert bytes(self.u.mem_read(DATA+0x110, 8)) == self.physical_mouse
        return self.u.reg_read(UC_X86_REG_EAX)


def verify(data):
    cases = []
    for base in (0x400000, 0x10400000):
        for width, height in ((800, 600), (1024, 768), (1366, 768),
                               (1920, 1080), (2560, 1440), (3840, 2160)):
            for request in (100, 125, 150, 200, 0, 999):
                f = Fixture(data, base); f.initialize(width, height, request)
                requested, actual, logicalw, logicalh = expected(width, height, request)
                assert tuple(f.state(o) for o in (0x18, 0, 4, 8, 0xc, 0x10)) == (requested, actual, width, height, logicalw, logicalh)
                assert f.native_dims() == (logicalw, logicalh)
                assert f.ui_sizes == [(logicalw, logicalh)]
                assert [call[2] for call in f.calls if call[0]=='relayout'] == [(logicalw, logicalh)]*3
                for index in (1,4,5,6):
                    assert f.u.reg_read(REGS[index]) == VALUES[index]
                assert f.state(0x28) == 1 and f.state(0x2c) == 0
                cases.append({'kind':'scale', 'base':hex(base), 'physical':[width,height], 'requested':request,'actual':actual,'logical':[logicalw,logicalh]})
        # Stable requests survive physical resize and become effective again.
        f = Fixture(data, base); f.initialize(2560,1440,200)
        f.run(0x9f47f8, args=(1024,768)); assert f.state(0x18)==200 and f.state(0)==100
        f.run(0x9f47f8, args=(3840,2160)); assert f.state(0)==200 and f.native_dims()==(1920,1080)
        cases.append({'kind':'physical_resize', 'base':hex(base)})
        for failure in ('host_guard','protect','flush'):
            f = Fixture(data, base, bad_host=failure=='host_guard',
                        protect_failures=(True,) if failure=='protect' else (),
                        flush_failures=(True,False) if failure=='flush' else ())
            f.initialize(2560,1440,150)
            assert f.state(0)==100 and f.state(0x18)==150 and f.state(0x28)==0xffffffff
            assert f.native_dims()==(2560,1440)
            calls = list(f.calls); f.run(scale.SETTER,eax=150)
            assert len([c for c in f.calls if c[0] in ('protect','flush')]) == len([c for c in calls if c[0] in ('protect','flush')])
            if failure=='flush': assert bytes(f.u.mem_read(scale.TI_UPLOAD_CALL,5))==bytes.fromhex('e81964dbff')
            cases.append({'kind':'installation_failure', 'base':hex(base),'failure':failure})
        for bootstrap in (100,125,150,200,0,999):
            f=Fixture(data,base); f.bootstrap_value=bootstrap
            f.state(0x24,scale.CORE_RVA+0x3d00)
            f.run(0x9f47f8,args=(2560,1440))
            assert f.state(0)==expected(2560,1440,bootstrap)[1]
            cases.append({'kind':'bootstrap','base':hex(base),'value':bootstrap})
        for small in ((1,1),(799,1440),(2560,599),(0,0)):
            f=Fixture(data,base); f.bootstrap_value=150
            f.state(0x24,scale.CORE_RVA+0x3d00)
            f.run(0x9f47f8,args=small)
            assert f.state(0x18)==0 and f.state(0x28)==0
            assert f.native_dims()==small
            f.run(0x9f47f8,args=(2560,1440))
            assert f.state(0)==150 and f.state(0x18)==150
            assert f.native_dims()==(1706,960)
            cases.append({'kind':'transient_startup','base':hex(base),'temporary':list(small),'final':[2560,1440]})
        # SILVER_Init can receive real physical bounds before its GUI manager
        # exists. Execute native Resize's null-manager branch and require all
        # extra reflows to remain unreachable, then construct the same manager
        # and prove the ordinary resize still performs the existing reflows.
        for requested in (100,125,150,200):
            f=Fixture(data,base); f.bootstrap_value=requested
            f.state(0x24,scale.CORE_RVA+0x3d00)
            put(f.u,base+0x776650,0)
            f.run(0x9f47f8,args=(2560,1363))
            _,actual,lw,lh=expected(2560,1363,requested)
            assert f.native_dims()==(lw,lh)
            assert f.state(0x18)==requested and f.state(0)==actual
            assert not f.ui_sizes and not any(c[0]=='relayout' for c in f.calls)
            assert f.state(0x28)==1 and f.state(0x2c)==0
            put(f.u,base+0x776650,f.manager)
            f.run(0x9f47f8,args=(2560,1363))
            assert f.ui_sizes==[(lw,lh)]
            assert [c[2] for c in f.calls if c[0]=='relayout']==[(lw,lh)]*3
            cases.append({'kind':'real_bounds_before_GUI_Init','base':hex(base),
                          'physical':[2560,1363],'requested':requested,'actual':actual,
                          'logical':[lw,lh],'early_reflows_skipped':True,
                          'later_existing_manager_reflowed':True})
        # Change scale repeatedly after the PDA was constructed at150%. Execute
        # its real tile-quantized bounds and child list code, with content/range
        # callbacks explicitly stubbed. Every unrelated byte remains a canary.
        f=Fixture(data,base);f.initialize(2560,1363,150);squad=SquadFixture(f)
        for request in (100,125,150,200,100):
            f.run(scale.SETTER,eax=request)
            _,actual,lw,lh=expected(2560,1363,request)
            squad.verify(lw,lh)
            assert f.state(0)==actual and f.state(0x18)==request
            for index in (1,4,5,6):assert f.u.reg_read(REGS[index])==VALUES[index]
            assert f.u.reg_read(UC_X86_REG_ESP)==STACK+0xf004
            cases.append({'kind':'existing_PDA_reflow','base':hex(base),
                          'requested':request,'actual':actual,'logical':[lw,lh],
                          'native_root_bounds_executed':True,'unrelated_bytes_preserved':True})
        for physical,request in (((1024,768),150),((3840,2160),200),((2560,1440),150)):
            f.run(0x9f47f8,args=physical)
            f.run(scale.SETTER,eax=request)
            _,actual,lw,lh=expected(*physical,request)
            squad.verify(lw,lh)
            cases.append({'kind':'existing_PDA_physical_resize','base':hex(base),
                          'physical':list(physical),'requested':request,'actual':actual,
                          'logical':[lw,lh],'native_root_bounds_executed':True})
        for guard in ('missing_global','other_global','wrong_class','wrong_parent'):
            f=Fixture(data,base);f.initialize(2560,1363,150);squad=SquadFixture(f)
            if guard=='missing_global':put(f.u,f.va(0xac4bb4),0)
            if guard=='other_global':put(f.u,f.va(0xac4bb4),squad.zoom)
            if guard=='wrong_class':put(f.u,squad.filter,f.va(0xa2bf58))
            if guard=='wrong_parent':put(f.u,squad.filter+0x4c,squad.root)
            before=bytes(f.u.mem_read(squad.filter,0x400))
            f.run(scale.SETTER,eax=100)
            assert bytes(f.u.mem_read(squad.filter,0x400))==before
            cases.append({'kind':'existing_filter_guard','base':hex(base),'guard':guard,
                          'all_filter_bytes_preserved':True})
        for field,value in ((0,0xa2bf58),(0x30,754),(0x34,361),(0x38,31),(0x3c,31)):
            f=Fixture(data,base);f.initialize(2560,1363,150);squad=SquadFixture(f)
            put(f.u,squad.zoom+field,f.va(value) if field==0 else value)
            before=bytes(f.u.mem_read(squad.zoom,0x400))
            f.run(scale.SETTER,eax=100)
            assert bytes(f.u.mem_read(squad.zoom,0x400))==before
            cases.append({'kind':'existing_filter_zoom_guard','base':hex(base),
                          'field':hex(field),'all_unrelated_button_bytes_preserved':True})
        for percent in scale.PERCENTS:
            f=Fixture(data,base); f.initialize(2560,1440,percent)
            lw,lh=f.native_dims(); f.state(0x14,0)
            f.run(scale.RENDER); assert ('render_scope',0) in f.calls and f.state(0x14)==0
            f.state(0x14,7); f.run(scale.RENDER); assert f.state(0x14)==7
            for index,(site,native,name) in enumerate(scale.UI_CALLS):
                f.state(0x14,7);f.phase_native=native;f.phase_expected=1
                f.run(site,stop=site+5)
                assert f.state(0x14)==7 and f.u.reg_read(UC_X86_REG_EAX)==0xdeadbeef
                assert f.u.reg_read(UC_X86_REG_EFLAGS)==0x202
                assert f.u.reg_read(UC_X86_REG_ESP)==STACK+0xf000
                for register_index in (1,4,5,6):assert f.u.reg_read(REGS[register_index])==VALUES[register_index]
                cases.append({'kind':'explicit_gui_scope','base':hex(base),'percent':percent,'name':name})
            for site,native,name in scale.WORLD_CALLS:
                assert bytes(f.u.mem_read(f.va(site),5))==scale.call_bytes(site,native)
                f.state(0x14,0);f.phase_native=native;f.phase_expected=0
                f.run(site,stop=site+5)
                assert f.state(0x14)==0
                cases.append({'kind':'physical_world_scope','base':hex(base),'percent':percent,'name':name})
            f.phase_native=None;f.state(0x14,0)
            for rva,slot,value in ((0x6c64a0,DATA+0x150,1),
                                  (0x6c5a30,DATA+0x154,0),
                                  (0x6c61b0,DATA+0x158,1000),
                                  (0x6c6068,DATA+0x15c,500)):
                put(f.u,base+rva,slot);put(f.u,slot,value)
            put(f.u,base+0x818bf8,1);f.u.mem_write(base+0x818c00,bytes((5,6,2)))
            f.run(0x9f40ae,stop=0x9f40b3)
            assert f.world_rects[-1]==(1024,687,16,10,0x50ffe36b,0)
            assert tuple(get(f.u,get(f.u,base+rva)) for rva in (0x6c61b0,0x6c6068))==(1000,500)
            cases.append({'kind':'native_f7_marker','base':hex(base),'percent':percent,'physical_rectangle':list(f.world_rects[-1])})
            f.state(0x14,7);f.phase_native=0xa6a408;f.phase_expected=0
            for rva,value in ((0x6c5b70,17),(0x6c5a04,23)):put(f.u,get(f.u,f.base+rva),value)
            f.run(0x9f41a3,stop=0x9f41a8)
            assert f.state(0x14)==7
            assert tuple(get(f.u,get(f.u,f.base+rva)) for rva in (0x6c5b70,0x6c5a04))==(17,23)
            f.phase_native=None
            cases.append({'kind':'physical_cursor','base':hex(base),'percent':percent})
            for active, fvf, stride, viewport in ((1,0x144,28,'normal'),(0,0x144,28,'normal'),
                                                 (1,0x142,36,'normal'),(1,0x144,28,'portrait'),
                                                 (1,0x144,8,'normal'),(1,0x144,36,'normal')):
                f.state(0x14,active); put(f.u,f.vb+0x18,fvf);put(f.u,f.vb+0x1c,stride)
                put(f.u,FRAME-4,f.vb)
                put(f.u,f.renderer+0x299,512 if viewport=='portrait' else 4096)
                put(f.u,f.renderer+0x29d,512 if viewport=='portrait' else 4096)
                original=bytearray((i*17+3)&255 for i in range(stride*3))
                if stride>=16:
                    for i in range(3):struct.pack_into('<ff',original,i*stride,(-20.,71.,1706.)[i],(5.,120.,959.)[i])
                src=DATA+0x5000;dst=DATA+0x6000;f.u.mem_write(src,bytes(original))
                for reg,value in zip(REGS,VALUES):f.u.reg_write(reg,value)
                f.u.reg_write(UC_X86_REG_EAX,src);f.u.reg_write(UC_X86_REG_EDX,dst)
                f.u.reg_write(UC_X86_REG_ECX,len(original));sp=STACK+0xf000;put(f.u,sp,END)
                f.u.reg_write(UC_X86_REG_ESP,sp);f.stopping=END
                before=[f.u.reg_read(r) for r in REGS]
                f.u.emu_start(f.va(scale.UPLOAD),END,count=100000)
                assert [f.u.reg_read(r) for r in REGS]==before
                assert f.u.reg_read(UC_X86_REG_ESP)==sp+4
                out=bytes(f.u.mem_read(dst,len(original)));want=bytearray(original)
                if active and percent>100 and fvf&0xe==4 and stride>=16 and viewport=='normal':
                    for i in range(3):
                        x,y=struct.unpack_from('<ff',original,i*stride)
                        struct.pack_into('<ff',want,i*stride,x*(2560/lw),y*(1440/lh))
                assert out==bytes(want) and bytes(f.u.mem_read(src,len(original)))==bytes(original)
                cases.append({'kind':'gpu_vertices','base':hex(base),'percent':percent,'scope':active,'fvf':hex(fvf),'stride':stride,'viewport':viewport})
            for active,viewport in ((1,'normal'),(0,'normal'),(1,'portrait')):
                f.state(0x14,active);put(f.u,f.renderer+0x299,512 if viewport=='portrait' else 4096)
                put(f.u,f.renderer+0x29d,512 if viewport=='portrait' else 4096)
                rect=(-10,42,lw-42,lh-206)
                f.u.mem_write(f.rect,struct.pack('<4i',*rect));f.run(0x4f2eb4,eax=f.rect)
                want=tuple(divide(v,(2560,1440)[i%2],(lw,lh)[i%2]) for i,v in enumerate(rect)) if active and percent>100 and viewport=='normal' else rect
                assert f.clip_rects[-1]==want
                assert bytes(f.u.mem_read(f.base+0x6cc530,16))==struct.pack('<4i',*rect)
                cases.append({'kind':'scissor','base':hex(base),'percent':percent,'scope':active,'viewport':viewport})
            for xy in ((1337,733),(-23,-17),(2559,1439)):
                x,y=xy;want=(divide(x,lw,2560),divide(y,lh,1440))
                for hook_index,stop,slots in ((4,0x9f485f,(UC_X86_REG_ESI,UC_X86_REG_EDI)),
                                              (5,0x9f4b7f,(UC_X86_REG_ESI,UC_X86_REG_EDI)),
                                              (6,0x9f4e23,(UC_X86_REG_EBX,UC_X86_REG_ESI)),
                                              (7,0x9f4b63,(UC_X86_REG_EAX,UC_X86_REG_EDX))):
                    va=scale.HOOKS[hook_index][0]
                    if hook_index in (4,5):put(f.u,FRAME+8,2);put(f.u,FRAME+12,x);put(f.u,FRAME+16,y)
                    elif hook_index==6:put(f.u,FRAME+12,x);put(f.u,FRAME+16,y)
                    else:put(f.u,FRAME+8,x);put(f.u,FRAME+12,y)
                    f.run(va,stop=stop)
                    assert tuple(signed(f.u.reg_read(r)) for r in slots)==want
                    assert tuple(signed(get(f.u,get(f.u,base+rva))) for rva in (0x6c5b70,0x6c5a04))==want
                    assert f.u.reg_read(UC_X86_REG_EFLAGS)==0x246
                    if hook_index in (4,5):assert f.u.reg_read(UC_X86_REG_EBX)==2
                    cases.append({'kind':'input','base':hex(base),'percent':percent,'hook':hex(va),'physical':list(xy),'logical':list(want)})
                put(f.u,get(f.u,base+0x6c5b70),x);f.run(0x9f3aa5,eax=y,stop=0x9f3aad)
                assert tuple(signed(get(f.u,get(f.u,base+rva))) for rva in (0x6c5b70,0x6c5a04))==want
                assert f.u.reg_read(UC_X86_REG_EDX)==get(f.u,base+0x6c5a04)
                assert f.u.reg_read(UC_X86_REG_EFLAGS)==0x246
                cases.append({'kind':'copied_mouse','base':hex(base),'percent':percent,'physical':list(xy)})
    return cases


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,default=ROOT/'reports/ui-scale/core/silver.dll')
    parser.add_argument('--out',type=Path,default=ROOT/'reports/ui-scale/core/native-proof.json')
    args=parser.parse_args();data=args.candidate.read_bytes();cases=verify(data)
    result={'result':'PASS','candidate_sha256':hashlib.sha256(data).hexdigest(),'cases':len(cases),
            'details':cases,'windows_apis_stubbed':True,'native_manager_and_reflow_stubbed':True,
            'actual_native_resize_and_rect_code_executed':True,'real_client_rendering_verified':False}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: {len(cases)} UI scale native cases')


if __name__=='__main__':main()
