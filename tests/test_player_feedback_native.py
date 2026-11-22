"""Execute reported UI paths in the exact published x86 image."""
import hashlib
from pathlib import Path
import struct
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EBP, UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESP,
    UC_X86_REG_EDI, UC_X86_REG_ESI,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'reports/player-feedback-20261104/source-silver.dll'
DATA, STACK, STOP = 0x2000000, 0x3000000, 0x3000100


def candidate() -> bytes:
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '617620e4bb082096794f644ffc975c1e7342327a5e8a94ce27d0c2532f3b1c3c'
    patcher = ROOT/'deploy/client_player_feedback.py'
    if patcher.exists():
        from deploy.client_player_feedback import patch
        return patch(raw)
    return raw


class AvatarNativeTests(unittest.TestCase):
    def test_assignment_reaches_the_original_gallery_portrait_field(self):
        for base in (0x400000, 0x1400000):
            with self.subTest(base=base):
                pe = pefile.PE(data=candidate())
                delta = base-0x400000
                pe.relocate_image(base)
                raw = pe.get_memory_mapped_image()
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(base, (len(raw)+4095)&~4095)
                u.mem_write(base, raw)
                u.mem_map(DATA, 0x30000)
                u.mem_map(STACK, 0x10000)

                def put(at, value):
                    u.mem_write(at, struct.pack('<I', value))

                def get(at):
                    return struct.unpack('<I', u.mem_read(at, 4))[0]

                def run(entry):
                    put(STACK+0x8000, STOP)
                    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
                    u.emu_start(entry+delta, STOP, count=3000)
                    self.assertEqual(u.reg_read(UC_X86_REG_EIP), STOP)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK+0x8004)

                slots, actor, selected = DATA+0x1000, DATA+0x2000, DATA+0x9000
                put(0xac618c+delta, slots)
                put(slots, actor)
                put(actor+0x28, 7)
                put(actor+0x278, 0xdeadbeef)
                put(0xac64b4+delta, selected)
                put(selected, 0)
                packet = b'\xfc\x01\x01\x00'+struct.pack('<II', 7, 10007)
                u.mem_write(DATA, packet[1:])
                u.reg_write(UC_X86_REG_EAX, 0xfc)
                u.reg_write(UC_X86_REG_EDX, DATA)
                u.reg_write(UC_X86_REG_ECX, len(packet))
                run(0xc80000)
                self.assertEqual(get(actor+0x60dc), 10007)
                self.assertEqual(get(actor+0x278), 0xdeadbeef)
                rendered = []

                def hook(_u, address, _size, _data):
                    if address not in (0x9bf334+delta, 0x6b0250+delta):
                        return
                    sp = u.reg_read(UC_X86_REG_ESP)
                    if address == 0x6b0250+delta:
                        rendered.append(u.reg_read(UC_X86_REG_ECX))
                    else:
                        u.reg_write(UC_X86_REG_EAX, 1)
                    u.reg_write(UC_X86_REG_EIP, get(sp))
                    u.reg_write(UC_X86_REG_ESP, sp+(12 if address == 0x6b0250+delta else 4))

                u.hook_add(UC_HOOK_CODE, hook)
                run(0x6b06d4)
                self.assertEqual(rendered, [10007])
                # The custom A2 roster must render the same saved portrait.
                frame = STACK+0x7000
                put(frame-12, actor)
                put(frame-4, 100)
                put(frame-8, 200)
                u.reg_write(UC_X86_REG_EBP, frame)
                u.emu_start(0xcc1197+delta, 0xcc11ca+delta, count=3000)
                self.assertEqual(rendered, [10007, 10007])
                self.assertEqual(u.reg_read(UC_X86_REG_EIP), 0xcc11ca+delta)


