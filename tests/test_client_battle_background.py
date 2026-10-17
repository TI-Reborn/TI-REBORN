"""Original x86 native enqueue, focus gate, pause gate and callback tick.

Allocation and list insertion are isolated; packet copy, native Focused getter,
queue wakeup, pending lookup and tick gates execute unchanged in Unicorn.
No game window, authentication, transport or server response is simulated.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP

from deploy.client_battle_background import BASE_SHA, PATCHED_SHA, GATE_FILE_OFFSET, GATE_VA, SPAN_VA, IMAGE_BASE, ORIGINAL_SPAN, AFTER, patch, patch_plan, restore

ROOT = Path(__file__).resolve().parents[1]
DATA = 0x2000000
STACK = 0x3000000
STOP = STACK + 0x100
CONTEXT = DATA + 0x1000
LIST = DATA + 0x2000
TABLE = DATA + 0x2100
ROOT_WINDOW = DATA + 0x6000
CALLBACK = DATA + 0xe000
BODY = struct.pack('<I', 0x10000002)


def _original() -> bytes:
    # Read archived/owned native images only after checking the complete hash.
    candidates = (
        ROOT / 'reports/client-version-research/archive-20231004/ti.exe',
        ROOT / 'reports/contracts-local/clients/game-a/ti.exe',
        Path(r'C:\Program Files (x86)\TIOnline\ti.exe'),
    )
    for path in candidates:
        if path.is_file():
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == BASE_SHA:
                return data
            if hashlib.sha256(data).hexdigest() == PATCHED_SHA:
                return restore(data)
    raise unittest.SkipTest('Pinned original native client image is unavailable')


def _enqueue(image: bytes, focused: bool, overlay: int, halted: bool):
    native = pefile.PE(data=image).get_memory_mapped_image()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    for address, size in ((0, 0x1000), (0x400000, (len(native) + 4095) & ~4095),
                          (DATA, 0x10000), (STACK, 0x10000)):
        u.mem_map(address, size)
    u.mem_write(0x400000, native)
    def put(address, value):
        u.mem_write(address, struct.pack('<I', value))
    def get(address):
        return struct.unpack('<I', u.mem_read(address, 4))[0]
    def ret(value=None):
        sp = u.reg_read(UC_X86_REG_ESP)
        u.reg_write(UC_X86_REG_EIP, get(sp))
        u.reg_write(UC_X86_REG_ESP, sp + 4)
        if value is not None:
            u.reg_write(UC_X86_REG_EAX, value)

    put(0x76e17c, DATA + 0x500)
    put(DATA + 0x500, CONTEXT)
    put(CONTEXT + 0x10, LIST)
    put(LIST + 4, TABLE)
    u.mem_write(CONTEXT + 0x19, bytes((int(halted),)))
    put(0x76e568, DATA + 0x510)
    put(DATA + 0x510, ROOT_WINDOW)
    # Real TWinControl VMT/DMT: FFB1 resolves to native Focused getter 5EB000.
    put(ROOT_WINDOW, 0x5d9898)
    put(ROOT_WINDOW + 0x278, 0x1234)
    put(0x76de74, DATA + 0x9000)
    put(0x76e0ac, DATA + 0x9100)
    put(0x76e2ac, DATA + 0x9200)
    u.mem_write(DATA + 0x9200, bytes((overlay,)))
    put(0x76e314, DATA + 0x9300)
    put(DATA + 0x9300, 100)
    put(0x76dccc, DATA + 0x9400)
    put(0x76deb4, DATA + 0x9500)
    u.mem_write(DATA, BODY)
    put(STACK + 0x8000, STOP)
    for i, value in enumerate((0x37, DATA, len(BODY), CALLBACK)):
        put(STACK + 0x8004 + 4 * i, value)
    u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
    heap = DATA + 0x3000
    state = {'focused_getter_executed': False, 'callback_executed': False}
    def hook(uc, address, size, user):
        nonlocal heap
        if address == 0x406a34:
            amount = uc.reg_read(UC_X86_REG_EAX)
            allocated = heap
            heap += (amount + 15) & ~15
            assert heap < DATA + 0x5000
            ret(allocated)
        elif address == 0x4b1c08:
            assert uc.reg_read(UC_X86_REG_EAX) == LIST
            row = uc.reg_read(UC_X86_REG_EDX)
            put(TABLE, row)
            put(LIST + 8, 1)
            state['row'] = row
            ret(0)
        elif address == 0x5eb000:
            state['focused_getter_executed'] = True
        elif address == 0x4141f0:
            # Only GetFocus endpoint; native getter does the HWND comparison.
            ret(0x1234 if focused else 0x5678)
        elif address in (0x7067c4, 0x70cbbc):
            ret(0)  # No animation or external pending work for the tick case.
        elif address == CALLBACK:
            state['callback_executed'] = True
            state['callback_body'] = bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EAX), len(BODY)))
            uc.emu_stop()
        elif address == 0x6f6f63:
            uc.emu_stop()  # Stop after a tick that did not dispatch the callback.
    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(0x71cc6c, STOP, count=12000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    row = state['row']
    state.update(busy=u.mem_read(CONTEXT + 0x18, 1)[0],
                 halted=u.mem_read(CONTEXT + 0x19, 1)[0],
                 queue_count=get(LIST + 8),
                 opcode=struct.unpack('<H', u.mem_read(row + 0x10, 2))[0],
                 callback=get(row + 0xc),
                 copied_body=bytes(u.mem_read(get(row + 0x1c), len(BODY))))
    return u, state


class ClientBattleBackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = _original()
        cls.updated = patch(cls.original)

    def test_exact_two_byte_patch_and_idempotence(self):
        self.assertEqual(hashlib.sha256(self.updated).hexdigest(), PATCHED_SHA)
        self.assertEqual(len(self.original), len(self.updated))
        changes = [i for i, (a, b) in enumerate(zip(self.original, self.updated)) if a != b]
        self.assertEqual(changes, [GATE_FILE_OFFSET, GATE_FILE_OFFSET + 1])
        self.assertEqual(patch(self.updated), self.updated)
        self.assertEqual(restore(self.updated), self.original)
        self.assertEqual(patch_plan(self.original, self.updated)['restored_sha256'], BASE_SHA)

    def test_owned_runtime_helper_matches_the_verified_native_patch(self):
        path = ROOT / 'reports/contracts-local/city-ui/qa-loader/QaMultiClientStarter.cs'
        if not path.is_file():
            self.skipTest('Owned local QA helper source is unavailable')
        source = path.read_text(encoding='utf-8')
        for name, value in (('BackgroundQueueGuardHex', ORIGINAL_SPAN.hex()),
                            ('BackgroundQueueAfterHex', AFTER.hex())):
            match = re.search(r'const string ' + name + r'\s*=\s*"([0-9a-f]+)";', source)
            self.assertIsNotNone(match, name)
            self.assertEqual(match.group(1), value)
            self.assertIn('Convert.FromHexString(' + name + ')', source)
        for name, value in (('BackgroundQueueGateRva', GATE_VA - IMAGE_BASE),
                            ('BackgroundQueueSpanRva', SPAN_VA - IMAGE_BASE)):
            match = re.search(r'const long ' + name + r'\s*=\s*(0x[0-9a-f]+);', source)
            self.assertIsNotNone(match, name)
            self.assertEqual(int(match.group(1), 16), value)
        self.assertIn('ReadProcessMemory(info.process,new IntPtr(0x400000 + BackgroundQueueSpanRva),queueActual', source)
        self.assertIn('WriteProcessMemory(info.process,new IntPtr(0x400000 + BackgroundQueueGateRva),queueWake,2', source)
        self.assertIn('FlushInstructionCache(info.process,new IntPtr(0x400000 + BackgroundQueueGateRva),2)', source)
        self.assertIn('if(kind==3 && nativeMulti)', source)

    def test_unrelated_edits_are_rejected_for_both_forms(self):
        for image in (self.original, self.updated):
            for offset in (0x200, GATE_FILE_OFFSET, GATE_FILE_OFFSET - 1, len(image) - 1):
                with self.subTest(patched=image == self.updated, offset=offset):
                    bad = bytearray(image)
                    bad[offset] ^= 1
                    with self.assertRaises(ValueError):
                        patch(bytes(bad))
        with self.assertRaises(ValueError):
            patch(b'not a PE image')

    def test_original_native_enqueue_focus_overlay_and_pause_matrix(self):
        for patched in (False, True):
            for focused in (False, True):
                for overlay in (0, 1):
                    for halted in (False, True):
                        with self.subTest(patched=patched, focused=focused, overlay=overlay, halted=halted):
                            _, state = _enqueue(self.updated if patched else self.original, focused, overlay, halted)
                            self.assertTrue(state['focused_getter_executed'])
                            self.assertEqual(state['halted'], int(halted))
                            self.assertEqual(state['busy'], int(not halted and (patched or focused or overlay)))
                            self.assertEqual(state['queue_count'], 1)
                            self.assertEqual(state['opcode'], 0x37)
                            self.assertEqual(state['callback'], CALLBACK)
                            self.assertEqual(state['copied_body'], BODY)

    def test_background_callback_drains_on_normal_native_tick(self):
        for patched in (False, True):
            with self.subTest(patched=patched):
                u, state = _enqueue(self.updated if patched else self.original, False, 0, False)
                u.mem_write(STACK + 0x8000, struct.pack('<I', STOP))
                u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
                u.reg_write(UC_X86_REG_EAX, CONTEXT)
                u.emu_start(0x6f6e00, STOP, count=12000)
                self.assertEqual(state['callback_executed'], patched)
                row = state['row']
                self.assertEqual(u.mem_read(row, 1)[0], 3 if patched else 0)
                self.assertEqual(u.mem_read(row + 0x18, 1)[0], int(patched))
                if patched:
                    self.assertEqual(state['callback_body'], BODY)


if __name__ == '__main__':
    unittest.main()
