"""Execute existing Silver chat geometry code without launching a game.

The root docking, immediate-child layout and ChatPage geometry functions are
native x86. Name/list/type lookup and text wrapping/scroll metrics are explicit
stubs. The latter stubs preserve all synthetic message and input data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from functools import lru_cache

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
    UC_X86_REG_EIP, UC_X86_REG_EFLAGS,
)

ROOT = Path(__file__).resolve().parents[1]
DATA, STACK = 0x30000000, 0x31000000
PRESERVED = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
PRESERVED_VALUES = (0x12345678, 0x23456789, 0x3456789a, 0x456789ab)


@lru_cache(maxsize=2)
def mapped_image(image, base):
    p = pefile.PE(data=image)
    p.relocate_image(base)
    return p.get_memory_mapped_image()


def put32(u, address, value):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get32(u, address):
    return struct.unpack('<I', u.mem_read(address, 4))[0]


class ChatFixture:
    def __init__(self, image, base, width, height, chat_height=256, *, missing=False):
        mapped = mapped_image(image, base)
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u.mem_map(base, (len(mapped) + 0xfff) & ~0xfff)
        self.u.mem_write(base, mapped)
        self.u.mem_map(DATA, 0x20000)
        self.u.mem_map(STACK, 0x10000)
        self.base = base
        self.next_data = DATA + 0x4000
        self.manager = DATA + 0x1000
        self.root = DATA + 0x1800
        self.windows = [self.root]
        self.window_by_name = {'window_chat': self.root}
        self.missing = missing
        self.children = []
        self.children_by_parent = {self.root: self.children}
        self.names = {}
        self.calls = []
        self.metrics = []
        self.exit = DATA + 0x1ff00
        self.u.hook_add(UC_HOOK_CODE, self.hook)
        self.class_vmt = {name: get32(self.u, self.address(va)) for name, va in (
            ('memo', 0xa2c95c), ('label', 0xa30e38), ('list', 0xa2d28c),
            ('edit', 0xa2fb7c), ('button', 0xa2ecdc),
        )}
        self.class_vmt.update(render=self.address(0xa2c208),
                              pagecontrol=self.address(0xa34c48),
                              page=self.address(0xa33fa0),
                              window=get32(self.u, self.address(0xa319e8)))
        self.u.mem_write(self.root + 0x30, struct.pack('<iiii', 17, 512, 1024, chat_height))
        for va, slot, value in ((0xac622c, DATA + 0x100, self.manager),
                                (0xac56e0, DATA + 0x104, width),
                                (0xac5e60, DATA + 0x108, height)):
            put32(self.u, self.address(va), slot)
            put32(self.u, slot, value)
        put32(self.u, self.address(0xb76650), self.manager)
        for name in ('close_btn', 'btn_refresh', 'btn_search', 'btn_savechatlog',
                     'btn_ignorelist', 'btn_friends', 'btn_settings',
                     'btn_clear_chat', 'btn_hide'):
            self.children.append(self.control('button', name))
        close = self.children[0]
        put32(self.u, self.root + 0x344, close)
        self.children.append(self.control('label', 'ban_chat_mark'))
        self.render = self.control('render', '')
        self.pagecontrol = self.control('pagecontrol', '')
        self.children.extend((self.render, self.pagecontrol))
        self.children_by_parent[self.pagecontrol] = []

    def address(self, preferred_va):
        return self.base + preferred_va - 0x400000

    def allocate(self, size):
        result = self.next_data
        self.next_data += (size + 15) & ~15
        return result

    def control(self, kind, name, x=0, y=0, width=50, height=22):
        c = self.allocate(0x400)
        put32(self.u, c, self.class_vmt[kind])
        self.u.mem_write(c + 0x30, struct.pack('<iiii', x, y, width, height))
        encoded = name.encode('utf-16le')
        s = self.allocate(12 + len(encoded) + 2)
        self.u.mem_write(s, struct.pack('<HHiI', 1200, 2, 1, len(name)) + encoded + b'\0\0')
        put32(self.u, c + 0x68, s + 12)
        self.names[c] = name
        return c

    def text(self, pointer):
        if not pointer:
            return ''
        return bytes(self.u.mem_read(pointer, get32(self.u, pointer - 4) * 2)).decode('utf-16le')

    def return_stub(self):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, get32(self.u, sp))
        self.u.reg_write(UC_X86_REG_ESP, sp + 4)

    def hook(self, u, address, size, _):
        if address == self.exit:
            u.emu_stop()
            return
        va = address - self.base + 0x400000
        eax, edx = u.reg_read(UC_X86_REG_EAX), u.reg_read(UC_X86_REG_EDX)
        if va == 0xa3fca8:
            assert eax == self.manager
            name = self.text(edx)
            window = self.window_by_name.get(name)
            absent = window is None or (name == 'window_chat' and self.missing)
            u.reg_write(UC_X86_REG_EAX, 0xffffffff if absent else self.windows.index(window))
        elif va == 0xa3f2a0:
            assert eax == self.manager and 0 <= edx < len(self.windows)
            u.reg_write(UC_X86_REG_EAX, self.windows[edx])
        elif va == 0xa424d4:
            assert eax in self.children_by_parent
            u.reg_write(UC_X86_REG_EAX, len(self.children_by_parent[eax]))
        elif va == 0xa424c4:
            assert eax in self.children_by_parent
            children = self.children_by_parent[eax]
            assert 0 <= edx < len(children)
            u.reg_write(UC_X86_REG_EAX, children[edx])
        elif va == 0x4095ac:
            u.reg_write(UC_X86_REG_EAX, int(get32(u, eax) == edx))
        elif va == 0x40c354:
            equal = self.text(eax) == self.text(edx)
            flags = u.reg_read(UC_X86_REG_EFLAGS)
            u.reg_write(UC_X86_REG_EFLAGS, (flags & ~0x40) | (0x40 if equal else 0))
        elif va in (0xa4d320, 0xa4c468, 0xa4c3a4, 0xa494ac):
            self.metrics.append((hex(va), eax))
        else:
            return
        self.calls.append(hex(va))
        self.return_stub()

    def execute(self, preferred_va, eax=0):
        for reg, value in zip(PRESERVED, PRESERVED_VALUES):
            self.u.reg_write(reg, value)
        sp = STACK + 0x8000
        put32(self.u, sp, self.exit)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        self.u.reg_write(UC_X86_REG_EAX, eax)
        self.u.reg_write(UC_X86_REG_ECX, 0x56789abc)
        self.u.reg_write(UC_X86_REG_EDX, 0x6789abcd)
        self.u.reg_write(UC_X86_REG_EFLAGS, 0x246)
        self.u.emu_start(self.address(preferred_va), self.exit, count=100000)
        assert self.u.reg_read(UC_X86_REG_EIP) == self.exit
        assert self.u.reg_read(UC_X86_REG_ESP) == sp + 4
        assert tuple(self.u.reg_read(r) for r in PRESERVED) == PRESERVED_VALUES
        if preferred_va in (0xc24000, 0xc24300):
            assert self.u.reg_read(UC_X86_REG_EAX) == eax
            assert self.u.reg_read(UC_X86_REG_ECX) == 0x56789abc
            assert self.u.reg_read(UC_X86_REG_EDX) == 0x6789abcd


def native_chat_cases(image):
    results = []
    for base in (0x400000, 0x10400000):
        for width, height in ((800, 600), (1920, 1080), (3440, 1440), (3840, 2160)):
            for chat_height in (150, 256, 384):
                f = ChatFixture(image, base, width, height, chat_height)
                f.execute(0xa029dc)
                assert get32(f.u, f.root + 0x30) == 0
                assert get32(f.u, f.root + 0x34) == (512 if chat_height == 150 else height-chat_height)
                assert get32(f.u, f.root + 0x38) == width
                assert get32(f.u, f.root + 0x3c) == chat_height
                byname = {f.names[c]: c for c in f.children if f.names[c]}
                assert get32(f.u, byname['btn_refresh']+0x30) == width-0x122
                assert get32(f.u, byname['btn_savechatlog']+0x30) == width-0x40
                assert get32(f.u, byname['ban_chat_mark']+0x30) == width//2-0x18
                for players_visible in (False, True):
                    page = f.control('page', '')
                    put32(f.u, page+0x4c, f.pagecontrol)
                    f.u.mem_write(f.pagecontrol+0x38, struct.pack('<ii', width, chat_height))
                    close = f.control('button', '', height=16)
                    memo = f.control('memo', '', 48, 52, 912, 140)
                    players = f.control('list', '', 976, 52, 240, 166)
                    edit = f.control('edit', 'edit_chat', 46, 196, 800, 22)
                    send = f.control('button', 'send_hack', 862, 196, 100, 25)
                    toggle = f.control('button', 'userlist_hack', 964, 106, 8, 32)
                    f.u.mem_write(players+0x49, bytes([players_visible]))
                    for field, ptr in ((0x288, close), (0x29c, memo), (0x2a0, players),
                                       (0x2a4, edit), (0x2a8, send), (0x2ac, toggle)):
                        put32(f.u, page+field, ptr)
                    messages = f.allocate(128)
                    payload = b'existing global/location/trade messages; preserve their contents'.ljust(128, b'!')
                    f.u.mem_write(messages, payload)
                    put32(f.u, memo+0x2ac, messages)
                    put32(f.u, edit+0x2e0, messages+64)
                    f.execute(0xa4f608, page)
                    memo_width = width-112-(240 if players_visible else 0)
                    assert get32(f.u, memo+0x38) == memo_width
                    assert get32(f.u, memo+0x3c) == chat_height-116
                    assert get32(f.u, edit+0x30) == 46
                    assert get32(f.u, edit+0x34) == chat_height-60
                    assert get32(f.u, edit+0x38) == memo_width-112
                    assert get32(f.u, send+0x30) == 46+memo_width-96
                    assert get32(f.u, send+0x34) == chat_height-60
                    assert get32(f.u, toggle+0x30) == 52+memo_width
                    assert get32(f.u, close+0x34) == 32
                    assert bytes(f.u.mem_read(messages, 128)) == payload
                    assert get32(f.u, memo+0x2ac) == messages
                    assert get32(f.u, edit+0x2e0) == messages+64
                    assert f.metrics[-2:] == [('0xa4d320', memo), ('0xa4c468', memo)]
                results.append({'base': hex(base), 'screen': [width, height],
                                'chatHeight': chat_height, 'nestedStates': 2, 'result': 'PASS'})
        f = ChatFixture(image, base, 1920, 1080, missing=True)
        original = bytes(f.u.mem_read(f.root, 0x400))
        f.execute(0xa029dc)
        assert bytes(f.u.mem_read(f.root, 0x400)) == original
        assert not f.metrics
        results.append({'base': hex(base), 'chatMissing': True, 'result': 'PASS'})
    return results


def generated_chat_helper_cases(image):
    """Execute the product helper against a synthetic current native tree."""
    results = []
    for base in (0x400000, 0x10400000):
        for width, height, chat_height in ((w, h, ch)
                for w, h in ((800, 600), (1920, 1080), (3440, 1440), (3840, 2160))
                for ch in (150, 256, 384)):
            f = ChatFixture(image, base, width, height, chat_height)
            f.u.mem_write(f.root+0x38, struct.pack('<ii', width, chat_height))
            f.u.mem_write(f.render+0x38, struct.pack('<ii', 1024, 256))
            f.u.mem_write(f.pagecontrol+0x38, struct.pack('<ii', 1024, 256))
            empty = f.control('render', '', width=0, height=0)
            invalid_size = f.control('render', '', width=1, height=0)
            f.children.extend((empty, invalid_size))
            pages = []
            memos, edits, pages_controls, sentinels = [], [], [], []
            unrelated = f.control('button', '', 7, 11, 23, 29)
            f.children_by_parent[f.pagecontrol] = pages
            for i in range(9):
                page = f.control('page', '', width=1024, height=256)
                pages.append(page)
                put32(f.u, page+0x4c, f.pagecontrol)
                close = f.control('button', '', height=16)
                memo = f.control('memo', '', 48, 52, 912, 140)
                players = f.control('list', '', 976, 52, 240, 166)
                edit = f.control('edit', 'edit_chat', 46, 196, 800, 22)
                send = f.control('button', 'send_hack', 862, 196, 100, 25)
                toggle = f.control('button', 'userlist_hack', 964, 106, 8, 32)
                visible = bool(i % 2)
                f.u.mem_write(players+0x49, bytes([visible]))
                for field, ptr in ((0x288, close), (0x29c, memo), (0x2a0, players),
                                   (0x2a4, edit), (0x2a8, send), (0x2ac, toggle)):
                    put32(f.u, page+field, ptr)
                memos.append((memo, visible))
                edits.append(edit)
                pages_controls.append((close, players, send, toggle))
                sentinel = f.allocate(128)
                payload = (f'chat tab{i} old messages; unsent input'.encode()).ljust(128, b'!')
                f.u.mem_write(sentinel, payload)
                put32(f.u, memo+0x2ac, sentinel)
                put32(f.u, edit+0x2e0, sentinel+64)
                sentinels.append((sentinel, payload))
            pages.append(unrelated)
            original_unrelated = bytes(f.u.mem_read(unrelated, 0x400))
            f.execute(0xa029dc)
            f.execute(0xc24000, 0x1234)
            assert get32(f.u, f.root+0x34) == height-chat_height+(37 if chat_height == 150 else 0)
            for control in (f.render, f.pagecontrol, *pages[:-1]):
                assert get32(f.u, control+0x38) == width
                assert get32(f.u, control+0x3c) == chat_height
            assert get32(f.u, empty+0x38) == 0 and get32(f.u, empty+0x3c) == 0
            assert get32(f.u, invalid_size+0x38) == 1 and get32(f.u, invalid_size+0x3c) == 0
            assert bytes(f.u.mem_read(unrelated, 0x400)) == original_unrelated
            for (memo, visible), edit, controls, (sentinel, payload) in zip(
                    memos, edits, pages_controls, sentinels):
                close, players, send, toggle = controls
                memo_width = width-112-(240 if visible else 0)
                assert get32(f.u, memo+0x38) == memo_width
                assert get32(f.u, memo+0x3c) == chat_height-116
                assert get32(f.u, edit+0x38) == memo_width-112
                assert get32(f.u, edit+0x34) == chat_height-60
                assert get32(f.u, players+0x38) == 240
                assert get32(f.u, players+0x30) == width-48-(240 if visible else 0)
                assert get32(f.u, players+0x3c) == chat_height-92
                assert get32(f.u, send+0x30) == 46+memo_width-96
                assert get32(f.u, send+0x34) == chat_height-60
                assert get32(f.u, toggle+0x30) == 52+memo_width
                assert get32(f.u, toggle+0x34) == 52+(chat_height-116)//2-16
                assert get32(f.u, close+0x34) == 32
                assert bytes(f.u.mem_read(sentinel, 128)) == payload
                assert get32(f.u, memo+0x2ac) == sentinel
                assert get32(f.u, edit+0x2e0) == sentinel+64
            assert len(f.metrics) == 18
            assert f.u.reg_read(UC_X86_REG_EAX) == 0x1234
            results.append({'base': hex(base), 'screen': [width, height],
                            'chatHeight': chat_height,
                            'pages': 9, 'preservedEmptyOverlays': True,
                            'messagesAndInputPreserved': True, 'result': 'PASS'})
        for missing in ('chat', 'manager_reference', 'manager_object'):
            f = ChatFixture(image, base, 1920, 1080, missing=missing == 'chat')
            if missing == 'manager_reference':
                put32(f.u, f.address(0xac622c), 0)
            elif missing == 'manager_object':
                put32(f.u, DATA+0x100, 0)
            original = bytes(f.u.mem_read(f.root, 0x400))
            f.execute(0xc24000)
            assert bytes(f.u.mem_read(f.root, 0x400)) == original
            assert not f.metrics
            results.append({'base': hex(base), 'absent': missing, 'result': 'PASS'})
    return results


def generated_hud_anchor_cases(image):
    """Verify only positions of existing right-anchored HUD windows change."""
    results = []
    for base in (0x400000, 0x10400000):
        for width, height in ((800, 600), (1920, 1080), (3440, 1440), (3840, 2160)):
            for visible in (False, True):
                f = ChatFixture(image, base, width, height)
                jackpot = f.control('window', 'window_jack_pot_progress', 871, 389, 96, 128)
                mode = f.control('window', 'window_pdamap_modeswitch', 1024, 32, 0, 0)
                for name, window in (('window_jack_pot_progress', jackpot),
                                     ('window_pdamap_modeswitch', mode)):
                    f.windows.append(window)
                    f.window_by_name[name] = window
                    f.children_by_parent[window] = []
                    f.u.mem_write(window+0x49, bytes([visible]))
                    put32(f.u, window+0x2c, DATA+0x1f100)
                expected_jackpot = bytearray(f.u.mem_read(jackpot, 0x400))
                expected_mode = bytearray(f.u.mem_read(mode, 0x400))
                struct.pack_into('<ii', expected_jackpot, 0x30, width-105-48, height-315-64)
                struct.pack_into('<i', expected_mode, 0x30, width)
                f.execute(0xa029dc)
                f.execute(0xc24000, 0x1234)
                f.execute(0xc24300, 0x1234)
                assert bytes(f.u.mem_read(jackpot, 0x400)) == bytes(expected_jackpot)
                assert bytes(f.u.mem_read(mode, 0x400)) == bytes(expected_mode)
                assert f.u.reg_read(UC_X86_REG_EAX) == 0x1234
                results.append({'base': hex(base), 'screen': [width, height],
                                'visible': visible, 'jackpotPosition': [width-153, height-379],
                                'modeSwitchPosition': [width, 32],
                                'onlyCoordinatesChanged': True, 'result': 'PASS'})
        for absent in ('jackpot', 'pda', 'both', 'manager_reference', 'manager_object'):
            f = ChatFixture(image, base, 1920, 1080)
            jackpot = f.control('window', 'window_jack_pot_progress', 871, 389, 96, 128)
            mode = f.control('window', 'window_pdamap_modeswitch', 1024, 32, 0, 0)
            f.windows.extend((jackpot, mode))
            if absent not in ('jackpot', 'both'):
                f.window_by_name['window_jack_pot_progress'] = jackpot
            if absent not in ('pda', 'both'):
                f.window_by_name['window_pdamap_modeswitch'] = mode
            if absent == 'manager_reference':
                put32(f.u, f.address(0xac622c), 0)
            elif absent == 'manager_object':
                put32(f.u, DATA+0x100, 0)
            expected_jackpot = bytearray(f.u.mem_read(jackpot, 0x400))
            expected_mode = bytearray(f.u.mem_read(mode, 0x400))
            if absent not in ('jackpot', 'both', 'manager_reference', 'manager_object'):
                struct.pack_into('<ii', expected_jackpot, 0x30, 1920-153, 1080-379)
            if absent not in ('pda', 'both', 'manager_reference', 'manager_object'):
                struct.pack_into('<i', expected_mode, 0x30, 1920)
            f.execute(0xc24300, 0x1234)
            assert bytes(f.u.mem_read(jackpot, 0x400)) == bytes(expected_jackpot)
            assert bytes(f.u.mem_read(mode, 0x400)) == bytes(expected_mode)
            results.append({'base': hex(base), 'absent': absent,
                            'onlyCoordinatesChanged': True, 'result': 'PASS'})
    return results


def generated_battle_anchor_cases(image):
    """Refresh cached battle coordinates while preserving slot gameplay data."""
    results = []
    for base in (0x400000, 0x10400000):
        for width, height in ((800, 600), (1920, 1080), (3440, 1440), (3840, 2160)):
            for window_width in (288, 289):
                for visible in (False, True):
                    f = ChatFixture(image, base, width, height)
                    topmenu = f.control('window', 'window_topmenu', 362, 0, window_width, 32)
                    f.windows.append(topmenu)
                    f.window_by_name['window_topmenu'] = topmenu
                    f.u.mem_write(topmenu+0x49, bytes([visible]))
                    put32(f.u, topmenu+0x2c, DATA+0x1f200)
                    expected_topmenu = bytearray(f.u.mem_read(topmenu, 0x400))
                    struct.pack_into('<i', expected_topmenu, 0x30, (width-300)//2)
                    expected_slots = []
                    for index in range(9):
                        address = f.address(0xad11e0)+index*0x48
                        payload = bytes((index*29+b*17)%256 for b in range(0x48))
                        f.u.mem_write(address, payload)
                        expected = bytearray(payload)
                        struct.pack_into('<ii', expected, 4,
                                         width-256+(86, 139, 192)[index%3],
                                         height-256+(206, 153, 100)[index//3])
                        expected_slots.append((address, expected))
                    f.execute(0xc24300, 0x1234)
                    assert bytes(f.u.mem_read(topmenu, 0x400)) == bytes(expected_topmenu)
                    for address, expected in expected_slots:
                        assert bytes(f.u.mem_read(address, 0x48)) == bytes(expected)
                    results.append({'base': hex(base), 'screen': [width, height],
                                    'topmenuWidth': window_width, 'visible': visible,
                                    'slotRecords': 9, 'onlyCoordinatesChanged': True,
                                    'result': 'PASS'})
        for absent in ('topmenu', 'manager_reference', 'manager_object'):
            f = ChatFixture(image, base, 1920, 1080)
            if absent == 'manager_reference':
                put32(f.u, f.address(0xac622c), 0)
            elif absent == 'manager_object':
                put32(f.u, DATA+0x100, 0)
            expected_slots = []
            for index in range(9):
                address = f.address(0xad11e0)+index*0x48
                payload = bytes((index*29+b*17)%256 for b in range(0x48))
                f.u.mem_write(address, payload)
                expected = bytearray(payload)
                if absent == 'topmenu':
                    struct.pack_into('<ii', expected, 4,
                                     1920-256+(86, 139, 192)[index%3],
                                     1080-256+(206, 153, 100)[index//3])
                expected_slots.append((address, expected))
            f.execute(0xc24300, 0x1234)
            for address, expected in expected_slots:
                assert bytes(f.u.mem_read(address, 0x48)) == bytes(expected)
            results.append({'base': hex(base), 'absent': absent,
                            'onlyCoordinatesChanged': True, 'result': 'PASS'})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, default=ROOT/'reports/screen-settings/client/silver.dll')
    parser.add_argument('--out', type=Path, default=ROOT/'reports/screen-settings/chat-native-proof.json')
    args = parser.parse_args()
    image = args.candidate.read_bytes()
    cases = native_chat_cases(image)
    helper_cases = generated_chat_helper_cases(image)
    hud_cases = generated_hud_anchor_cases(image)
    battle_cases = generated_battle_anchor_cases(image)
    result = {'result': 'PASS', 'candidateSha256': hashlib.sha256(image).hexdigest(),
              'rootCases': len(cases), 'nestedCases': sum(c.get('nestedStates', 0) for c in cases),
              'nativeFunctions': ['0xa029dc', '0xa02334', '0xa43630', '0xa4f608'],
              'stubs': ['name lookup', 'list lookup', 'class checks', 'Unicode comparison',
                        'message wrapping and scrollbar metrics'],
              'generatedHelperCases': len(helper_cases), 'generatedHelper': '0xc24000',
              'generatedHudCases': len(hud_cases),
              'generatedHudHelper': '0xc24300',
              'generatedBattleCases': len(battle_cases),
              'realClientRenderingVerified': False, 'cases': cases,
              'helperCases': helper_cases, 'hudCases': hud_cases,
              'battleCases': battle_cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f"PASS: {len(cases)} native root, {result['nestedCases']} nested page, "
          f"{len(helper_cases)} generated helper cases")
    print(f"PASS: {len(hud_cases)} generated HUD cases")
    print(f"PASS: {len(battle_cases)} generated battle HUD cases")


if __name__ == '__main__':
    main()
