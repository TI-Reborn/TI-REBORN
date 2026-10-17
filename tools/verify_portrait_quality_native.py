"""Execute portrait extension x86 at two ASLR bases; native GUI/COM calls stubbed.

This does not launch a client. Constructors, list lookup, visibility and frame
quantization are explicit fixtures. Destination geometry, all branch paths,
stack/register preservation and the original target-creation code are executed.
"""
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
from deploy import client_portrait_quality as q

DATA, STACK, STOP = 0x30000000, 0x31000000, 0x3001ff00
REGISTERS = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
CANARIES = (0x12345678, 0x23456789, 0x3456789a, 0x456789ab)


def put32(u, a, v):
    u.mem_write(a, struct.pack('<I', v & 0xffffffff))


def get32(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


@lru_cache(maxsize=6)
def mapped(image, base):
    pe = pefile.PE(data=image); pe.relocate_image(base)
    return pe.get_memory_mapped_image()


def fixture_image(source):
    """Use a real post-panel candidate, or pad .11 for an isolated fixture only."""
    p = pefile.PE(data=source)
    if p.OPTIONAL_HEADER.SizeOfImage == q.SECTION_RVA+q.SIZE:
        from deploy import client_ui_scale as core, client_ui_scale_controls as controls
        frozen = ROOT/'reports/screen-settings/graphical/source'/core.BASE_SHA/'silver.dll'
        before = core.patch(frozen.read_bytes())
        before = controls.patch(before, expected_sha=q.sha(before))
        assert q.patch(before, expected_sha=q.sha(before)) == source
        return source, False
    if p.OPTIONAL_HEADER.SizeOfImage == q.SECTION_RVA:
        return q.patch(source, expected_sha=q.sha(source)), False
    assert p.OPTIONAL_HEADER.SizeOfImage == 0x825000
    from deploy import client_ui_scale as core, client_ui_scale_controls as controls
    d = core.patch(source)
    d = controls.patch(d, expected_sha=q.sha(d))
    return q.patch(d, expected_sha=q.sha(d)), False


class Fixture:
    def __init__(self, image, base, width=2560, height=1440):
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        memory = mapped(image, base)
        self.u.mem_map(base, (len(memory)+4095)&~4095); self.u.mem_write(base, memory)
        self.u.mem_map(DATA, 0x20000); self.u.mem_map(STACK, 0x10000)
        self.u.mem_map(0, 0x1000)  # Native x86 SEH chain at FS:[0].
        if base != 0x400000:
            self.u.mem_map(0x400000, 0x400000)
        self.base, self.next = base, DATA+0x6000
        self.manager, self.original = DATA+0x1000, DATA+0x2000
        self.windows, self.names, self.children = [], {}, {}
        self.calls, self.quads, self.states, self.close_callback = [], [], [], None
        self.width, self.height = width, height
        self.window_vmt = get32(self.u, self.va(0xa319e8))
        self.portrait_vmt = get32(self.u, self.va(0x8a228c))
        for va, cell, value in ((0xac56e0, DATA+0x100, width), (0xac5e60, DATA+0x104, height),
                                (0xac5b70, DATA+0x108, 99), (0xac5a04, DATA+0x10c, 77)):
            put32(self.u, self.va(va), cell); put32(self.u, cell, value)
        put32(self.u, self.va(0xb76650), self.manager)
        put32(self.u, 0x777030, DATA+0x5000)
        self.u.mem_write(self.original, b'\xa5'*0x400)
        put32(self.u, self.original, self.portrait_vmt)
        put32(self.u, self.original+0x17c, self.manager)
        put32(self.u, self.original+0x4c, DATA+0x3000)
        put32(self.u, DATA+0x3000+0x68, 0)
        self.children[self.original] = []
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def va(self, va):
        return self.base+va-0x400000

    def allocate(self):
        result = self.next; self.next += 0x400
        return result

    def return_(self, extra=0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, get32(self.u, sp))
        self.u.reg_write(UC_X86_REG_ESP, sp+4+extra)

    def text(self, pointer):
        return bytes(self.u.mem_read(pointer, 2*get32(self.u, pointer-4))).decode('utf-16le')

    def clone_name(self, pointer):
        # Actual native40b47c clones refcount-1 static UnicodeString literals.
        text=self.text(pointer);block=self.allocate()
        self.u.mem_write(block,struct.pack('<HHiI',1200,2,1,len(text))+
                         text.encode('utf-16le')+b'\0\0')
        return block+12

    def run(self, va, eax=0, edx=0, ecx=0, stack=(), edi=None):
        sp = STACK+0xf000
        for register, value in zip(REGISTERS, CANARIES): self.u.reg_write(register, value)
        if edi is not None: self.u.reg_write(UC_X86_REG_EDI, edi)
        self.u.reg_write(UC_X86_REG_EAX, eax); self.u.reg_write(UC_X86_REG_EDX, edx)
        self.u.reg_write(UC_X86_REG_ECX, ecx)
        self.u.mem_write(sp, struct.pack('<'+'I'*(len(stack)+1), STOP, *stack))
        self.u.reg_write(UC_X86_REG_ESP, sp)
        try:
            self.u.emu_start(self.va(va), STOP, count=100000)
        except Exception as error:
            if hasattr(self, 'trace'): print('native fixture trace', self.trace[-30:])
            raise RuntimeError(f'Fixture {va:#x} base {self.base:#x} failed at '
                               f'EIP {self.u.reg_read(UC_X86_REG_EIP):#x}, '
                               f'ESP {self.u.reg_read(UC_X86_REG_ESP):#x}') from error
        assert self.u.reg_read(UC_X86_REG_ESP) == sp+4+4*len(stack)
        for register, value in zip(REGISTERS, CANARIES):
            if register == UC_X86_REG_EDI and edi is not None: value = edi
            assert self.u.reg_read(register) == value, (hex(va), register)

    def hook(self, u, address, size, _):
        if not hasattr(self, 'trace'): self.trace = []
        self.trace.append((hex(address), hex(u.reg_read(UC_X86_REG_ESP))))
        if len(self.trace) > 40: self.trace.pop(0)
        if address == STOP: u.emu_stop(); return
        eax, edx, ecx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        sp = u.reg_read(UC_X86_REG_ESP)
        if address == 0x7427d8:
            self.states.append(eax); self.return_(); return
        if address == 0x611c10:
            # Stack top: five native UV arguments then eight doubles in reverse
            # push order. TI's registered drawing function consumes84bytes.
            values = struct.unpack('<5I8d', u.mem_read(sp+4, 84))
            self.quads.append(dict(texture=eax, args=values[:5], reversed_xy=values[5:], edx=edx, ecx=ecx))
            self.return_(84); return
        va = address-self.base+0x400000
        if va == 0xa3fca8:
            assert eax == self.manager
            ptr = self.names.get(self.text(edx))
            u.reg_write(UC_X86_REG_EAX, self.windows.index(ptr) if ptr else 0xffffffff)
        elif va == 0xa3f2a0:
            assert eax == self.manager
            u.reg_write(UC_X86_REG_EAX, self.windows[edx])
        elif va == 0xa4341c:
            assert ecx == self.manager and edx & 0xff == 1
            ptr, close = self.allocate(), self.allocate()
            put32(u, ptr, self.window_vmt); put32(u, ptr+0x17c, self.manager)
            put32(u, ptr+0x344, close); put32(u, close+0x4c, ptr)
            u.mem_write(close+0x30,struct.pack('<4I',0,16,64,64))
            u.mem_write(close+0x49,b'\1')
            u.mem_write(ptr+0x340, struct.pack('<HH', 32, 32))
            self.windows.append(ptr); self.children[ptr] = [close]
            self.calls.append('create_window'); u.reg_write(UC_X86_REG_EAX, ptr)
        elif va == 0x40b47c:
            text = self.text(edx)
            clone=self.clone_name(edx);assert clone!=edx
            put32(u, eax, clone)
            if text == 'window_portrait_preview': self.names[text] = eax-0x68
        elif va == 0xa42b04:
            assert get32(u, edx-4) == len('Боец: мышь — поворот, ПКМ — закрыть'.encode('utf-16le'))
            put32(u, eax+0x5c, edx)
        elif va == 0xa55038:
            self.close_callback = edx; self.calls.append('register_close')
        elif va == 0x8aa4a4:
            parent, height, width, y = struct.unpack('<4I', u.mem_read(sp+4, 16))
            ptr = self.allocate(); put32(u, ptr, self.portrait_vmt)
            put32(u, ptr+0x17c, self.manager); put32(u, ptr+0x4c, parent)
            u.mem_write(ptr+0x30, struct.pack('<4I', ecx, y, width, height))
            u.mem_write(ptr+0x49,b'\1')
            self.children[parent].append(ptr); self.calls.append('create_portrait')
            u.reg_write(UC_X86_REG_EAX, ptr); self.return_(16); return
        elif va == 0x4095ac:
            u.reg_write(UC_X86_REG_EAX, get32(u, eax) == self.window_vmt)
        elif va == 0xa424d4:
            u.reg_write(UC_X86_REG_EAX, len(self.children.get(eax, [])))
        elif va == 0xa424c4:
            u.reg_write(UC_X86_REG_EAX, self.children[eax][edx])
        elif va == 0xa43a54:
            u.mem_write(eax+0x49, bytes([edx & 0xff])); self.calls.append('show')
        elif va == 0xa4370c:
            u.mem_write(eax+0x49, b'\0'); self.calls.append('hide')
        elif va == 0x9b63d0:
            self.calls.append(('normal_draw', eax, edx))
        elif va == 0x9f4867:
            # Execute the exact guarded replayed SEH prefix; only the remaining
            # native game input handler is stubbed, and never called for match.
            assert eax == 0 and get32(u, sp) == self.va(0x9f4ab7)
            self.calls.append('native_mouse_fallback')
            u.reg_write(UC_X86_REG_ESP, sp+8)
            u.reg_write(UC_X86_REG_EIP, self.va(0x9f4abe))
            return
        else:
            return
        self.return_()


class InputFixture(Fixture):
    """Execute native hit recursion, MouseDown, drag update and arrow render.

    Only non-geometric script/variant command dispatch is captured. Native
    rectangle creation and containment, native inherited hit methods, native
    polling and angle arithmetic execute from the actual relocated PE image.
    """
    def __init__(self, image, base, width=2560, height=1440):
        super().__init__(image, base, width, height)
        self.commands = []
        put32(self.u, self.va(0xac5a50), DATA+0x110)
        put32(self.u, self.va(0xac64b4), DATA+0x114)
        put32(self.u, DATA+0x114, 0)
        put32(self.u, self.va(0xac618c), DATA+0x120)
        put32(self.u, DATA+0x120, DATA+0x200)
        put32(self.u, DATA+0x200+0x28, 1234)
        put32(self.u, self.va(0xac622c), DATA+0x124)
        put32(self.u, DATA+0x124, self.manager)

    def render_area_events(self, control):
        # Constructor creates event objects even when their callback lists are
        # empty. Native a54594 executes against this authentic empty-list ABI.
        event, callbacks = self.allocate(), self.allocate()
        put32(self.u, event+8, callbacks); put32(self.u, callbacks+8, 0)
        for offset in (0x2d0, 0x2d4, 0x2dc): put32(self.u, control+offset, event)
        put32(self.u, control+0x298, 0)

    def hook(self, u, address, size, _):
        va = address-self.base+0x400000
        eax, edx, ecx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        if va == 0x9bf334:
            u.reg_write(UC_X86_REG_EAX, 1); self.return_(); return
        if va == 0x43afc0:
            u.mem_write(eax, struct.pack('<4I', ecx & 0xff, 0, edx, 0))
            self.return_(); return
        if va == 0xa88a78:
            assert edx == 2
            variants = struct.unpack('<12I', u.mem_read(eax, 48))
            self.commands.append((variants[2], variants[6], variants[10]))
            self.return_(); return
        if va in (0x40c9f4, 0xa54980):
            self.return_(); return
        if va == 0x675000:
            self.return_(20); return
        super().hook(u, address, size, _)


def verify_native_input(candidate):
    cases = []
    for base in (0x400000, 0x10400000):
        for screen, region in (((2560,1440),'torso'),((2560,1440),'feet'),
                               ((960,540),'torso'),((960,540),'feet')):
            f = InputFixture(candidate, base, *screen)
            f.run(q.MOUSE_ENTRY, f.original, 1, 100, (100,))
            root=f.names['window_portrait_preview'];control=f.children[root][-1]
            f.render_area_events(control)
            f.u.mem_write(control+0x4a,b'\1')
            side=get32(f.u,control+0x38)
            assert get32(f.u,control+0x2f4)==side
            put32(f.u,control+0x2e8,75)
            px=get32(f.u,root+0x30)+get32(f.u,control+0x30)+side//2
            py=get32(f.u,root+0x34)+get32(f.u,control+0x34)+(side//2 if region=='torso' else side-1)
            put32(f.u,DATA+0x108,px);put32(f.u,DATA+0x10c,py)
            # Native hit recursion now reaches the standalone render area.
            f.run(0xa42c48,root,px-get32(f.u,root+0x30),py-get32(f.u,root+0x34))
            assert f.u.reg_read(UC_X86_REG_EAX)==control
            f.run(0xa43070,control,0,px,(py,))
            assert f.u.mem_read(control+0x2e0,1)==b'\1'
            assert get32(f.u,control+0x2e4)==px
            f.u.mem_write(DATA+0x110,b'\1')
            # Native update is allowed to drag outside the hit rectangle after
            # capture. Feet within visible side still pass native Rect math.
            put32(f.u,DATA+0x108,px+70)
            cache=bytes(f.u.mem_read(control+0x40,8))
            f.run(0x8aa5c0,control)
            assert get32(f.u,control+0x2e8)==5
            assert get32(f.u,control+0x2e4)==px+70
            assert f.commands==[(33,1234,5)]
            assert bytes(f.u.mem_read(control+0x40,8))==cache
            f.u.mem_write(DATA+0x110,b'\0');f.run(0x8aa5c0,control)
            assert f.u.mem_read(control+0x2e0,1)==b'\0'
            cases.append(dict(base=hex(base),logical_screen=list(screen),native_drag_region=region,
                              native_hit_and_MouseDown=True,angle_before=75,angle_after=5,
                              actual_native_Update=True,native_mouse_release=True))
        # Prove the original zero-height bug using the real native Update.
        f=InputFixture(candidate,base)
        f.run(q.MOUSE_ENTRY,f.original,1,100,(100,))
        root=f.names['window_portrait_preview'];control=f.children[root][-1]
        put32(f.u,control+0x2f4,0);put32(f.u,control+0x2e8,75)
        put32(f.u,control+0x2e4,100);f.u.mem_write(control+0x2e0,b'\1')
        f.u.mem_write(DATA+0x110,b'\1')
        put32(f.u,DATA+0x108,170)
        put32(f.u,DATA+0x10c,get32(f.u,root+0x34)+get32(f.u,control+0x34)+50)
        f.run(0x8aa5c0,control)
        assert get32(f.u,control+0x2e8)==75 and not f.commands
        cases.append(dict(base=hex(base),old_zero_drag_height_reproduced=True))
        for name in ('ordinary_window','window_portrait_previeX','',None):
            f=InputFixture(candidate,base)
            f.u.mem_write(f.original,b'\0'*0x400)
            put32(f.u,f.original,f.portrait_vmt);put32(f.u,f.original+0x4c,DATA+0x3000)
            put32(f.u,DATA+0x3000,f.window_vmt)
            if name is not None:
                block=f.allocate();f.u.mem_write(block,struct.pack('<HHiI',1200,2,1,len(name))+name.encode('utf-16le')+b'\0\0')
                put32(f.u,DATA+0x3000+0x68,block+12)
            f.render_area_events(f.original)
            f.run(0xa4d684,f.original,20,30)
            assert f.u.reg_read(UC_X86_REG_EAX)==1
            cases.append(dict(base=hex(base),ordinary_native_mouse_transparency_preserved=name))
        for guard in ('ordinary_render_area','foreign_parent_class','no_parent','name_short_page_boundary'):
            f=InputFixture(candidate,base)
            f.run(q.MOUSE_ENTRY,f.original,1,100,(100,))
            root=f.names['window_portrait_preview'];control=f.children[root][-1]
            f.render_area_events(control)
            if guard=='ordinary_render_area':put32(f.u,control,get32(f.u,f.va(0xa2c1b0)))
            elif guard=='foreign_parent_class':put32(f.u,root,0x12345678)
            elif guard=='no_parent':put32(f.u,control+0x4c,0)
            else:
                put32(f.u,root+0x68,DATA+0x20000);put32(f.u,DATA+0x20000-4,22)
            before=bytes(f.u.mem_read(control,0x400))
            f.run(0xa4d684,control,20,30)
            assert f.u.reg_read(UC_X86_REG_EAX)==1
            assert bytes(f.u.mem_read(control,0x400))==before
            cases.append(dict(base=hex(base),preview_hit_guard_keeps_native=guard,control_unchanged=True))
        f=InputFixture(candidate,base)
        f.run(q.MOUSE_ENTRY,f.original,1,100,(100,))
        root=f.names['window_portrait_preview'];control=f.children[root][-1]
        f.render_area_events(control)
        px=get32(f.u,control+0x30)+100;py=get32(f.u,control+0x34)+100
        patched=bytes(f.u.mem_read(f.va(0xa4d684),6))
        f.u.mem_write(f.va(0xa4d684),bytes.fromhex('558bec515356'))
        f.run(0xa42c48,root,px,py)
        assert f.u.reg_read(UC_X86_REG_EAX)==root
        # Use a fresh emulator so a restored JMP is not hidden by Unicorn's
        # previously translated original native block.
        f=InputFixture(candidate,base)
        f.run(q.MOUSE_ENTRY,f.original,1,100,(100,))
        root=f.names['window_portrait_preview'];control=f.children[root][-1]
        f.render_area_events(control)
        px=get32(f.u,control+0x30)+100;py=get32(f.u,control+0x34)+100
        f.run(0xa42c48,root,px,py)
        assert f.u.reg_read(UC_X86_REG_EAX)==control
        cases.append(dict(base=hex(base),old_native_transparent_hit_reproduced=True,
                          scoped_hook_native_recursion_reaches_portrait=True))
        for side_name,sign in (('left',10),('right',-10)):
            f=InputFixture(candidate,base)
            f.run(q.MOUSE_ENTRY,f.original,1,100,(100,))
            root=f.names['window_portrait_preview'];control=f.children[root][-1]
            side=get32(f.u,control+0x38)
            cx=get32(f.u,root+0x30)+get32(f.u,control+0x30)+side//2
            cy=get32(f.u,root+0x34)+get32(f.u,control+0x34)+side//2
            px=cx-39 if side_name=='left' else cx+39
            py=cy+get32(f.u,control+0x2f0)+16
            put32(f.u,DATA+0x108,px);put32(f.u,DATA+0x10c,py)
            f.u.mem_write(DATA+0x110,b'\1')
            closure=DATA+0x4000;put32(f.u,closure+0xc,control)
            f.run(0x8aa1f0,closure,cx,cy)
            assert f.commands==[(48,1234,sign & 0xffffffff)]
            assert not (get32(f.u,root+0x34)+get32(f.u,control+0x34)<=py<=get32(f.u,root+0x34)+get32(f.u,control+0x34)+side)
            cases.append(dict(base=hex(base),native_arrow=side_name,native_render_polling=True,
                              independent_of_body_hit=True,rotation_command_delta=sign))
    return cases


def verify_ti(original):
    candidate = q.patch_ti(original)
    assert candidate == original and q.sha(candidate) == q.TI_SHA
    p = pefile.PE(data=original)
    changed = [i for i, pair in enumerate(zip(original, candidate)) if pair[0] != pair[1]]
    assert changed == []
    assert candidate[p.get_offset_from_rva(0x6b02e4-0x400000):][:10] == original[p.get_offset_from_rva(0x6b02e4-0x400000):][:10]
    assert candidate[p.get_offset_from_rva(0x6f709c-0x400000):][:0xf0] == original[p.get_offset_from_rva(0x6f709c-0x400000):][:0xf0]
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    image = mapped(candidate, 0x400000)
    u.mem_map(0x400000, (len(image)+4095)&~4095); u.mem_write(0x400000, image)
    u.mem_map(DATA, 0x20000); u.mem_map(STACK, 0x10000)
    put32(u, 0x76e168, DATA+0x100); put32(u, DATA+0x100, DATA+0x1000)
    put32(u, STACK+0xf000, STOP); u.reg_write(UC_X86_REG_ESP, STACK+0xf000)
    captures = []
    def hook(uc, address, size, _):
        if address == STOP: uc.emu_stop()
        elif address == 0x6103d0:
            captures.append((uc.reg_read(UC_X86_REG_EDX), uc.reg_read(UC_X86_REG_ECX)))
            sp = uc.reg_read(UC_X86_REG_ESP); uc.reg_write(UC_X86_REG_EAX, DATA+0x2000)
            uc.reg_write(UC_X86_REG_EIP, get32(uc, sp)); uc.reg_write(UC_X86_REG_ESP, sp+8)
    u.hook_add(UC_HOOK_CODE, hook); u.emu_start(0x6f7010, STOP, count=1000)
    assert captures == [(256, 256)] and get32(u, 0x777030) == DATA+0x2000
    return candidate


class InstallFixture(Fixture):
    """Execute the original TI rebuild/release/power-of-two methods.

    Only the final COM CreateTexture/Release interfaces and the downstream
    Screen preference bootstrap are replaced by controlled native fixtures.
    """
    def __init__(self, image, base, original, failures=0, depth=0):
        super().__init__(image, base)
        p = pefile.PE(data=original)
        for va, count in ((0x6f702a, 10), (0x6108f0, 0x13c),
                          (0x610c0c, 0x5d), (0x611124, 0x75),
                          (0x60a668, 0x1a), (0x40ea64, 0x15), (0x60f7d0, 0xd0)):
            self.u.mem_write(va, original[p.get_offset_from_rva(va-0x400000):][:count])
        self.target, self.renderer = DATA+0x5000, DATA+0x5300
        self.device, self.device_vmt = DATA+0x5500, DATA+0x5600
        self.texture_vmt, self.texture = DATA+0x5800, DATA+0x5900
        self.com_create, self.com_release = DATA+0x1ff10, DATA+0x1ff20
        self.u.mem_write(self.com_create, b'\xc3'); self.u.mem_write(self.com_release, b'\xc3')
        self.failures, self.creates, self.releases, self.bootstrap = failures, [], [], []
        put32(self.u, self.target+8, self.renderer)
        put32(self.u, self.renderer+0x44, self.device)
        put32(self.u, self.renderer+0x1c8, 0)
        put32(self.u, self.device, self.device_vmt)
        put32(self.u, self.device_vmt+0x5c, self.com_create)
        put32(self.u, self.texture, self.texture_vmt)
        put32(self.u, self.texture_vmt+8, self.com_release)
        put32(self.u, self.target+0xc, self.texture)
        for field in (0x20, 0x1c, 0x14, 0x18): put32(self.u, self.target+field, 256)
        self.u.mem_write(self.target+0x60, bytes([1, depth]))
        self.resource_manager, self.resource_list = DATA+0x5c00, DATA+0x5d00
        put32(self.u, self.resource_manager+0x48, self.resource_list)
        put32(self.u, self.resource_list+8, 1)

    def hook(self, u, address, size, _):
        if address == self.com_create:
            sp = u.reg_read(UC_X86_REG_ESP)
            args = struct.unpack('<9I', u.mem_read(sp+4, 36))
            assert args[0] == self.device and args[3:7] == (1, 1, 21, 0) and args[8] == 0
            self.creates.append(args[1:3])
            failed = len(self.creates) <= self.failures
            if not failed: put32(u, args[7], self.texture)
            u.reg_write(UC_X86_REG_EAX, 0x8007000e if failed else 0)
            self.return_(36); return
        if address == self.com_release:
            self.releases.append(get32(u, u.reg_read(UC_X86_REG_ESP)+4))
            u.reg_write(UC_X86_REG_EAX, 0); self.return_(4); return
        if address == self.va(0xc29b00):
            self.bootstrap.append(u.reg_read(UC_X86_REG_EAX))
            self.return_(); return
        if address == 0x4b1dec:
            assert u.reg_read(UC_X86_REG_EAX) == self.resource_list
            assert u.reg_read(UC_X86_REG_EDX) == 0
            u.reg_write(UC_X86_REG_EAX, self.target); self.return_(); return
        if address == 0x4094e4:
            u.reg_write(UC_X86_REG_EAX, 0); self.return_(); return
        super().hook(u, address, size, _)


def verify_installer(candidate, original):
    cases = []
    for base in (0x400000, 0x10400000):
        for depth in (0, 1):
            f = InstallFixture(candidate, base, original, depth=depth)
            original_code = bytes(f.u.mem_read(0x6f702a, 10))
            f.run(q.STARTUP_ENTRY, eax=0x13572468)
            assert f.bootstrap == [0x13572468]
            assert f.creates == [(512, 512)] and len(f.releases) == 1
            assert get32(f.u, f.va(q.IMAGE_BASE+q.STATE)) == 1
            assert get32(f.u, 0x777030) == f.target
            assert bytes(f.u.mem_read(f.target+0x60, 2)) == bytes([1, depth])
            assert [get32(f.u, f.target+x) for x in (0x20, 0x1c, 0x14, 0x18)] == [512]*4
            assert bytes(f.u.mem_read(0x6f702a, 10)) == original_code
            f.run(q.INSTALL_ENTRY)
            assert f.creates == [(512, 512)] and len(f.releases) == 1
            # Execute the original resource manager's OnReset loop. Its
            # requested dimensions carry the startup upgrade into later
            # native device resets, without changing the factory operands.
            f.run(0x60f7d0-base+0x400000, eax=f.resource_manager)
            assert f.creates == [(512, 512), (512, 512)]
            assert [get32(f.u, f.target+x) for x in (0x20, 0x1c, 0x14, 0x18)] == [512]*4
            cases.append(dict(base=hex(base), existing_target_native_rebuild512=True,
                              disk_and_runtime_code_unchanged=True, idempotent=True,
                              executed_native_OnReset_keeps512=True, depth=depth))
        for failures in (1, 2):
            f = InstallFixture(candidate, base, original, failures=failures, depth=1)
            f.run(q.INSTALL_ENTRY)
            assert f.creates == [(512, 512), (256, 256)]
            assert get32(f.u, f.va(q.IMAGE_BASE+q.STATE)) == 0xffffffff
            assert get32(f.u, f.va(q.IMAGE_BASE+q.STATE)+4) == failures+1
            assert get32(f.u, 0x777030) == f.target and bytes(f.u.mem_read(f.target+0x61, 1)) == b'\1'
            assert [get32(f.u, f.target+x) for x in (0x20, 0x1c, 0x14, 0x18)] == [256 if failures == 1 else 0]*4
            cases.append(dict(base=hex(base), allocation_failures=failures, native_rollback256=failures == 1,
                              rollback_failure_reported=failures == 2))
        for guard in ('code', 'creator', 'missing', 'owner', 'device', 'inactive', 'resource', 'owned_depth', 'size'):
            f = InstallFixture(candidate, base, original)
            if guard == 'code': f.u.mem_write(0x6108f0, b'\x90')
            elif guard == 'creator': f.u.mem_write(0x6f702c, b'\x02')
            elif guard == 'missing': put32(f.u, 0x777030, 0)
            elif guard == 'owner': put32(f.u, f.target+8, 0)
            elif guard == 'device': put32(f.u, f.renderer+0x44, 0)
            elif guard == 'inactive': f.u.mem_write(f.target+0x60, b'\0')
            elif guard == 'resource': put32(f.u, f.target+0xc, 0)
            elif guard == 'owned_depth': put32(f.u, f.target+0x10, f.texture)
            elif guard == 'size': put32(f.u, f.target+0x20, 1024)
            before = bytes(f.u.mem_read(f.target, 0x68))
            f.run(q.INSTALL_ENTRY)
            assert f.creates == [] and f.releases == []
            assert bytes(f.u.mem_read(f.target, 0x68)) == before
            assert get32(f.u, f.va(q.IMAGE_BASE+q.STATE)+4) == 1
            cases.append(dict(base=hex(base), rejected_guard=guard, target_unchanged=True))
        f = InstallFixture(candidate, base, original)
        for field in (0x20, 0x1c, 0x14, 0x18): put32(f.u, f.target+field, 512)
        f.run(q.INSTALL_ENTRY)
        assert f.creates == [] and f.releases == [] and get32(f.u, f.va(q.IMAGE_BASE+q.STATE)) == 1
        cases.append(dict(base=hex(base), preexisting512_preserved=True))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver', type=Path, default=ROOT/'reports/screen-settings/client/silver.dll')
    parser.add_argument('--ti', type=Path, default=ROOT/'reports/ui-modernization/baseline/ti.exe')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/portrait-quality/native-proof.json')
    args = parser.parse_args()
    candidate, padded = fixture_image(args.silver.read_bytes())
    ti = verify_ti(args.ti.read_bytes()); cases = verify_installer(candidate, ti)
    cases += verify_native_input(candidate)
    for base in (0x400000, 0x10400000):
        for width, height in ((2560, 1440), (2048, 1152), (1706, 960), (1280, 720), (960, 540), (640, 480), (512, 384)):
            f = Fixture(candidate, base, width, height)
            before = bytes(f.u.mem_read(f.original, 0x400))
            f.run(q.MOUSE_ENTRY, f.original, 1, 100, (100,))
            root = f.names['window_portrait_preview']; control = f.children[root][-1]
            assert bytes(f.u.mem_read(f.original, 0x400)) == before
            assert f.calls.count('create_window') == f.calls.count('create_portrait') == 1
            assert f.u.mem_read(root+0x49, 1) == b'\1'
            side = get32(f.u, control+0x38)
            assert 244 <= side <= 488 and side == get32(f.u, control+0x3c)
            assert get32(f.u, root+0x30)+get32(f.u, root+0x38) <= width
            assert get32(f.u, root+0x34)+get32(f.u, root+0x3c) <= height
            close=get32(f.u,root+0x344)
            assert get32(f.u,close+0x38)==64 and get32(f.u,close+0x34)==16
            assert get32(f.u,close+0x30)==max(0,get32(f.u,root+0x38)-64-16)
            assert get32(f.u,close+0x30)+64 <= get32(f.u,root+0x38)
            assert get32(f.u,root+0x68)!=f.va(q.IMAGE_BASE+q.WINDOW_NAME+12)
            closure = DATA+0x4000; put32(f.u, closure+0xc, control)
            x, y = 500, 420
            f.run(q.DRAW_ENTRY, x, y, edi=closure)
            quad = f.quads[-1]
            assert quad['texture'] == DATA+0x5000
            assert quad['reversed_xy'] == (y+side/2, x-side/2, y+side/2, x+side/2,
                                           y-side/2, x+side/2, y-side/2, x-side/2)
            assert quad['args'] == (0, 0, 0, 0xffffffff, 0xffffffff)
            assert f.states == [3, 0]
            f.run(q.MOUSE_ENTRY, control, 1, 100, (100,))
            assert f.u.mem_read(root+0x49, 1) == b'\0'
            f.run(q.MOUSE_ENTRY, f.original, 1, 100, (100,))
            assert f.calls.count('create_window') == 1 and f.u.mem_read(root+0x49, 1) == b'\1'
            f.run(f.close_callback-base+0x400000)
            assert f.u.mem_read(root+0x49, 1) == b'\0'
            cases.append(dict(base=hex(base), logical_screen=[width, height], preview_side=side,
                              created_once=True, right_click_close=True, native_close_callback=True))
        f = Fixture(candidate, base)
        f.run(q.MOUSE_ENTRY, f.original, 0, 100, (100,))
        assert not f.windows and f.u.mem_read(f.original+0x2e0, 1) == b'\1'
        assert get32(f.u, f.original+0x2e4) == 99
        cases.append(dict(base=hex(base), original_left_drag=True))
        f = Fixture(candidate, base); put32(f.u, f.original+0x17c, 0)
        f.run(q.MOUSE_ENTRY, f.original, 1, 100, (100,))
        assert not f.windows
        cases.append(dict(base=hex(base), absent_manager_noop=True))
        f = Fixture(candidate, base); closure = DATA+0x4000; put32(f.u, closure+0xc, f.original)
        f.run(q.DRAW_ENTRY, 100, 120, edi=closure)
        assert f.calls == [('normal_draw', 100, 120)] and not f.quads
        cases.append(dict(base=hex(base), ordinary_portrait_original_draw=True))
        for kind in ('char', 'shop'):
            for hover_kind, point, visible, expected, button in tuple(
                    (h, p, v, e, b) for b in (1, 0x101) for h, p, v, e in (
                    ('self', (184, 150), True, True), ('parent', (184, 230), True, True),
                    ('none', (184, 230), True, True), ('sibling', (184, 230), True, False),
                    ('self', (305, 230), True, False), ('self', (184, 255), True, False),
                    ('self', (184, 230), False, False))) + (
                    ('self', (184, 150), True, True, 0x201),
                    ('self', (184, 150), True, True, 0x1001)):
                f = Fixture(candidate, base)
                parent, sibling = DATA+0x3000, DATA+0x3800
                put32(f.u, parent, f.window_vmt); put32(f.u, parent+0x4c, 0)
                f.u.mem_write(parent+0x30, struct.pack('<4I', 20, 30, 512, 512))
                f.u.mem_write(parent+0x49, bytes([visible]))
                f.u.mem_write(f.original+0x30, struct.pack('<4I', 100, 100, 128, 64))
                f.u.mem_write(f.original+0x49, b'\1')
                if kind == 'shop':
                    put32(f.u, f.original, get32(f.u, f.va(0xa2c1b0)))
                    put32(f.u, f.original+0x68, f.clone_name(f.va(0x8d5acc)))
                else:
                    put32(f.u, f.original+0x68, 0)
                f.children[parent] = [f.original]
                f.children[sibling] = []
                put32(f.u, f.manager+0x280, DATA+0x500)
                put32(f.u, DATA+0x500+4, DATA+0x600)
                put32(f.u, DATA+0x500+8, 1); put32(f.u, DATA+0x600, parent)
                hovered = {'self':f.original, 'parent':parent, 'none':0, 'sibling':sibling}[hover_kind]
                put32(f.u, f.manager+0x2d4, hovered)
                before = bytes(f.u.mem_read(f.original, 0x400))
                f.run(0x9f484c, stack=(button, *point))
                assert bool(f.windows) == expected
                assert ('native_mouse_fallback' in f.calls) != expected
                assert bytes(f.u.mem_read(f.original, 0x400)) == before
                cases.append(dict(base=hex(base), city_render_area_kind=kind, hover=hover_kind,
                                  click=list(point), button=button, visible=visible, preview_opened=expected,
                                  native_input_preserved=not expected,
                                  feet_outside_original_hit=point == (184, 230)))
        for button in (0, 2, 0x100, 0x102):
            f = Fixture(candidate, base)
            f.run(0x9f484c, stack=(button, 100, 120))
            assert f.calls == ['native_mouse_fallback']
            cases.append(dict(base=hex(base), native_other_button_preserved=button))
        # Nil/short managed names guard before reading any character, including
        # a string pointer directly at an unmapped page boundary.
        for name,length in (('window_portrait_preview',23),('window_portrait_previeX',23),
                            ('Xindow_portrait_preview',23),('window_portrait_previe',22),
                            ('window_portrait_previewX',24),('',0)):
            f=Fixture(candidate,base);block=DATA+0x1f000;actual=block+12
            f.u.mem_write(block,struct.pack('<HHiI',1200,2,1,len(name))+name.encode('utf-16le')+b'\0\0')
            f.run(q.NAME_EQUAL_ENTRY,actual,f.va(q.IMAGE_BASE+q.WINDOW_NAME+12),23)
            assert f.u.reg_read(UC_X86_REG_EAX)==int(name=='window_portrait_preview')
            cases.append(dict(base=hex(base),bounded_name_compare=name,exact_length=length))
        for count in (0,1,22,24):
            f=Fixture(candidate,base);pointer=DATA+0x20000
            put32(f.u,pointer-4,count)
            f.run(q.NAME_EQUAL_ENTRY,pointer,f.va(q.IMAGE_BASE+q.WINDOW_NAME+12),23)
            assert f.u.reg_read(UC_X86_REG_EAX)==0
            cases.append(dict(base=hex(base),wrong_length_page_boundary_no_character_read=count))
        f=Fixture(candidate,base)
        f.run(q.NAME_EQUAL_ENTRY,0,f.va(q.IMAGE_BASE+q.WINDOW_NAME+12),23)
        assert f.u.reg_read(UC_X86_REG_EAX)==0
        cases.append(dict(base=hex(base),nil_name_guard=True))
        f=Fixture(candidate,base)
        f.run(q.MOUSE_ENTRY,f.original,1,100,(100,))
        root=f.names['window_portrait_preview'];control=f.children[root][-1]
        side=get32(f.u,control+0x38)
        px=get32(f.u,root+0x30)+get32(f.u,control+0x30)+side-4
        py=get32(f.u,root+0x34)+get32(f.u,control+0x34)+side-4
        put32(f.u,f.manager+0x2d4,control)
        f.run(q.WALK_ENTRY,control,px,py,(0,))
        assert f.u.reg_read(UC_X86_REG_EAX)==control
        cases.append(dict(base=hex(base),cloned_preview_name_expanded_feet_bounds=True))
        for name in ('shopcha','shopcharX','Xhopchar','shopchaX',''):
            f=Fixture(candidate,base)
            parent=DATA+0x3000
            put32(f.u,parent+0x4c,0)
            f.u.mem_write(parent+0x30,struct.pack('<4I',20,30,512,512))
            f.u.mem_write(f.original+0x30,struct.pack('<4I',100,100,128,64))
            f.u.mem_write(f.original+0x49,b'\1')
            put32(f.u,f.original,get32(f.u,f.va(0xa2c1b0)))
            block=DATA+0x1f000
            f.u.mem_write(block,struct.pack('<HHiI',1200,2,1,len(name))+name.encode('utf-16le')+b'\0\0')
            put32(f.u,f.original+0x68,block+12)
            put32(f.u,f.manager+0x2d4,0)
            f.run(q.WALK_ENTRY,f.original,184,150,(0,))
            assert f.u.reg_read(UC_X86_REG_EAX)==0
            cases.append(dict(base=hex(base),unrelated_shop_name_keeps_native=name))
    report = dict(status='PASS', cases=len(cases)+3, native_fixture_cases=cases,
                  ti_candidate_sha256=q.sha(ti), silver_candidate_sha256=q.sha(candidate),
                  fixture_only_padding=padded, projection_unchanged=True, normal_244_unchanged=True,
                  executed_original_native_target_creation_256=True,
                  executed_existing_target_native_rebuild_512_and_rollback=True,
                  native_rebuild_release_and_power2_methods_executed=True,
                  executed_native_resource_manager_OnReset_keeps512=True,
                  on_disk_TI_unchanged=True, runtime_executable_changed_bytes=0,
                  aslr_bases=[hex(x) for x in (0x400000, 0x10400000)],
                  executed_native_frame_quantization_and_centering=True,
                  native_static_names_cloned_in_fixtures=True,
                  bounded_UnicodeString_content_name_checks=True,
                  actual64wide_close_button_inside_window=True,
                  executed_native_hit_recursion_MouseDown_Update_and_arrows=True,
                  native_gui_constructors_and_COM_are_stubs=True, graphical_validation=False, published=False)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'native_fixture_cases'}, indent=2))


if __name__ == '__main__': main()
