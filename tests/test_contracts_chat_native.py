"""Run the pinned native chat tab dispatcher with scoped UI/string stubs.

The original a50bf8 routing and a4f76c append/unread decision execute. Only
Delphi string ownership, widget lookup and the final chat-list append are
stubbed. No graphical client, socket or player database is used.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX,
    UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EIP)

from deploy.client_contracts_city import BASE_SHA

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/contracts-local/city-ui/native/source-silver.dll'
DATA = 0x2000000
STACK = 0x3000000
STOP = STACK+0x100
TEXT = '[Контракты] ContractA приглашает вас в группу. !party accept'
GUARDS = {
    (0xa50bf8, 0x470): '9035006a9e4a1ce954f312d51b3132ac56b410c690ac2c4b38eae2d2ba632c08',
    (0xa4f76c, 0x187): 'b1528aa43c4d119ed024a28fc76b4a8da6360b3d035ff6794b55ba35388654fc',
}


class NativeChat:
    def __init__(self, raw, tabs):
        pe = pefile.PE(data=raw)
        for (address, size), digest in GUARDS.items():
            if hashlib.sha256(pe.get_data(address-0x400000, size)).hexdigest() != digest:
                raise ValueError('Unrecognized native chat branch')
        mapped = pe.get_memory_mapped_image()
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u.mem_map(0, 0x1000)
        self.u.mem_map(0x400000, (len(mapped)+4095)&~4095)
        self.u.mem_write(0x400000, mapped)
        self.u.mem_map(DATA, 0x10000)
        self.u.mem_map(STACK, 0x10000)
        self.tabs = []
        self.rows = []
        self.append_lists = {}
        self.body = DATA+0x8100
        self.sender = DATA+0x8200
        self.u.mem_write(self.body, TEXT.encode('utf-16le')+b'\0\0')
        self.u.mem_write(self.sender, 'Контракты'.encode('utf-16le')+b'\0\0')
        self.put(0xac5cf8, DATA+0x8300)  # Ordinary chat settings.
        self.put(0xac628c, DATA+0x8340)  # Disable private auto-response.
        for index, (tag, enabled) in enumerate(tabs):
            tab = DATA+0x1000+index*0x400
            self.tabs.append(tab)
            self.put(tab+0x278, tag)
            self.u.mem_write(tab+0x4a, bytes((int(enabled),)))
            self.put(tab+0x29c, tab+0x300)
            self.append_lists[tab+0x300] = tab
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def get(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def put(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value))

    def text(self, address):
        result = bytearray()
        for offset in range(0, 800, 2):
            word = bytes(self.u.mem_read(address+offset, 2))
            if word == b'\0\0':
                return result.decode('utf-16le')
            result.extend(word)
        raise AssertionError('Unterminated native text')

    def ret(self, arguments=0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, self.get(sp))
        self.u.reg_write(UC_X86_REG_ESP, sp+4+arguments)

    def hook(self, _u, address, _size, _data):
        eax = self.u.reg_read(UC_X86_REG_EAX)
        edx = self.u.reg_read(UC_X86_REG_EDX)
        if address in (0x40b180, 0x40b1a0, 0x40b0fc, 0x40b0e4, 0x40b09c):
            self.ret()  # String reference ownership only.
        elif address == 0xa424d4:
            self.u.reg_write(UC_X86_REG_EAX, len(self.tabs)); self.ret()
        elif address == 0xa424c4:
            self.u.reg_write(UC_X86_REG_EAX, self.tabs[edx]); self.ret()
        elif address == 0x40c048:
            self.put(eax, edx); self.ret()  # Wide string assignment.
        elif address in (0xa50b98, 0xa50b54):
            self.put(eax, 0); self.ret()  # Optional timestamp/team markup.
        elif address == 0x40c244:
            # Formatting is outside this routing probe; retain the actual body.
            self.put(eax, self.body); self.ret(4*edx)
        elif address == 0xa4c580:
            tab = self.append_lists[eax]
            self.rows.append(dict(tag=self.get(tab+0x278), text=self.text(edx),
                markup=self.text(self.u.reg_read(UC_X86_REG_ECX))))
            self.ret(4)  # Native final chat-list append has one stack argument.

    def dispatch(self, channel):
        sp = STACK+0x8000
        self.put(sp, STOP)
        self.put(sp+4, 0)
        self.put(sp+8, self.body)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        self.u.reg_write(UC_X86_REG_EAX, DATA+0x7000)
        self.u.reg_write(UC_X86_REG_EDX, channel)
        self.u.reg_write(UC_X86_REG_ECX, self.sender)
        self.u.emu_start(0xa50bf8, STOP, count=30000)
        if self.u.reg_read(UC_X86_REG_EIP) != STOP:
            raise AssertionError('Native dispatcher did not complete')
        return self.rows


class ContractsNativeChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = SOURCE.read_bytes()
        if hashlib.sha256(cls.raw).hexdigest() != BASE_SHA:
            raise ValueError('Native chat probe requires the pinned published source')

    def test_system_message_reaches_first_enabled_tab_without_location_tab(self):
        native = NativeChat(self.raw, ((12, True), (6, True), (8, True)))
        rows = native.dispatch(5)
        self.assertEqual([row['tag'] for row in rows], [12])
        self.assertTrue(all(row['text'] == TEXT for row in rows))
        self.assertTrue(all(row['markup'] == ' @ 2' for row in rows))

    def test_system_message_excludes_disabled_tabs(self):
        native = NativeChat(self.raw, ((12, True), (6, False), (8, False)))
        self.assertEqual([row['tag'] for row in native.dispatch(5)], [12])

    def test_system_message_uses_trade_or_help_when_global_is_disabled(self):
        for selected in (6, 8):
            with self.subTest(selected=selected):
                native = NativeChat(self.raw, tuple((tag, tag == selected) for tag in (12, 6, 8)))
                self.assertEqual([row['tag'] for row in native.dispatch(5)], [selected])

    def test_location_message_is_absent_when_native_location_tab_is_missing(self):
        native = NativeChat(self.raw, ((12, True), (6, True), (8, True)))
        self.assertEqual(native.dispatch(0), [])

    def test_existing_location_chat_routing_is_preserved(self):
        native = NativeChat(self.raw, ((12, True), (0, True), (6, True)))
        self.assertEqual([row['tag'] for row in native.dispatch(0)], [0])

    def test_channel_four_is_battle_chat_and_has_no_city_target(self):
        native = NativeChat(self.raw, ((12, True), (6, True), (8, True)))
        self.assertEqual(native.dispatch(4), [])


if __name__ == '__main__':
    unittest.main()
