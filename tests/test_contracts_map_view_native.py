"""Pinned original x86 map-mode transition, without clients or sockets.

The EE dispatcher, u16 reader, status assignment, map-mode setter and integer
to float position reset execute unchanged. F0/97 and F0/117 original branches
also execute. Widget lookup/show/hide, chat-tab changes and city label refresh
are explicitly stubbed; this proves the render-mode choice, not D3D drawing.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX,
    UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP)

from deploy.client_contracts_city import BASE_SHA
from tio.locations import leave_town_packet, movement_packet, stop_packet
from tio.protocol.system_message import encode_open_town_view

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/contracts-local/city-ui/native/source-silver.dll'
DATA = 0x2000000
STACK = 0x3000000
STOP = STACK+0x100
CHAR = DATA+0x1000
TOWN = DATA+0x2000
GUARDS = {
    (0x7d2de6, 0x92): '0da100e536fd848fc811a177837a68ca2fed7d8988485c912d4c84c723f30f01',
    (0x7d26e2, 0x11): 'c6542a027afb41d1067d93f66a9dd340bd1a282091a701c2d0a3c322f3607c97',
    (0x88b33c, 0x15b): '22546d3b34887f8a6077377f4b9e2094806998ca5459da6ada7e89195ac80fb3',
    (0x88b29c, 0x9e): 'a53314b2f75b7882fab9d94030cc071f2933bb956b4fcd0faa62cf5a829537ab',
    (0x85905c, 0x1b8): '0eeb86dc9ed8d0bdb27ef5bd3c368697526e4d1a498e50e175a706e349debf35',
    (0x9de87c, 0xf): '007bf4d89b4d7ad1ba4ebc40e59362934af7dcb5ee4edd1a88685c5dd87053a0',
    (0x9edeb4, 0x3d): '129b0947d993bf1d5eaa28d6ea28e4b47b9a3b48359eb762b00132f0c6ebf976',
    (0x8596e0, 0x90): '0496a1b1a17e14d94343b41cadb5000dcc6a079d368136d75681255e77f4e4c2',
    (0x9e58a8, 0x30): 'e6f176c11feac1b5333111f7b0b5f2a72b579e418a3d887f005eb6eaaf9a3d5c',
    (0x9e4e5c, 0x301): '8d1959cdce894526b75df94e71bfd018a9952a1e5bdde815449082f1c6c2230e',
}


class NativeMapView:
    def __init__(self, raw, *, mode=1):
        pe = pefile.PE(data=raw)
        for (address, size), digest in GUARDS.items():
            if hashlib.sha256(pe.get_data(address-0x400000, size)).hexdigest() != digest:
                raise ValueError('Unrecognized native map-view consumer span')
        mapped = pe.get_memory_mapped_image()
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u.mem_map(0, 0x1000)
        self.u.mem_map(0x400000, (len(mapped)+0xfff)&~0xfff)
        self.u.mem_write(0x400000, mapped)
        self.u.mem_map(DATA, 0x10000)
        self.u.mem_map(STACK, 0x10000)
        # The original imported city/global flag is an alias of the renderer's
        # actual mode, not a separate simulated boolean.
        if self.get(0xac5e5c) != 0xac4c6d:
            raise ValueError('Native render-mode import alias changed')
        for address, target in (
            (0xac5b7c, CHAR), (0xac5d58, TOWN),
            (0xac5630, DATA+0x2200), (0xac54d8, DATA+0x2400),
            (0xac622c, DATA+0x2600), (0xac6370, DATA+0x2900),
            (0xac6440, DATA+0x4000), (0xac62a4, DATA+0x5000),
            (0xac63bc, DATA+0x6000), (0xac5a98, DATA+0x6100),
            (0xac5a4c, DATA+0x6200), (0xac60a4, DATA+0x6300)):
            self.put(address, target)
        self.put(TOWN, 3)
        self.put(DATA+0x2600, DATA+0x2800)
        self.put(DATA+0x6000, DATA+0x6400)
        self.put(DATA+0x6408, DATA+0x6600)
        self.u.mem_write(DATA+0x660c, b'\x03')  # No mine/base callbacks.
        self.put(DATA+0x6100, 42)
        self.put(0xac4804, 0xffffffff)  # No active mine-help session.
        self.u.mem_write(CHAR+0xc, struct.pack('<ii', -154, -318))
        self.u.mem_write(CHAR+0x1c, struct.pack('<ff', -154., -318.))
        self.u.mem_write(0xac4c6d, bytes((mode,)))
        self.calls = []
        self.chat_calls = []
        self.reader_consumed = []
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def put(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value))

    def get(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def ret(self, arguments=0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, self.get(sp))
        self.u.reg_write(UC_X86_REG_ESP, sp+4+arguments)

    def hook(self, _u, address, _size, _data):
        if address in (0x88b29c, 0x85905c, 0x9de87c, 0x9edeb4, 0x8596e0):
            self.calls.append(address)
        if address == 0x88b2ab:
            bp = self.u.reg_read(UC_X86_REG_EBP)
            self.reader_consumed.append(self.get(bp-4)-DATA)
        if address in (0xa03040, 0xa03344):
            self.chat_calls.append((address,
                self.u.reg_read(UC_X86_REG_EAX)&0xff))
            self.ret()
        elif address == 0xa3fca8:
            self.u.reg_write(UC_X86_REG_EAX, 0); self.ret()
        elif address == 0xa3f2a0:
            self.u.reg_write(UC_X86_REG_EAX, DATA+0x3000); self.ret()
        elif address == 0xa69d68:
            self.u.reg_write(UC_X86_REG_EAX, 0); self.ret()
        elif address == 0x775efc:
            self.ret(4)  # This widget binding consumes one stack argument.
        elif address in (
            0x9cfa38, 0xa4370c, 0xa436e8, 0xa6a114, 0xa69ec0,
            0x83649c, 0xa00c60, 0xa01ef4, 0x8a36c0, 0xa088e0,
            0x78c3f8, 0xa01634, 0xa05434, 0x9b822c,
            0x9e4584, 0x9e3c88, 0x9e4568, 0xa3ebf4, 0x7d1350):
            self.ret()  # Scoped GUI/logging boundaries only.

    def run(self, entry, end=STOP):
        self.put(STACK+0x8000, STOP)
        self.u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
        self.u.emu_start(entry, end, count=10000)
        if self.u.reg_read(UC_X86_REG_EIP) != end:
            raise AssertionError('Native map-view path exceeded its instruction budget')

    def receive_state(self, packet):
        if len(packet) != 3 or packet[0] != 0xee:
            raise ValueError('Expected native EE and one u16')
        self.u.mem_write(DATA, packet[1:])
        self.u.reg_write(UC_X86_REG_EAX, packet[0])
        self.u.reg_write(UC_X86_REG_EDX, DATA)
        self.u.reg_write(UC_X86_REG_ECX, len(packet))
        self.run(0x88b33c)

    def receive_system(self, packet):
        command = struct.unpack_from('<I', packet, 1)[0]
        index = self.u.mem_read(0x7d1db4+command, 1)[0]
        address = self.get(0x7d1fbf+4*index)
        if command not in (97, 117) or packet != struct.pack('<BII', 0xf0, command, 0):
            raise ValueError('Expected bounded no-argument F0 view command')
        self.run(address, 0x7d3d59)

    def receive_position(self, packet):
        if packet[0] not in (0x1d, 0x1e):
            raise ValueError('Expected native moving or stopped position')
        self.u.mem_write(DATA, packet[1:])
        self.u.reg_write(UC_X86_REG_EAX, DATA)
        self.run(0x88b130 if packet[0] == 0x1d else 0x88b248)

    @property
    def mode(self):
        return self.u.mem_read(0xac4c6d, 1)[0]

    @property
    def status(self):
        return self.u.mem_read(CHAR+0x22c, 1)[0]


class ContractsNativeMapViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = SOURCE.read_bytes()
        if hashlib.sha256(cls.raw).hexdigest() != BASE_SHA:
            raise ValueError('Map-view probe requires the pinned published source')

    def test_leave_town_alone_keeps_city_render_mode(self):
        native = NativeMapView(self.raw)
        native.receive_system(leave_town_packet())
        self.assertEqual(native.get(TOWN), 0xffffffff)
        self.assertEqual(native.mode, 1)
        self.assertNotIn(0x9de87c, native.calls)

    def test_actual_map_packet_dispatches_and_switches_city_to_global(self):
        from tio.protocol.world_bootstrap import encode_open_map_view
        native = NativeMapView(self.raw)
        native.receive_state(encode_open_map_view())
        self.assertEqual(native.mode, 0)
        self.assertEqual(native.status, 2)
        self.assertEqual(native.reader_consumed, [2])
        self.assertEqual(native.calls, [0x88b29c, 0x85905c, 0x9de87c, 0x9edeb4])
        self.assertEqual(struct.unpack('<ii', native.u.mem_read(CHAR+0xc, 8)), (-154, -318))

    def test_departure_sequence_enables_map_and_preserves_moving_destination(self):
        from tio.protocol.world_bootstrap import encode_open_map_view
        native = NativeMapView(self.raw)
        native.receive_system(leave_town_packet())
        native.receive_state(encode_open_map_view())
        native.receive_position(movement_packet(42, -154, -318, destination=(-200, -370)))
        self.assertEqual((native.mode, native.status), (0, 2))
        self.assertEqual(native.get(CHAR+0x224), 0xffffffff)
        self.assertEqual(struct.unpack('<ii', native.u.mem_read(CHAR+0x14, 8)), (-200, -370))

    def test_reconnect_at_stopped_target_uses_global_mode(self):
        from tio.protocol.world_bootstrap import encode_open_map_view
        native = NativeMapView(self.raw)
        native.receive_system(leave_town_packet())
        native.receive_state(encode_open_map_view())
        native.receive_position(stop_packet(42, -200, -370))
        self.assertEqual(native.mode, 0)
        self.assertEqual(native.get(CHAR+0x224), 0)
        self.assertEqual(struct.unpack('<ii', native.u.mem_read(CHAR+0xc, 8)), (-200, -370))

    def test_city_return_restores_normal_status_chat_and_city_mode(self):
        from tio.protocol.world_bootstrap import encode_open_map_view, encode_restore_city_controls
        native = NativeMapView(self.raw)
        native.receive_state(encode_open_map_view())
        native.put(TOWN, 3)  # F0/98's separately verified selected-town projection.
        native.receive_state(encode_restore_city_controls())
        self.assertEqual(native.status, 0)
        self.assertEqual(native.mode, 0)  # EE0 resets status, not the view.
        self.assertIn((0xa03344, 6), native.chat_calls)
        self.assertIn((0xa03344, 0), native.chat_calls)
        native.receive_system(encode_open_town_view())
        self.assertEqual(native.mode, 1)

    def test_repeated_map_packet_is_safe_when_already_global(self):
        from tio.protocol.world_bootstrap import encode_open_map_view
        native = NativeMapView(self.raw, mode=0)
        native.receive_state(encode_open_map_view())
        self.assertEqual((native.mode, native.status), (0, 2))
        self.assertNotIn(0x9de87c, native.calls)

    def test_native_u16_state_is_not_truncated_to_one_byte(self):
        native = NativeMapView(self.raw)
        native.receive_state(b'\xee\x02\x01')
        self.assertEqual((native.mode, native.status), (1, 0xff))
        self.assertNotIn(0x85905c, native.calls)


if __name__ == '__main__':
    unittest.main()