class LiveLootNativeTests(unittest.TestCase):
    def test_container_close_emits_empty_40_only_outside_live_commit(self):
        import os
        from deploy.client_crate_close import EMPTY_BRANCH, SOURCE_SHA, patch
        from deploy.client_live_loot import STATE
        from tio.protocol.battle_loot import LootTransfer, encode_loot_transfer

        retained = ROOT/'reports/crate-last-ap-20261113/source-silver.dll'
        source = Path(os.environ.get('TIO_CRATE_CLOSE_SOURCE', str(retained if retained.is_file()
                      else Path.home()/'AppData/Local/TIO-Online/silver.dll')))
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
            self.skipTest('Requires original 2026.11.13.1 Silver')
        raw = patch(source.read_bytes())
        for base in (0x400000, 0x1400000):
            delta = base-0x400000
            pe = pefile.PE(data=raw)
            pe.relocate_image(base)
            mapped = pe.get_memory_mapped_image()
            u = Uc(UC_ARCH_X86, UC_MODE_32)
            u.mem_map(base, (len(mapped)+4095)&~4095)
            u.mem_write(base, mapped)
            u.mem_map(DATA, 0x30000)
            u.mem_map(STACK, 0x10000)
            u.mem_map(0, 0x1000)
            obj, handle, vt, flush = (DATA+0x1000, DATA+0x3000,
                                      DATA+0x3100, DATA+0x3200)
            def put(at, value):u.mem_write(at, struct.pack('<I', value))
            def get(at):return struct.unpack('<I', u.mem_read(at, 4))[0]
            put(handle, obj);put(obj, vt);put(vt, flush)
            put(0xac600c+delta, handle)
            wire = []
            def hook(_u, at, _size, _data):
                if at == 0x9dd012+delta:
                    u.emu_stop()
                elif at == 0xa93f70+delta:
                    u.reg_write(UC_X86_REG_EAX, 0xffffffff)
                elif at == 0x6748b0+delta:
                    u.reg_write(UC_X86_REG_EAX, handle)
                elif at == flush:
                    wire.append(bytes(u.mem_read(obj+4, get(obj+0x1004))))
                elif at not in (0x40d748+delta, 0x40c9f4+delta):
                    return
                if at != 0x9dd012+delta:
                    sp = u.reg_read(UC_X86_REG_ESP)
                    u.reg_write(UC_X86_REG_EIP, get(sp))
                    u.reg_write(UC_X86_REG_ESP, sp+4)
            u.hook_add(UC_HOOK_CODE, hook)
            for state, mode, actor, expected in ((0,0,17,True),(2,0,17,False),
                                                  (0,1,17,False),(0,2,17,False),
                                                  (0,0,0,False)):
                with self.subTest(base=base,state=state,mode=mode,actor=actor):
                    wire.clear()
                    put(obj+0x1004,0)
                    put(base+STATE,state)
                    put(0xac4c64+delta,mode)
                    put(0xac4c5c+delta,actor)
                    u.mem_write(0xad27ec+delta,b'\x02\x03')
                    u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
                    u.reg_write(UC_X86_REG_EFLAGS,0x42)
                    u.emu_start(EMPTY_BRANCH+delta,STOP,count=10000)
                    self.assertEqual(u.reg_read(UC_X86_REG_EIP),0x9dd012+delta)
                    self.assertEqual(wire,[encode_loot_transfer(LootTransfer(actor,2,3))] if expected else [])

    def test_frame_waits_for_ack_and_native_writer_emits_nonce_and_direction(self):
        from deploy.client_live_loot import FRAME, STATE, NONCE
        for base in (0x400000, 0x1400000):
            with self.subTest(base=base):
                delta = base-0x400000
                pe = pefile.PE(data=candidate())
                pe.relocate_image(base)
                raw = pe.get_memory_mapped_image()
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(base, (len(raw)+4095)&~4095)
                u.mem_write(base, raw)
                u.mem_map(DATA, 0x30000)
                u.mem_map(STACK, 0x10000)
                u.mem_map(0, 0x1000)
                def put(at, value):u.mem_write(at, struct.pack('<I', value))
                def get(at):return struct.unpack('<I', u.mem_read(at, 4))[0]
                def ret(extra=0):
                    sp = u.reg_read(UC_X86_REG_ESP)
                    u.reg_write(UC_X86_REG_EIP, get(sp))
                    u.reg_write(UC_X86_REG_ESP, sp+4+extra)
                def run(at):
                    put(STACK+0x8000, STOP)
                    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
                    try:u.emu_start(at+delta, STOP, count=10000)
                    except Exception as error:raise AssertionError(hex(u.reg_read(UC_X86_REG_EIP))) from error
                    self.assertEqual(u.reg_read(UC_X86_REG_EIP), STOP)
                obj, handle, vt, flush = (DATA+0x1000, DATA+0x3000,
                                          DATA+0x3100, DATA+0x3200)
                put(handle, obj);put(obj, vt);put(vt, flush)
                put(0xac600c+delta, handle)
                commits = []
                frame_case = [False]
                def hook(_u, at, _size, _data):
                    if at == 0xc26a00+delta:ret()
                    elif at == 0x9dce5c+delta and frame_case[0]:
                        commits.append(1)
                        u.mem_write(base+STATE, b'\x03')
                        ret()
                    elif at == 0x6748b0+delta:
                        u.reg_write(UC_X86_REG_EAX, handle);ret()
                    elif at in (flush, 0x40d748+delta, 0x40d6c8+delta,
                                 0x40c9f4+delta):ret()
                u.hook_add(UC_HOOK_CODE, hook)
                def invalid(uc, access, address, size, value, data):
                    raise AssertionError((hex(uc.reg_read(UC_X86_REG_EIP)), hex(address)))
                u.hook_add(UC_HOOK_MEM_INVALID, invalid)
                # Execute the original 40 writer with one right-to-left move.
                rows = DATA+0x8000
                put(rows-4, 1);put(rows+0x28, 9103);put(rows+0x1c, 5)
                put(STACK+0x8004, rows);put(STACK+0x8008, 0)
                put(base+STATE, 2)
                u.reg_write(UC_X86_REG_EAX, 17)
                u.reg_write(UC_X86_REG_EDX, 2)
                u.reg_write(UC_X86_REG_ECX, 3)
                run(0x98f5cc)
                wire = bytes(u.mem_read(obj+4, get(obj+0x1004)))
                self.assertEqual(wire, b'\xf5' + struct.pack(
                    '<IIBBIIII', 1, 17, 2, 3, 0, 1, 9103, 5))
                self.assertEqual(get(base+NONCE), 1)
                # The next frame sends once; further frames wait for 47.
                frame_case[0] = True
                put(0xac5f18+delta, DATA+0x100)
                put(DATA+0x100, 0);put(0xac4c5c+delta, 17)
                # A character-to-character exchange still commits on its OK.
                put(0xac4c64+delta, 1)
                put(base+STATE, 1)
                run(FRAME)
                self.assertEqual(commits, [])
                put(0xac4c64+delta, 0)
                put(base+STATE, 1)
                run(FRAME);run(FRAME)
                self.assertEqual(commits, [1])
                self.assertEqual(u.mem_read(0xac4c58+delta, 1), b'\x01')
                # Original 47 consumer is stubbed after our dispatcher wrapper.
                def stop_dispatch(_u, at, _size, _data):
                    if at == 0xc800d4+delta:ret()
                u.hook_add(UC_HOOK_CODE, stop_dispatch)
                u.reg_write(UC_X86_REG_EAX, 0x47)
                run(0xc80000)
                self.assertEqual(u.mem_read(base+STATE, 1), b'\0')
                self.assertEqual(u.mem_read(0xac4c58+delta, 1), b'\0')
                # A rejected transfer must release input and discard its window.
                closed = []
                def close_window(_u, at, _size, _data):
                    if at == 0x9b17c0+delta:
                        closed.append(True);ret()
                u.hook_add(UC_HOOK_CODE, close_window)
                put(base+STATE, 2);put(0xac4c58+delta, 1)
                put(DATA+0x9000, 394)
                u.reg_write(UC_X86_REG_EAX, 0xf0)
                u.reg_write(UC_X86_REG_EDX, DATA+0x9000)
                u.reg_write(UC_X86_REG_ECX, 5)
                run(0xc80000)
                self.assertEqual(closed, [True])
                self.assertEqual(u.mem_read(base+STATE, 1), b'\0')
                self.assertEqual(u.mem_read(0xac4c58+delta, 1), b'\0')


