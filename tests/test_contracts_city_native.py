"""Execute the actual city extension x86 with scoped native API sentinels."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX,
    UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
    UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)

from deploy import client_contracts_city as city

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/contracts-local/city-ui/native/source-silver.dll'
FALLBACK = ROOT/'reports/contracts-local/clients/game-a/silver.dll'
OBJECT = 0x3001000
TOWN = 0x3000800
CLASS = 0x3000900
STACK = 0x4008000
STOP = 0x400f000
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
        UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)


def source_bytes():
    data = (SOURCE if SOURCE.is_file() else FALLBACK).read_bytes()
    if hashlib.sha256(data).hexdigest() != city.BASE_SHA:
        raise ValueError('Native probes require the pinned original published source')
    return data


class Machine:
    def __init__(self, delta=0):
        self.delta = delta
        self.base = city.IMAGE_BASE+delta
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u.mem_map(self.base, 0x900000)
        self.u.mem_map(0x3000000, 0x20000)
        self.u.mem_map(0x4000000, 0x10000)
        self.u.mem_write(self.base+city.SECTION_RVA, city.section_payload())
        self.handlers = {}
        self.u.hook_add(UC_HOOK_CODE, self.hook)
        self.children = []
        self.next_child = 0
        self.calls = []
        self.sent = []
        self.captions = {}
        self.callbacks = {}
        self.write(self.va(0xac5d58), TOWN)
        self.write(TOWN, 3)
        self.write(self.va(0xa2ecdc), CLASS)
        self.write(OBJECT+0x38, 280)
        self.write(OBJECT+0x3c, 300)
        self.write(OBJECT+0x30, 168)
        self.write(OBJECT+0x34, 80)
        for native, handler in (
            (0x8d3604, self.decorate), (0x4f2cb4, self.resource),
            (0xa4517c, self.create), (0xa42b04, self.caption),
            (0xa55038, self.event), (0xa424d4, self.count),
            (0xa424c4, self.child), (0x4095ac, self.instance),
            (0x9ff3e4, self.chat), (0x9e3c88, self.refresh)):
            self.handlers[self.va(native)] = handler

    def va(self, address):
        return address+self.delta

    def read(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def write(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def reg(self, register, value=None):
        if value is not None:
            self.u.reg_write(register, value)
        return self.u.reg_read(register)

    def ret(self, count=0):
        sp = self.reg(UC_X86_REG_ESP)
        self.reg(UC_X86_REG_EIP, self.read(sp))
        self.reg(UC_X86_REG_ESP, sp+4+count)

    def hook(self, _u, address, _size, _data):
        if address == STOP:
            self.u.emu_stop()
        elif address in self.handlers:
            self.handlers[address]()

    def string(self, address, unicode_string=False):
        size = self.read(address-4)
        return bytes(self.u.mem_read(address, size*2 if unicode_string else size)).decode('utf-16le')

    def arguments(self, count):
        sp = self.reg(UC_X86_REG_ESP)
        return tuple(self.read(sp+4+i*4) for i in range(count))

    def decorate(self):
        self.calls.append(('decorate', self.arguments(5), self.reg(UC_X86_REG_EAX)))
        self.reg(UC_X86_REG_EAX, 0x778899)
        self.ret(20)

    def resource(self):
        pointer, kind, arg1, arg2 = self.arguments(4)
        self.calls.append(('resource', self.string(self.reg(UC_X86_REG_EAX), True),
            self.reg(UC_X86_REG_ECX), self.reg(UC_X86_REG_EDX), kind, arg1, arg2))
        self.write(pointer, pointer+0x20)
        self.write(pointer+4, 0x77770000)
        self.write(pointer+8, self.reg(UC_X86_REG_ECX)*0x10001)
        self.reg(UC_X86_REG_EAX, 0x334455)
        self.reg(UC_X86_REG_ECX, 0x556677)
        self.reg(UC_X86_REG_EDX, 0x667788)
        self.ret(16)

    def add_child(self, *, visible=True, button=True):
        pointer = 0x3004000+self.next_child*0x400
        self.next_child += 1
        self.children.append((pointer, button))
        self.u.mem_write(pointer+0x49, bytes((int(visible), int(visible))))
        self.write(pointer+0x38, 150)
        self.write(pointer+0x34, 40)
        return pointer

    def create(self):
        parent, = self.arguments(1)
        self.calls.append(('create', parent, self.reg(UC_X86_REG_ECX),
            self.reg(UC_X86_REG_EAX), self.reg(UC_X86_REG_EDX)&255))
        pointer = self.add_child()
        self.reg(UC_X86_REG_EAX, pointer)
        self.ret(4)

    def caption(self):
        self.captions[self.reg(UC_X86_REG_EAX)] = self.string(self.reg(UC_X86_REG_EDX))
        self.ret()

    def event(self):
        self.callbacks[self.reg(UC_X86_REG_EAX)-0x2a0] = self.reg(UC_X86_REG_EDX)
        self.ret()

    def count(self):
        if self.reg(UC_X86_REG_EAX) != OBJECT:
            raise AssertionError('Layout queried an unrelated parent')
        self.reg(UC_X86_REG_EAX, len(self.children))
        self.ret()

    def child(self):
        self.reg(UC_X86_REG_EAX, self.children[self.reg(UC_X86_REG_EDX)][0])
        self.ret()

    def instance(self):
        pointer = self.reg(UC_X86_REG_EAX)
        if self.reg(UC_X86_REG_EDX) != CLASS:
            raise AssertionError('Layout queried an unrelated native class')
        self.reg(UC_X86_REG_EAX, int(dict(self.children)[pointer]))
        self.ret()

    def chat(self):
        self.sent.append((self.reg(UC_X86_REG_EAX)&255,
            self.string(self.reg(UC_X86_REG_EDX)), self.reg(UC_X86_REG_ECX)))
        self.reg(UC_X86_REG_EAX, 0x667788)
        self.reg(UC_X86_REG_ECX, 0x556677)
        self.reg(UC_X86_REG_EDX, 0x778899)
        self.ret()

    def refresh(self):
        self.calls.append(('refresh',))
        self.reg(UC_X86_REG_EAX, 0x556677)
        self.ret()

    def run(self, entry, *args):
        self.write(STACK, STOP)
        for i, arg in enumerate(args, 1):
            self.write(STACK+i*4, arg)
        self.reg(UC_X86_REG_ESP, STACK)
        self.u.emu_start(self.va(city.ENTRIES[entry]), 0, count=10000)


class NativeCityTests(unittest.TestCase):
    def test_constructor_native_parent_events_texture_load_and_stack(self):
        for delta in (0, 0x1000000):
            with self.subTest(aslr_delta=delta):
                m = Machine(delta)
                for _ in range(4):
                    m.add_child()
                m.add_child(visible=False)
                m.add_child(button=False)
                original = {reg: 0x1000+i for i, reg in enumerate(REGS)}
                original[UC_X86_REG_EBX] = OBJECT
                for reg, value in original.items():
                    m.reg(reg, value)
                m.reg(UC_X86_REG_EFLAGS, 0x246)
                # Native decorator may set arithmetic flags; extension retains
                # its post-call value and does not clobber the return register.
                args = (OBJECT, 0x11223344, 0x55667788, 0x12345678, 0x76543210)
                m.run('construct', *args)
                self.assertEqual(m.calls[0], ('decorate', args, original[UC_X86_REG_EAX]))
                self.assertEqual(m.calls[1:3], [
                    ('resource', 'pda\\contracts_button.png', 25, 25, 2, 0, 0),
                    ('resource', 'pda\\contracts_frame.png', 32, 32, 2, 0, 0)])
                created = [call for call in m.calls if call[0] == 'create']
                self.assertEqual(created, [('create', OBJECT, m.base+city.DATA['button_resource'], CLASS, 1)]*2)
                pointers = [m.read(m.base+city.DATA[n+'_button']) for n in ('contracts', 'party')]
                self.assertEqual([m.captions[p] for p in pointers], ['Контракты', 'Группа'])
                self.assertEqual([m.callbacks[p] for p in pointers],
                    [m.va(city.ENTRIES[n]) for n in ('contracts', 'party')])
                self.assertEqual([m.read(p+0x278) for p in pointers], list(city.NEW_BUTTON_IDS))
                original[UC_X86_REG_EAX] = 0x778899
                self.assertEqual({reg: m.reg(reg) for reg in REGS}, original)
                self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+24)
                self.assertEqual(m.reg(UC_X86_REG_EFLAGS), 0x246)
                self.assertEqual(m.read(OBJECT+0x38), 280)
                self.assertEqual(m.read(OBJECT+0x3c), 240)
                self.assertEqual(m.u.mem_read(OBJECT+0x2ad, 1), b'\x01')

    def test_resource_load_is_reused_but_new_lifecycle_receives_new_controls(self):
        m = Machine()
        m.reg(UC_X86_REG_EBX, OBJECT)
        m.run('construct', OBJECT, 0, 0, 0, 0)
        first = m.read(m.base+city.DATA['contracts_button'])
        # Root owns the children: native root reconstruction destroys its old
        # children. Our allocator sentinel gives the second pair fresh
        # addresses, so an accidentally retained pointer cannot pass the probe.
        m.children = []
        m.reg(UC_X86_REG_EBX, OBJECT)
        m.run('construct', OBJECT, 0, 0, 0, 0)
        self.assertEqual(len([c for c in m.calls if c[0]=='resource']), 2)
        self.assertEqual(len([c for c in m.calls if c[0]=='create']), 4)
        self.assertEqual(len(m.children), 2)
        self.assertEqual(m.read(m.base+city.DATA['city']), OBJECT)
        second = m.read(m.base+city.DATA['contracts_button'])
        self.assertNotEqual(first, second)
        self.assertIn(second, dict(m.children))
        self.assertNotIn(first, dict(m.children))
        self.assertEqual(m.read(second+0x278), 0x701)

    def test_callback_plain_event_abi_guard_and_individual_private_commands(self):
        for delta in (0, 0x1000000):
            for town in (*city.CITY_IDS, 0, 1, 6, 9, 17, 18, 20):
                for entry, text in (('contracts', '!contracts list'), ('party', '!party status')):
                    with self.subTest(aslr_delta=delta, town=town, entry=entry):
                        m = Machine(delta)
                        m.write(TOWN, town)
                        original = {reg: 0x1000+i for i, reg in enumerate(REGS)}
                        for reg, value in original.items():
                            m.reg(reg, value)
                        m.reg(UC_X86_REG_EFLAGS, 0x246)
                        m.run(entry)
                        self.assertEqual(m.sent, [(0, text, 0)] if town in city.CITY_IDS else [])
                        self.assertEqual({reg: m.reg(reg) for reg in REGS}, original)
                        self.assertEqual(m.reg(UC_X86_REG_EFLAGS), 0x246)
                        self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+4)

    def test_layout_native_visible_children_only_and_city_gate(self):
        for town, count in ((3, 4), (5, 7), (17, 4)):
            m = Machine()
            m.reg(UC_X86_REG_EBX, OBJECT)
            visible = [m.add_child() for _ in range(count)]
            hidden = m.add_child(visible=False)
            other = m.add_child(button=False)
            m.run('construct', OBJECT, 0, 0, 0, 0)
            m.write(TOWN, town)
            m.run('layout')
            for i, p in enumerate(visible):
                self.assertEqual([m.read(p+o) for o in (0x30,0x34,0x38,0x3c)], [16,32+i*32,248,25])
            for p in (hidden, other):
                self.assertEqual(m.read(p+0x38), 150)
                self.assertEqual(m.read(p+0x34), 40)
            pointers = [m.read(m.base+city.DATA[n+'_button']) for n in ('contracts','party')]
            self.assertEqual([bytes(m.u.mem_read(p+0x49,2)) for p in pointers],
                [b'\x01\x01']*2 if town in city.CITY_IDS else [b'\x00\x00']*2)
            self.assertEqual(m.read(OBJECT+0x3c), (count+(2 if town in city.CITY_IDS else 0))*32+48)

    def test_refresh_original_runs_before_extension_and_retains_abi(self):
        m = Machine()
        original = {reg: 0x5000+i for i, reg in enumerate(REGS)}
        for reg, value in original.items():
            m.reg(reg, value)
        m.run('refresh')
        self.assertEqual(m.calls, [('refresh',)])
        original[UC_X86_REG_EAX] = 0x556677
        self.assertEqual({reg: m.reg(reg) for reg in REGS}, original)
        self.assertEqual(m.reg(UC_X86_REG_ESP), STACK+4)

    def test_pinned_patch_exact_section_hooks_idempotence_and_unknown_refusal(self):
        before = source_bytes()
        updated = city.patch(before)
        self.assertEqual(city.patch(updated), updated)
        pe = pefile.PE(data=updated)
        self.assertEqual(pe.sections[-1].Name.rstrip(b'\0'), city.SECTION_NAME)
        self.assertEqual(pe.sections[-1].VirtualAddress, city.SECTION_RVA)
        self.assertEqual(pe.sections[-1].SizeOfRawData, city.SECTION_SIZE)
        self.assertEqual(len(updated)-len(before), city.SECTION_SIZE)
        self.assertEqual(pe.OPTIONAL_HEADER.SizeOfImage, city.SECTION_RVA+city.SECTION_SIZE)
        self.assertEqual(pe.OPTIONAL_HEADER.DATA_DIRECTORY[5].__pack__(), pefile.PE(data=before).OPTIONAL_HEADER.DATA_DIRECTORY[5].__pack__())
        for va, old, new, _ in city.edit_specifications():
            off = pe.get_offset_from_rva(va-city.IMAGE_BASE)
            self.assertEqual(before[off:off+len(old)], old)
            self.assertEqual(updated[off:off+len(new)], new)
        bad = bytearray(updated)
        bad[pe.sections[-1].PointerToRawData+0xd00] ^= 1
        with self.assertRaises(ValueError):
            city.patch(bytes(bad))
        for offset in (0x400, 0x1000, len(before)-1):
            bad = bytearray(before); bad[offset] ^= 1
            with self.assertRaises(ValueError):
                city.patch(bytes(bad))

    def test_only_declared_code_and_pe_header_bytes_change_in_existing_image(self):
        before = source_bytes(); after = city.patch(before)
        pe = pefile.PE(data=before)
        allowed = set()
        for va, old, _new, _why in city.edit_specifications():
            offset = pe.get_offset_from_rva(va-city.IMAGE_BASE)
            allowed.update(range(offset, offset+len(old)))
        for structure, field, count in (
            (pe.FILE_HEADER,'NumberOfSections',2),
            (pe.OPTIONAL_HEADER,'SizeOfImage',4),
            (pe.OPTIONAL_HEADER,'CheckSum',4),
            (pe.OPTIONAL_HEADER,'SizeOfCode',4)):
            at = structure.get_field_absolute_offset(field)
            allowed.update(range(at,at+count))
        header = pe.sections[-1].get_file_offset()+40
        allowed.update(range(header,header+40))
        actual = {i for i, (b,a) in enumerate(zip(before,after)) if b!=a}
        self.assertTrue(actual <= allowed)
        # Existing arena/hire/premium/service event registrations are untouched.
        for va in (0x85c12d,0x85c1bc,0x85c270,0x85c365,0x85c3ff,0x85c4a8):
            at = pe.get_offset_from_rva(va-city.IMAGE_BASE)
            self.assertEqual(before[at:at+5], after[at:at+5])

    def test_native_packet_writer_tail_serializes_actual_utf16_command_wire(self):
        original = pefile.PE(data=source_bytes()).get_memory_mapped_image()
        for entry, text in (('contracts','!contracts list'),('party','!party status')):
            m = Machine()
            m.u.mem_map(0, 0x1000)  # Native Delphi SEH sentinel, no OS calls.
            # Run the original existing chat writer's transport tail. Native
            # allocation and Unicode reference functions are scoped sentinels;
            # the actual x86 chooses opcode, channel and writes through the
            # native numeric/Unicode packet writers.
            for start,end in ((0x9ff6f8,0x9ff739),(0x675bf8,0x675c34),
                              (0x67493c,0x6749ef)):
                m.u.mem_write(start, original[start-city.IMAGE_BASE:end-city.IMAGE_BASE])
            packet = 0x300c000
            ref = 0x300b000
            vtable = 0x300b200
            dispatch = 0x500000
            command = m.base+city.DATA[entry+'_command']
            raw = text.encode('utf-16le')
            self.assertEqual(m.read(command-4),len(raw))
            frame = 0x4009000
            m.write(frame-4,command)
            m.u.mem_write(frame-0x15,b'\0')
            m.write(frame-8,0)
            m.write(ref,packet)
            m.write(m.va(0xac600c),ref)
            m.write(packet,vtable)
            m.write(vtable,dispatch)
            m.write(packet+0x1004,0)
            m.u.mem_write(dispatch,b'\xc3')
            def begin():
                m.reg(UC_X86_REG_EAX,ref);m.ret()
            def reference():m.ret()
            def compare():
                m.reg(UC_X86_REG_EFLAGS, m.reg(UC_X86_REG_EFLAGS)&~0x40);m.ret()
            def memcpy():
                m.u.mem_write(m.reg(UC_X86_REG_EDX),bytes(m.u.mem_read(m.reg(UC_X86_REG_EAX),m.reg(UC_X86_REG_ECX))))
                m.ret()
            def skip_reply():m.reg(UC_X86_REG_EAX,ref);m.ret()
            def done():m.u.emu_stop()
            m.handlers.update({0x6748b0:begin,0x40b1a0:reference,0x40be70:compare,
                0x406cf8:memcpy,0x40b0e4:reference,0x674b14:skip_reply,
                dispatch:done})
            m.reg(UC_X86_REG_ESP,STACK)
            m.reg(UC_X86_REG_EBP,frame)
            m.u.emu_start(0x9ff6f8,0,count=1000)
            size = m.read(packet+0x1004)
            self.assertEqual(bytes(m.u.mem_read(packet+4,size)),b'\x21\x00'+raw+b'\0\0')


if __name__ == '__main__':
    unittest.main()
