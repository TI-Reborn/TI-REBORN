"""Execute Screen snapshot/Apply x86 hooks with explicit native UI/D3D stubs.

This checks hook control flow, rollback, ABI preservation and PIC addressing.
It does not launch a client, attach to a game or validate Direct3D rendering.
The preferred-base case overlays synthetic TI stubs because both binaries have
the same preferred image base; real TI stays fixed at 0x400000 in the relocated
Silver case. Host device methods are deliberately represented only by stubs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
    UC_X86_REG_EIP, UC_X86_REG_EFLAGS,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_screen_settings as screen
from deploy import client_screen_resolution_ui as resolution_ui

DATA = 0x30000000
STACK = 0x31000000
FORM = DATA + 0x1000
RENDERER = DATA + 0x2000
FRAME = STACK + 0xc000
REGISTERS = (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP,
)
BASE_VALUES = (0x11111111, 0x22222222, 0x33333333, 0x44444444,
               0x55555555, 0x66666666, FRAME)


def put32(u: Uc, address: int, value: int):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get32(u: Uc, address: int) -> int:
    return struct.unpack('<I', u.mem_read(address, 4))[0]


def screen_values(values: tuple) -> tuple:
    return values+(0,) if len(values) == 4 else values


class Fixture:
    def __init__(self, image: bytes, base: int, old: tuple, *, reset_failures=(),
                 unavailable: str | None = None, target_states=('missing_ref', 'missing_ref'),
                 resource_failures=()):
        old = screen_values(old)
        self.base = base
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        if base != 0x400000:
            self.u.mem_map(0x400000, 0x400000)
        image_size = (len(image)+0xfff) & ~0xfff
        self.u.mem_map(base, image_size)
        self.u.mem_write(base, image)
        self.u.mem_map(DATA, 0x10000)
        self.u.mem_map(STACK, 0x10000)
        self.u.mem_map(0, 0x1000)
        self.cvars = dict(zip(screen.CVARS, old))
        self.old = old
        self.calls = []
        self.commands = []
        self.dialogs = []
        self.allocated = {}
        self.freed = []
        self.next_string = DATA + 0x4000
        self.reset_failures = list(reset_failures)
        self.resource_failures = list(resource_failures)
        self.reset_count = 0
        self.apply_entries = 0
        self.snapshot_entries = 0
        self.exit_address = None
        self.post_command_registers = None
        self.post_command_flags = None
        self.exclusive = []
        self.vsync_values = []
        self.device_windows = []
        self.resize_events = []
        self.ui_resize_events = []
        self.chat_resize_events = []
        self.target_events = []
        self.targets = []
        self.lost_before_reset = []
        self.current_size = old[2:4]
        self.constant_strings = bytes(self.u.mem_read(base+screen.STRINGS, 0x300))
        # This compact managed literal occupies 32 bytes; target snapshot state
        # starts at STATE+0x70 beyond it, within the former 64-byte padding.
        self.constant_vsync_prefix = bytes(self.u.mem_read(base+screen.VSYNC_PREFIX, 0x20))
        self.u.mem_write(RENDERER+0x2d3, bytes([old[4]]))
        old_square = 512
        while old_square < max(old[2:4]):
            old_square *= 2
        self.old_square = old_square
        put32(self.u, RENDERER+0x1c0, DATA+0x700)
        put32(self.u, RENDERER+0x2dc, old_square)
        put32(self.u, RENDERER+0x2e0, old_square)
        assert len(target_states) == len(screen.TARGETS)
        for index, ((reference, _), state) in enumerate(zip(screen.TARGETS, target_states)):
            assert state in ('missing_ref', 'missing_object', 'inactive', 'active')
            slot, obj = DATA+0x300+index*4, DATA+0x6000+index*0x400
            put32(self.u, reference, 0 if state == 'missing_ref' else slot)
            put32(self.u, slot, 0 if state == 'missing_object' else obj)
            if state in ('active', 'inactive'):
                self.targets.append((index, obj, state))
                for offset in (0x14, 0x18, 0x1c, 0x20):
                    put32(self.u, obj+offset, old_square)
                put32(self.u, obj+0xc, DATA+0x800+index*4 if state == 'active' else 0)
                self.u.mem_write(obj+0x60, bytes([state == 'active']))
        self.u.mem_write(0x746470, bytes.fromhex('558bec83'))
        put32(self.u, 0x76e568, DATA+0x100)
        put32(self.u, DATA+0x100, FORM)
        put32(self.u, 0x76de0c, DATA+0x104)
        put32(self.u, DATA+0x104, RENDERER)
        if unavailable == 'host_guard':
            self.u.mem_write(0x746470, b'\0\0\0\0')
        elif unavailable == 'form_ref':
            put32(self.u, 0x76e568, 0)
        elif unavailable == 'form_object':
            put32(self.u, DATA+0x100, 0)
        elif unavailable == 'renderer_ref':
            put32(self.u, 0x76de0c, 0)
        elif unavailable == 'renderer_object':
            put32(self.u, DATA+0x104, 0)
        self.set_registers()
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def address(self, preferred_va: int) -> int:
        return self.base + preferred_va - 0x400000

    def set_registers(self):
        for register, value in zip(REGISTERS, BASE_VALUES):
            self.u.reg_write(register, value)
        self.u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
        self.u.reg_write(UC_X86_REG_EFLAGS, 0x246)

    def return_stub(self, clean: int = 0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, get32(self.u, sp))
        self.u.reg_write(UC_X86_REG_ESP, sp+4+clean)

    def clobber_volatile(self):
        self.u.reg_write(UC_X86_REG_EAX, 0xa0a0a0a0)
        self.u.reg_write(UC_X86_REG_ECX, 0xc0c0c0c0)
        self.u.reg_write(UC_X86_REG_EDX, 0xd0d0d0d0)
        self.u.reg_write(UC_X86_REG_EFLAGS, 0x202)

    def text(self, pointer: int) -> str:
        if not pointer:
            return ''
        length = get32(self.u, pointer-4)
        if length > 1000:
            raise AssertionError(f'Invalid managed UTF16 string length {length}')
        return bytes(self.u.mem_read(pointer, length*2)).decode('utf-16le')

    def allocate(self, value: str) -> int:
        encoded = value.encode('utf-16le')
        start = self.next_string
        self.next_string += (12+len(encoded)+2+3) & ~3
        self.u.mem_write(start, struct.pack('<HHiI', 1200, 2, 1, len(value))+encoded+b'\0\0')
        pointer = start+12
        self.allocated[pointer] = value
        return pointer

    def hook(self, u: Uc, address: int, size: int, _):
        if address == self.address(screen.APPLY_ENTRY):
            self.apply_entries += 1
            if self.apply_entries > 1:
                raise AssertionError('Failure re-entered Apply instead of exiting')
        if address == self.address(screen.SNAPSHOT_ENTRY):
            self.snapshot_entries += 1
            if self.snapshot_entries > 1:
                raise AssertionError('Failure re-entered snapshot instead of exiting')
        if self.exit_address == address:
            u.emu_stop()
            return
        va = address-self.base+0x400000
        if va == 0x688328:
            name = self.text(u.reg_read(UC_X86_REG_EAX))
            assert name in screen.CVARS, name
            self.calls.append(('cvar_read', name))
            self.clobber_volatile()
            u.reg_write(UC_X86_REG_EAX, self.cvars[name])
            self.return_stub()
        elif va == 0x6882a4:
            command = self.text(u.reg_read(UC_X86_REG_EAX))
            name, value = command.split(' ', 1)
            assert name in screen.CVARS, command
            self.cvars[name] = int(value)
            self.commands.append(command)
            self.clobber_volatile()
            if self.post_command_registers is None:
                self.post_command_registers = tuple(u.reg_read(r) for r in REGISTERS)
                self.post_command_flags = u.reg_read(UC_X86_REG_EFLAGS)
            self.return_stub()
        elif va == 0x4244b4:
            pointer = self.allocate(str(struct.unpack('<i', struct.pack('<I', u.reg_read(UC_X86_REG_EAX)))[0]))
            put32(u, u.reg_read(UC_X86_REG_EDX), pointer)
            self.clobber_volatile()
            self.return_stub()
        elif va == 0x40c1bc:
            destination = u.reg_read(UC_X86_REG_EAX)
            combined = self.text(u.reg_read(UC_X86_REG_EDX))+self.text(u.reg_read(UC_X86_REG_ECX))
            put32(u, destination, self.allocate(combined))
            self.clobber_volatile()
            self.return_stub()
        elif va == 0x40b09c:
            slot = u.reg_read(UC_X86_REG_EAX)
            pointer = get32(u, slot)
            assert pointer in self.allocated and pointer not in self.freed, pointer
            self.freed.append(pointer)
            put32(u, slot, 0)
            self.clobber_volatile()
            self.return_stub()
        elif va in (0x6675e0, 0x6d4190, 0x6d4090):
            # Localization and native message-box construction are explicit
            # stubs. Their count is evidence only of the called failure path.
            if va == 0x6d4190:
                self.dialogs.append(dict(title=self.text(u.reg_read(UC_X86_REG_EDX)),
                                         message=self.text(u.reg_read(UC_X86_REG_EAX))))
            else:
                self.dialogs.append(hex(va))
            if va == 0x6675e0:
                put32(u, u.reg_read(UC_X86_REG_EDX), 0)
            self.clobber_volatile()
            self.return_stub()
        elif va == 0x9f47f8:
            # SILVER_Resize is stdcall, unlike the guarded TI wrapper. Capture
            # the actual stacked arguments and verify its RET8 contract.
            assert u.reg_read(UC_X86_REG_EBX) == self.base
            sp = u.reg_read(UC_X86_REG_ESP)
            dimensions = get32(u, sp+4), get32(u, sp+8)
            assert dimensions == (get32(u, 0x787270), get32(u, 0x787274))
            assert self.reset_count > 0 and not u.mem_read(RENDERER+0x2a9, 1)[0]
            self.ui_resize_events.append(dimensions)
            self.clobber_volatile()
            self.return_stub(8)
        elif va == 0xa029dc:
            # Native chat refresh is a no-argument Silver call. Its real child
            # sizing is validated separately; the hook must call it only after
            # successful device/resource restore and own Silver_Resize.
            assert u.reg_read(UC_X86_REG_EBX) == self.base
            assert self.ui_resize_events and not u.mem_read(RENDERER+0x2a9, 1)[0]
            self.chat_resize_events.append(self.ui_resize_events[-1])
            self.clobber_volatile()
            self.return_stub()
        elif address == 0x721a24:
            raise AssertionError('TI guarded Resize wrapper silently skips during MouseUp')
        elif address in (0x5b1250, 0x5b0208, 0x5b0234, 0x746470,
                         0x5eb048, 0x64b290, 0x64b2d4, 0x64ade8):
            self.host_stub(address)

    def host_stub(self, address: int):
        u = self.u
        eax, edx, ecx = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        assert u.reg_read(UC_X86_REG_EBX) == self.base, 'PIC EBX changed before native host call'
        self.calls.append(('host', hex(address), eax, edx, ecx))
        result = None
        if address == 0x5b1250:
            assert eax == FORM and edx & 0xff == 2
        elif address == 0x5b0208:
            assert eax == FORM
            self.current_size = (edx, self.current_size[1])
        elif address == 0x5b0234:
            assert eax == FORM
            self.current_size = (self.current_size[0], edx)
        elif address == 0x746470:
            assert eax == FORM
            mode = u.mem_read(FORM+0x3d0, 1)[0]
            monitor = u.mem_read(FORM+0x3d1, 1)[0]
            # Desktop uses the work area; LCD fullscreen uses the full monitor.
            # These observed fixture sizes include a 48-pixel taskbar.
            dimensions = ((2560,1392) if mode == 2 else (2560,1440)
                          if mode == 1 and monitor > 0 else self.current_size)
            put32(u, 0x787270, dimensions[0])
            put32(u, 0x787274, dimensions[1])
        elif address == 0x5eb048:
            assert eax == FORM
            result = 0x12340000+self.reset_count
        elif address == 0x64b290:
            assert eax == RENDERER and edx == get32(u, 0x787270)
            self.renderer_width = edx
            put32(u, RENDERER+0x2dc, max(get32(u, RENDERER+0x2dc), edx))
        elif address == 0x64b2d4:
            assert eax == RENDERER and edx == get32(u, 0x787274)
            self.renderer_height = edx
            put32(u, RENDERER+0x2e0, max(get32(u, RENDERER+0x2e0), edx))
        elif address == 0x64ade8:
            assert eax == RENDERER
            self.reset_count += 1
            if self.reset_count > 2:
                raise AssertionError('Display rollback loops through more than two resets')
            self.exclusive.append(u.mem_read(RENDERER+0x2d7, 1)[0])
            self.vsync_values.append(u.mem_read(RENDERER+0x2d3, 1)[0])
            self.lost_before_reset.append(u.mem_read(RENDERER+0x2a9, 1)[0])
            self.device_windows.append(get32(u, RENDERER+0x1fc))
            self.resize_events.append((self.renderer_width, self.renderer_height))
            failure = self.reset_failures.pop(0) if self.reset_failures else False
            resource_failure = self.resource_failures.pop(0) if self.resource_failures else None
            event = dict(depth=[get32(u, RENDERER+0x2dc), get32(u, RENDERER+0x2e0)],
                         requested=[], reset_failed=bool(failure), resource_failure=resource_failure)
            put32(u, RENDERER+0x1c0, 0 if failure or resource_failure == 'depth' else DATA+0x700)
            for index, obj, state in self.targets:
                requested = (get32(u, obj+0x20), get32(u, obj+0x1c))
                event['requested'].append(dict(index=index, state=state, dimensions=list(requested)))
                if state != 'active':
                    continue
                active = not failure and resource_failure != f'target{index}_inactive'
                self.u.mem_write(obj+0x60, bytes([active]))
                put32(u, obj+0xc, 0 if failure or resource_failure == f'target{index}_texture' else DATA+0x800+index*4)
                for offset, dimension in ((0x14, requested[0]), (0x18, requested[1])):
                    put32(u, obj+offset, dimension-1 if resource_failure == f'target{index}_short' else dimension)
            self.target_events.append(event)
            u.mem_write(RENDERER+0x2a9, bytes([bool(failure)]))
            result = 0x8876086c if failure else 0
        self.clobber_volatile()
        if result is not None:
            u.reg_write(UC_X86_REG_EAX, result)
        self.return_stub()

    def snapshot(self):
        self.set_registers()
        put32(self.u, FRAME-8, self.old[0])
        self.exit_address = self.address(0x88384a)
        # Start at the removed popup's hook too: a surviving HIGHLOW relocation
        # there would corrupt the jump in the relocated Silver fixture.
        self.u.emu_start(self.address(0x883816), self.exit_address, count=10000)
        assert self.u.reg_read(UC_X86_REG_EIP) == self.exit_address
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK+0x8000
        assert tuple(get32(self.u, self.base+screen.STATE+offset) for offset in screen.OLD_OFFSETS) == self.old
        actual = tuple(self.u.reg_read(r) for r in REGISTERS)
        expected = list(BASE_VALUES)
        expected[0] = self.old[0]
        expected[3] = FRAME-0x20
        assert actual == tuple(expected), (actual, expected)
        assert self.u.reg_read(UC_X86_REG_EFLAGS) == 0x246

    def apply(self, target: tuple):
        target = screen_values(target)
        self.set_registers()
        self.cvars.update(dict(zip(screen.CVARS, target)))
        final_command = self.allocate(f'r_height {target[3]}')
        # This managed string belongs to the original outer Apply callback;
        # only the independent strings created for rollback must be freed here.
        self.u.reg_write(UC_X86_REG_EAX, final_command)
        self.exit_address = self.address(0x883930)
        self.u.emu_start(self.address(0x883924), self.exit_address, count=30000)
        assert self.u.reg_read(UC_X86_REG_EIP) == self.exit_address, 'Apply did not return to native cleanup'
        assert self.apply_entries == 1 and self.snapshot_entries == 1
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK+0x8000
        assert tuple(self.u.reg_read(r) for r in REGISTERS) == self.post_command_registers
        assert self.u.reg_read(UC_X86_REG_EFLAGS) == self.post_command_flags
        assert self.text(final_command) == f'r_height {target[3]}'
        assert final_command not in self.freed
        assert set(self.allocated)-set(self.freed) == {final_command}, 'Rollback managed strings leaked'
        assert bytes(self.u.mem_read(self.base+screen.STRINGS, 0x300)) == self.constant_strings
        assert bytes(self.u.mem_read(self.base+screen.VSYNC_PREFIX, 0x20)) == self.constant_vsync_prefix
        return get32(self.u, self.base+screen.STATE+0x30)


def verify_native_resize(images: dict[int, bytes]) -> list[dict]:
    """Execute the real Silver resize export, manager and list getters.

    Synthetic live objects contain either no manager, an empty manager or two
    child windows. No native code in this path dispatches an event or destroys
    a child. This also verifies the export's stack order and eight-byte cleanup.
    """
    cases = []
    for base, image in images.items():
        address = lambda va: base+va-0x400000
        for width, height in ((800, 600), (1920, 1080), (3440, 1440)):
            for manager_kind in ('absent', 'empty', 'children'):
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(base, (len(image)+0xfff) & ~0xfff)
                u.mem_write(base, image)
                u.mem_map(DATA, 0x10000)
                u.mem_map(STACK, 0x10000)
                put32(u, address(0xac56e0), DATA+0x100)
                put32(u, address(0xac5e60), DATA+0x104)
                put32(u, address(0xac5a4c), DATA+0x500)
                put32(u, address(0xb76650), 0 if manager_kind == 'absent' else FORM)
                if manager_kind != 'absent':
                    put32(u, FORM+0x280, DATA+0x2000)
                    put32(u, DATA+0x2000+8, 2 if manager_kind == 'children' else 0)
                    put32(u, DATA+0x2000+4, DATA+0x2100)
                if manager_kind == 'children':
                    for index in range(2):
                        window = DATA+0x3000+index*0x400
                        put32(u, DATA+0x2100+index*4, window)
                        put32(u, window+0x30, width+100 if index == 0 else 100)
                        put32(u, window+0x34, height+100 if index == 0 else 100)
                for register, value in zip(REGISTERS, BASE_VALUES):
                    u.reg_write(register, value)
                sp, sentinel = STACK+0x8000, DATA+0xf000
                put32(u, sp, sentinel)
                put32(u, sp+4, width)
                put32(u, sp+8, height)
                u.reg_write(UC_X86_REG_ESP, sp)
                u.emu_start(address(0x9f47f8), sentinel, count=1000)
                assert u.reg_read(UC_X86_REG_EIP) == sentinel
                assert u.reg_read(UC_X86_REG_ESP) == sp+12
                for register, value in zip(REGISTERS, BASE_VALUES):
                    if register in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
                        assert u.reg_read(register) == value
                assert (get32(u, DATA+0x100), get32(u, DATA+0x104)) == (width, height)
                viewport = tuple(get32(u, DATA+0x500+i*4) for i in range(4))
                assert viewport == (144, 42, width-42, height-206)
                if manager_kind != 'absent':
                    assert (get32(u, FORM+0x29c), get32(u, FORM+0x2a0)) == (width, height)
                if manager_kind == 'children':
                    assert (get32(u, DATA+0x3000+0x30), get32(u, DATA+0x3000+0x34)) == (width-64, height-24)
                    assert (get32(u, DATA+0x3400+0x30), get32(u, DATA+0x3400+0x34)) == (100, 100)
                    assert get32(u, DATA+0x2000+8) == 2
                cases.append(dict(kind='native_silver_resize', base=hex(base),
                                  dimensions=[width, height], manager=manager_kind,
                                  viewport=list(viewport), cleanup_bytes=8,
                                  callee_registers_preserved=True))
    return cases


def verify_screen_targets(images: dict[int, bytes]) -> list[dict]:
    """Exercise injected target/depth lifecycle with explicit Reset stubs.

    This validates the machine code's field updates and allocation-failure
    branches. Actual COM surfaces and native frame rendering need owned-client
    graphical evidence; no synthetic Reset here establishes those facts.
    """
    cases = []
    states = ('missing_ref', 'missing_object', 'inactive', 'active')
    old = (2, 0, 1024, 768, 0)
    target = (2, 0, 1920, 1080, 0)

    def target_fields(fixture):
        return [dict(index=index, state=state, logical=[get32(fixture.u, obj+0x20), get32(fixture.u, obj+0x1c)],
                     actual=[get32(fixture.u, obj+0x14), get32(fixture.u, obj+0x18)],
                     active=fixture.u.mem_read(obj+0x60, 1)[0], texture=get32(fixture.u, obj+0xc))
                for index, obj, state in fixture.targets]

    for base, image in images.items():
        for world in states:
            for bloom in states:
                fixture = Fixture(image, base, old, target_states=(world, bloom))
                fixture.snapshot()
                status = fixture.apply(target)
                assert status == 1 and fixture.reset_count == 1
                for row in target_fields(fixture):
                    assert row['logical'] == ([2048, 2048] if row['state'] == 'active' else [1024, 1024])
                    assert row['actual'] == row['logical']
                    assert row['active'] == int(row['state'] == 'active')
                assert fixture.target_events[0]['depth'] == [2048, 2048]
                assert fixture.chat_resize_events == fixture.ui_resize_events == [target[2:4]]
                cases.append(dict(kind='screen_target_presence', base=hex(base), world=world, bloom=bloom,
                                  status=status, resets=1, depth=fixture.target_events[0]['depth'],
                                  targets=target_fields(fixture), chat_refreshes=1))

                fixture = Fixture(image, base, old, target_states=(world, bloom))
                original = target_fields(fixture)
                fixture.snapshot()
                assert fixture.apply(old) == 1 and fixture.reset_count == 0
                assert target_fields(fixture) == original
                assert (get32(fixture.u, RENDERER+0x2dc), get32(fixture.u, RENDERER+0x2e0)) == (1024, 1024)
                assert not fixture.target_events and not fixture.chat_resize_events
                cases.append(dict(kind='screen_targets_unchanged', base=hex(base), world=world, bloom=bloom,
                                  resets=0, target_and_depth_fields_unchanged=True))

        for width, height, mode, expected in ((1920,1080,0,2048), (2560,1440,0,4096),
                                             (3440,1440,0,4096), (3840,2160,0,4096),
                                             (1024,768,2,4096)):
            fixture = Fixture(image, base, old, target_states=('active', 'active'))
            fixture.snapshot()
            requested = (2, mode, width, height, 0)
            assert fixture.apply(requested) == 1 and fixture.reset_count == 1
            assert fixture.target_events[0]['depth'] == [expected, expected]
            assert all(row['logical'] == row['actual'] == [expected, expected] for row in target_fields(fixture))
            cases.append(dict(kind='screen_targets_modern_size', base=hex(base), requested=[width,height],
                              mode=mode, actual=fixture.resize_events[0], square_target=expected,
                              depth=fixture.target_events[0]['depth']))

        failures = ('depth', 'target0_texture', 'target0_short', 'target0_inactive',
                    'target1_texture', 'target1_short', 'target1_inactive')
        for failure in failures:
            for rollback_failure in (None, 'depth', 'target0_texture', 'target1_short'):
                fixture = Fixture(image, base, old, target_states=('active', 'active'),
                                  resource_failures=(failure, rollback_failure))
                fixture.snapshot()
                status = fixture.apply(target)
                assert status == (2 if rollback_failure is None else 4) and fixture.reset_count == 2
                assert tuple(fixture.cvars[name] for name in screen.CVARS) == old
                assert fixture.target_events[0]['depth'] == [2048,2048]
                assert fixture.target_events[1]['depth'] == [1024,1024]
                assert fixture.lost_before_reset == [0,0], 'S_OK resource failure must notify OnLostDevice again'
                assert get32(fixture.u, base+screen.STATE+0x34) == get32(fixture.u, base+screen.STATE+0x38) == 0
                assert fixture.chat_resize_events == fixture.ui_resize_events == ([] if rollback_failure else [old[2:4]])
                for row in target_fields(fixture):
                    assert row['logical'] == [1024,1024]
                cases.append(dict(kind='screen_target_resource_failure', base=hex(base), failure=failure,
                                  rollback_failure=rollback_failure, status=status, resets=2,
                                  lost_before_reset=fixture.lost_before_reset,
                                  reset_hresults=[0,0], requested_targets_at_reset=fixture.target_events,
                                  chat_refreshes=len(fixture.chat_resize_events)))

        for reset_failures in ((True,False), (True,True)):
            fixture = Fixture(image, base, old, target_states=('active','active'), reset_failures=reset_failures)
            fixture.snapshot()
            status = fixture.apply(target)
            assert status == (4 if reset_failures[1] else 2)
            assert fixture.lost_before_reset == [0,1]
            assert [row['depth'] for row in fixture.target_events] == [[2048,2048],[1024,1024]]
            assert all(row['logical'] == [1024,1024] for row in target_fields(fixture))
            cases.append(dict(kind='screen_targets_reset_failure', base=hex(base), status=status,
                              reset_failures=list(reset_failures), saved_target_dimensions_restored=True,
                              saved_depth_dimensions_restored=True, lost_before_reset=fixture.lost_before_reset))
        # The native renderer retains maximum depth dimensions when shrinking
        # a window. Preserve those larger existing dimensions on both paths.
        for resource_failures in ((), ('target0_texture', None)):
            fixture = Fixture(image, base, old, target_states=('active','active'),
                              resource_failures=resource_failures)
            for offset in (0x2dc,0x2e0):
                put32(fixture.u, RENDERER+offset, 4096)
            fixture.snapshot()
            status = fixture.apply(target)
            assert status == (2 if resource_failures else 1)
            assert all(row['depth'] == [4096,4096] for row in fixture.target_events)
            assert (get32(fixture.u, RENDERER+0x2dc),get32(fixture.u, RENDERER+0x2e0)) == (4096,4096)
            cases.append(dict(kind='screen_targets_preserve_larger_depth', base=hex(base),
                              resource_failed=bool(resource_failures), status=status,
                              depth_dimensions=[4096,4096], resets=fixture.reset_count))
    return cases


def verify_resolution_ui(images: dict[int, bytes]) -> list[dict]:
    """Check native radio payloads, preset lookup and all type/mode predicates."""
    cases = []
    for base, image in images.items():
        address = lambda va: base+va-0x400000

        def fresh():
            u = Uc(UC_ARCH_X86, UC_MODE_32)
            u.mem_map(base, (len(image)+0xfff) & ~0xfff)
            u.mem_write(base, image)
            u.mem_map(DATA, 0x10000)
            u.mem_map(STACK, 0x10000)
            u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
            return u

        def return_from(u, cleanup=0):
            sp = u.reg_read(UC_X86_REG_ESP)
            u.reg_write(UC_X86_REG_EIP, get32(u, sp))
            u.reg_write(UC_X86_REG_ESP, sp+4+cleanup)

        u = fresh()
        u.reg_write(UC_X86_REG_ESI, FORM)
        bounds = []

        def native_bounds_stub(u, at, size, _):
            if at == address(0xa439d8):
                sp = u.reg_read(UC_X86_REG_ESP)
                # Verified original SetBounds stack order: width is the first
                # pushed parameter, height the second (nearest return address).
                height, width = get32(u, sp+4), get32(u, sp+8)
                assert u.reg_read(UC_X86_REG_EAX) == FORM
                bounds.append((width, height))
                put32(u, FORM+0x38, width)
                put32(u, FORM+0x3c, height)
                return_from(u, 8)

        u.hook_add(UC_HOOK_CODE, native_bounds_stub)
        u.emu_start(address(0x8867b8), address(0x8867d3), count=30)
        assert bounds == [(384, 384)]
        native_button_rows = []
        for index, va in enumerate(resolution_ui.BUTTON_ROW_VAS):
            button = DATA+0x3000+index*0x300
            u.reg_write(UC_X86_REG_EBX, button)
            u.emu_start(address(va), address(va+len(resolution_ui.BUTTON_ROW_CODE)), count=10)
            native_button_rows.append(get32(u, button+0x34))
        maximum_resolution_bottom = 208+16*(len(resolution_ui.RESOLUTIONS)//2)+16
        assert native_button_rows == [336, 336]
        assert min(native_button_rows)-maximum_resolution_bottom >= 32
        assert u.reg_read(UC_X86_REG_ESP) == STACK+0x8000
        cases.append(dict(kind='ui_native_geometry', base=hex(base), panel=list(bounds[0]),
                          native_button_rows=native_button_rows,
                          maximum_resolution_bottom=maximum_resolution_bottom,
                          minimum_gap=min(native_button_rows)-maximum_resolution_bottom))

        for width, height in (*resolution_ui.RESOLUTIONS, (2560, 1080), (5120, 1440)):
            u = fresh()
            values = list(BASE_VALUES)
            values[4], values[5] = DATA+0x200, 208
            for register, value in zip(REGISTERS, values):
                u.reg_write(register, value)
            put32(u, address(0xa309f4), DATA+0x100)
            objects, captions, helper_calls = [], {}, []

            def hook(u, at, size, _):
                if at == address(0x688328):
                    pointer = u.reg_read(UC_X86_REG_EAX)
                    name = bytes(u.mem_read(pointer, 64)).decode('utf-16le').split('\0')[0]
                    u.reg_write(UC_X86_REG_EAX, {'r_width': width, 'r_height': height}[name])
                    return_from(u)
                elif at == address(0xa44c9c):
                    assert get32(u, u.reg_read(UC_X86_REG_ESP)+4) == DATA+0x200
                    obj = DATA+0x1000+len(objects)*0x300
                    objects.append(obj)
                    u.reg_write(UC_X86_REG_EAX, obj)
                    return_from(u, 4)
                elif at == address(0xa42b04):
                    pointer = u.reg_read(UC_X86_REG_EDX)
                    length = get32(u, pointer-4)
                    assert 0 < length < 100
                    captions[u.reg_read(UC_X86_REG_EAX)] = bytes(u.mem_read(pointer, length)).decode('utf-16le')
                    return_from(u)
                elif at == address(0xa44eac):
                    u.mem_write(u.reg_read(UC_X86_REG_EAX)+0x280, bytes([u.reg_read(UC_X86_REG_EDX) & 1]))
                    return_from(u)
                elif at == address(0x884688):
                    helper_calls.append(at)
                    return_from(u)

            u.hook_add(UC_HOOK_CODE, hook)
            u.emu_start(address(0x886f28), address(0x886f98), count=10000)
            known = (width, height) in resolution_ui.RESOLUTIONS
            assert len(objects) == (10 if known else 11)
            selected = [index for index, obj in enumerate(objects) if u.mem_read(obj+0x280, 1)[0]]
            expected = resolution_ui.RESOLUTIONS.index((width, height)) if known else 10
            assert selected == [expected]
            assert [u.reg_read(register) for register in REGISTERS] == values
            assert u.reg_read(UC_X86_REG_ESP) == STACK+0x8000
            assert len(helper_calls) == 1
            for index, obj in enumerate(objects):
                assert get32(u, obj+0x284) == 3 and get32(u, obj+0x278) == index
                assert get32(u, obj+0x30) == 128+96*(index % 2)
                assert get32(u, obj+0x34) == 208+16*(index // 2)
                assert get32(u, obj+0x38) == 92
                expected_caption = ('%dx%d' % resolution_ui.RESOLUTIONS[index]) if index < 10 else 'Current'
                assert captions[obj] == expected_caption
            cases.append(dict(kind='ui_constructor', base=hex(base), resolution=[width, height],
                              controls=len(objects), selected=expected, registers_preserved=True))

        for index in range(11):
            u = fresh()
            u.reg_write(UC_X86_REG_EBP, FRAME)
            u.reg_write(UC_X86_REG_EBX, 7)
            u.reg_write(UC_X86_REG_ESI, index)
            u.reg_write(UC_X86_REG_EDI, 11)
            put32(u, address(0xb76650), DATA+0x100)
            put32(u, DATA+0x1000+0x278, index)

            def hook(u, at, size, _):
                if at == address(0xa3f2a0):
                    assert u.reg_read(UC_X86_REG_EDX) == 7
                    u.reg_write(UC_X86_REG_EAX, DATA+0x500)
                    return_from(u)
                elif at == address(0xa424c4):
                    assert u.reg_read(UC_X86_REG_EDX) == index
                    u.reg_write(UC_X86_REG_EAX, DATA+0x1000)
                    return_from(u)
                elif at == address(0x688328):
                    pointer = u.reg_read(UC_X86_REG_EAX)
                    name = bytes(u.mem_read(pointer, 64)).decode('utf-16le').split('\0')[0]
                    u.reg_write(UC_X86_REG_EAX, {'r_width': 5120, 'r_height': 1440}[name])
                    return_from(u)

            u.hook_add(UC_HOOK_CODE, hook)
            u.emu_start(address(0x884928), address(0x8849c2), count=1000)
            expected = resolution_ui.RESOLUTIONS[index] if index < 10 else (5120, 1440)
            assert (get32(u, FRAME-8), get32(u, FRAME-12)) == expected
            assert u.reg_read(UC_X86_REG_EDI) == 11
            cases.append(dict(kind='ui_lookup', base=hex(base), index=index, resolution=list(expected)))

        for monitor in range(4):
            for mode in range(3):
                u = fresh()
                u.reg_write(UC_X86_REG_EBP, FRAME)
                u.reg_write(UC_X86_REG_EAX, FORM)
                put32(u, FRAME-4, monitor)
                put32(u, FRAME-0x10, mode)
                u.emu_start(address(0x884912), address(0x884924), count=40)
                expected = mode == 0 or (mode == 1 and monitor == 0)
                assert (u.reg_read(UC_X86_REG_EDX) & 0xff) == expected
                assert u.reg_read(UC_X86_REG_EAX) == FORM
                cases.append(dict(kind='ui_enabled', base=hex(base), monitor=monitor,
                                  mode=mode, enabled=expected))
    return cases


def verify(source: Path, candidate: Path | None, output: Path):
    original = source.read_bytes()
    data = candidate.read_bytes() if candidate else screen.patch(original, expected_sha=hashlib.sha256(original).hexdigest())
    images = {}
    for base in (0x400000, 0x10400000):
        pe = pefile.PE(data=data)
        pe.relocate_image(base)
        images[base] = pe.get_memory_mapped_image()
    ui_cases = verify_resolution_ui(images)
    native_resize_cases = verify_native_resize(images)
    target_cases = verify_screen_targets(images)
    cases = []
    for base, image in images.items():
        for monitor in range(4):
            for mode in range(3):
                old = (2, 0, 1366, 768, 0)
                target = (monitor, mode, 1920, 1080, 0)
                fixture = Fixture(image, base, old)
                fixture.snapshot()
                status = fixture.apply(target)
                assert status == 1, status
                assert fixture.reset_count == 1
                assert tuple(fixture.cvars[name] for name in screen.CVARS) == target
                assert fixture.exclusive == [int(monitor == 0 and mode == 1)]
                assert fixture.device_windows == [0x12340000]
                expected_size = ((2560,1392) if mode == 2 else (2560,1440)
                                 if mode == 1 and monitor > 0 else target[2:4])
                assert fixture.resize_events == [expected_size]
                assert fixture.ui_resize_events == fixture.resize_events
                assert fixture.vsync_values == [target[4]]
                cases.append(dict(kind='apply', base=hex(base), target=list(target), status=status, resets=1))
        for old in ((2, 0, 1920, 1080, 0), (0, 1, 1280, 720, 1), (2, 2, 2560, 1440, 1)):
            fixture = Fixture(image, base, old)
            fixture.snapshot()
            status = fixture.apply(old)
            assert status == 1 and fixture.reset_count == 0, 'Unchanged settings reset the device'
            assert not fixture.ui_resize_events
            cases.append(dict(kind='no_change', base=hex(base), target=list(old), status=status, resets=0))
        for failures in ((True, False), (True, True)):
            old, target = (2, 0, 1366, 768, 0), (0, 1, 1920, 1080, 1)
            fixture = Fixture(image, base, old, reset_failures=failures)
            fixture.snapshot()
            status = fixture.apply(target)
            assert status == (4 if failures[1] else 2) and fixture.reset_count == 2
            assert tuple(fixture.cvars[name] for name in screen.CVARS) == old
            assert fixture.commands[-5:] == [f'{name} {value}' for name, value in zip(screen.CVARS, old)]
            assert fixture.exclusive == [1, 0]
            assert fixture.lost_before_reset == [0, 1]
            assert get32(fixture.u, base+screen.STATE+0x34) == 0x8876086c
            assert get32(fixture.u, base+screen.STATE+0x38) == (0x8876086c if failures[1] else 0)
            assert fixture.dialogs[0]['title'] == 'Экран'
            assert 'Сохранены прежние настройки' in fixture.dialogs[0]['message']
            assert fixture.ui_resize_events == ([] if failures[1] else [old[2:4]])
            assert fixture.vsync_values == [1, 0]
            assert fixture.u.mem_read(RENDERER+0x2d3, 1)[0] == old[4]
            cases.append(dict(kind='reset_failure', base=hex(base), rollback_reset_failed=failures[1], status=status, resets=2))
        for unavailable in ('host_guard', 'form_ref', 'form_object', 'renderer_ref', 'renderer_object'):
            old, target = (2, 0, 1366, 768, 0), (2, 0, 1920, 1080, 0)
            fixture = Fixture(image, base, old, unavailable=unavailable)
            fixture.snapshot()
            status = fixture.apply(target)
            assert status == 3 and fixture.reset_count == 0
            assert tuple(fixture.cvars[name] for name in screen.CVARS) == old
            assert not any(call[0] == 'host' for call in fixture.calls)
            assert not fixture.ui_resize_events
            cases.append(dict(kind='unavailable', base=hex(base), reason=unavailable, status=status, resets=0))
        for target in ((4, 0, 1920, 1080), (-1, 0, 1920, 1080), (2, 3, 1920, 1080),
                       (2, -1, 1920, 1080), (2, 0, 799, 1080), (2, 0, 7681, 1080),
                       (2, 0, 1920, 599), (2, 0, 1920, 4321),
                       (2, 0, 1920, 1080, -1), (2, 0, 1920, 1080, 2)):
            old = (2, 0, 1366, 768, 0)
            target = screen_values(target)
            fixture = Fixture(image, base, old)
            fixture.snapshot()
            status = fixture.apply(target)
            assert status == 3 and fixture.reset_count == 0
            assert tuple(fixture.cvars[name] for name in screen.CVARS) == old
            assert not any(call[0] == 'host' for call in fixture.calls)
            assert not fixture.ui_resize_events
            cases.append(dict(kind='invalid', base=hex(base), target=list(target), status=status, resets=0))
        for old_vsync, new_vsync in ((0, 1), (1, 0)):
            old = (2, 0, 1920, 1080, old_vsync)
            target = (2, 0, 1920, 1080, new_vsync)
            fixture = Fixture(image, base, old)
            fixture.snapshot()
            status = fixture.apply(target)
            assert status == 1 and fixture.reset_count == 1
            assert tuple(fixture.cvars[name] for name in screen.CVARS) == target
            assert fixture.vsync_values == [new_vsync]
            assert fixture.ui_resize_events == [target[2:4]]
            assert fixture.u.mem_read(RENDERER+0x2d3, 1)[0] == new_vsync
            cases.append(dict(kind='vsync_only', base=hex(base), old=old_vsync,
                              target=new_vsync, status=status, resets=1))
            for failures in ((True, False), (True, True)):
                fixture = Fixture(image, base, old, reset_failures=failures)
                fixture.snapshot()
                status = fixture.apply(target)
                assert status == (4 if failures[1] else 2) and fixture.reset_count == 2
                assert tuple(fixture.cvars[name] for name in screen.CVARS) == old
                assert fixture.vsync_values == [new_vsync, old_vsync]
                assert fixture.u.mem_read(RENDERER+0x2d3, 1)[0] == old_vsync
                assert fixture.ui_resize_events == ([] if failures[1] else [old[2:4]])
                cases.append(dict(kind='vsync_only_failure', base=hex(base), old=old_vsync,
                                  target=new_vsync, rollback_reset_failed=failures[1],
                                  status=status, resets=2))
    report = dict(candidate_sha256=hashlib.sha256(data).hexdigest(),
                  transformer_sha256=hashlib.sha256((ROOT/'deploy/client_screen_settings.py').read_bytes()).hexdigest(),
                  cases=len(cases)+len(ui_cases)+len(native_resize_cases)+len(target_cases), screen_apply_cases=len(cases),
                  resolution_ui_cases=len(ui_cases), native_silver_resize_cases=len(native_resize_cases),
                  screen_target_lifecycle_cases=len(target_cases),
                  all_pass=True, details=cases+ui_cases+native_resize_cases+target_cases,
                  screen_apply_native_host_and_ui_calls_stubbed=True, graphical_client=False,
                  fixed_ti_base='0x400000', silver_bases=[hex(base) for base in images],
                  original_apply_final_cvar_command_retained=True,
                  rollback_managed_strings_freed=True, failure_loop_checked=True,
                  no_change_does_not_reset=True, relocated_popup_skip_checked=True,
                  cvar_and_error_constants_preserved=True,
                  rollback_sets_existing_lost_state=True)
    report['direct_silver_resize_stdcall_arguments_checked'] = True
    report['native_silver_resize_dimensions_viewport_and_clamps_executed'] = True
    report['vsync_only_changes_reset_device_and_rollback_checked'] = True
    report['screen_sized_targets_and_square_depth_checked'] = True
    report['reset_s_ok_resource_failures_and_saved_dimensions_rollback_checked'] = True
    report['native_chat_refresh_after_resize_call_order_checked'] = True
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'details'}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'reports/screen-settings/resolution-ui/silver.dll')
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'reports/screen-settings/hotapply-native-proof.json')
    args = parser.parse_args()
    verify(args.source, args.candidate, args.output)


if __name__ == '__main__':
    main()