class InventoryHotkeyNativeTests(unittest.TestCase):
    def test_battle_key_dispatch_confirms_i_and_escape(self):
        import os
        from deploy.client_equipment_batch import ACTIVE, COUNTER, HIDE_ENTRY, WINDOW
        from deploy.client_inventory_hotkey import ESCAPE_SOURCE_SHA, KEY_CONTINUE, KEY_DISPATCH, patch_escape
        from tio.protocol.equipment_batch import COMMIT, EquipmentBatchRequest, encode_equipment_batch

        retained = ROOT/'reports/inventory-escape-20261113/source-silver.dll'
        source = Path(os.environ.get('TIO_HOTKEY_SOURCE', str(retained if retained.is_file()
                      else ROOT/'reports/inventory-keys-20261113/candidate-silver.dll')))
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != ESCAPE_SOURCE_SHA:
            self.skipTest('Requires original 2026.11.13.4 Silver')
        raw = patch_escape(source.read_bytes())
        for base in (0x400000, 0x1400000):
            delta = base-0x400000
            pe = pefile.PE(data=raw)
            pe.relocate_image(base)
            image = pe.get_memory_mapped_image()
            u = Uc(UC_ARCH_X86, UC_MODE_32)
            u.mem_map(base, (len(image)+4095)&~4095)
            u.mem_write(base, image)
            u.mem_map(DATA, 0x10000)
            u.mem_map(STACK, 0x10000)
            obj, handle, table, flush, window, battle = (DATA+n for n in
                                                        (0x1000,0x3000,0x3100,0x3200,0x4000,0x5000))
            def put(at, value):u.mem_write(at, struct.pack('<I', value))
            def get(at):return struct.unpack('<I', u.mem_read(at,4))[0]
            put(handle,obj);put(obj,table);put(table,flush)
            put(0xac600c+delta,handle);put(0xac64a0+delta,battle)
            put(battle,1);put(base+COUNTER,17);put(base+WINDOW,window)
            wire, hidden, stock = [], [], []
            def hook(_u, at, _size, _data):
                if at in (KEY_CONTINUE+delta, 0x9f5153+delta):
                    u.emu_stop()
                    return
                if at == 0x6748b0+delta:
                    u.reg_write(UC_X86_REG_EAX,handle)
                elif at == flush:
                    wire.append(bytes(u.mem_read(obj+4,get(obj+0x1004))))
                elif at == 0xa4370c+delta:
                    hidden.append((u.reg_read(UC_X86_REG_EAX),get(base+ACTIVE)))
                    u.reg_write(UC_X86_REG_EAX,window+0x2e8)
                    u.reg_write(UC_X86_REG_EIP,HIDE_ENTRY+delta)
                    return
                elif at == 0xa3fe48+delta:
                    stock.append((u.reg_read(UC_X86_REG_EDX),u.reg_read(UC_X86_REG_ECX)))
                elif at != 0xa54980+delta:
                    return
                sp = u.reg_read(UC_X86_REG_ESP)
                u.reg_write(UC_X86_REG_EIP,get(sp));u.reg_write(UC_X86_REG_ESP,sp+4)
            u.hook_add(UC_HOOK_CODE,hook)
            for key, mods, active, visible, operation in (
                    (0x49,0,1,1,COMMIT),(0x1b,0,1,1,COMMIT),(0x1b,0,0,1,None),
                    (0x49,0,0,1,None),(0x49,4,1,1,None),(0x49,0,1,0,None),
                    (0x1b,0,1,0,None),(0x41,0,1,1,None)):
                with self.subTest(base=base,key=key,mods=mods,active=active,visible=visible):
                    wire.clear();hidden.clear();stock.clear()
                    put(obj+0x1004,0);put(base+ACTIVE,active);put(window+0x49,visible)
                    u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
                    u.reg_write(UC_X86_REG_EDI,key)
                    u.reg_write(UC_X86_REG_ESI,mods)
                    u.emu_start(KEY_DISPATCH+delta,STOP,count=4000)
                    handled = visible and not mods and key in (0x49,0x1b)
                    expected_ip = 0x9f5153 if handled else KEY_CONTINUE
                    self.assertEqual(u.reg_read(UC_X86_REG_EIP),expected_ip+delta)
                    self.assertEqual(wire,[encode_equipment_batch(EquipmentBatchRequest(operation,17))]
                                     if operation is not None else [])
                    self.assertEqual(hidden,[(window,0)] if handled else [])
                    self.assertEqual(stock,[] if handled else [(key,mods)])


class ItemAlignmentNativeTests(unittest.TestCase):
    def test_compact_item_origin_preserves_the_native_call_contract(self):
        raw = candidate()
        patcher = ROOT/'deploy/client_item_alignment.py'
        if patcher.exists():
            from deploy.client_item_alignment import patch
            raw = patch(raw)
        for base in (0x400000, 0x1400000):
            with self.subTest(base=base):
                delta = base-0x400000
                pe = pefile.PE(data=raw)
                pe.relocate_image(base)
                mapped = pe.get_memory_mapped_image()
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(base, (len(mapped)+4095)&~4095)
                u.mem_write(base, mapped)
                u.mem_map(DATA, 0x1000)
                u.mem_map(STACK, 0x10000)
                arguments = (0xffffffff, 0, 1, 1, 0, 0, 1)
                sp = STACK+0x8000
                u.mem_write(sp, struct.pack('<8I', STOP, *arguments))
                u.reg_write(UC_X86_REG_ESP, sp)
                u.reg_write(UC_X86_REG_EAX, 200)
                u.reg_write(UC_X86_REG_EDX, 300)
                u.reg_write(UC_X86_REG_ECX, DATA)
                calls = []
                def original(_u, at, _size, _data):
                    if at != 0xca1c00+delta:
                        return
                    stack = u.reg_read(UC_X86_REG_ESP)
                    calls.append((u.reg_read(UC_X86_REG_EAX),
                                  u.reg_read(UC_X86_REG_EDX),
                                  u.reg_read(UC_X86_REG_ECX),
                                  struct.unpack('<7I', u.mem_read(stack+4, 28))))
                    destination, = struct.unpack('<I', u.mem_read(stack, 4))
                    u.reg_write(UC_X86_REG_EIP, destination)
                    u.reg_write(UC_X86_REG_ESP, stack+32)
                    u.reg_write(UC_X86_REG_EAX, 1)
                u.hook_add(UC_HOOK_CODE, original)
                u.emu_start(0xa777e0+delta, STOP, count=2000)
                self.assertEqual(calls, [(198, 300, DATA, arguments)])
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), 1)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), sp+32)



if __name__ == '__main__':
    unittest.main()
