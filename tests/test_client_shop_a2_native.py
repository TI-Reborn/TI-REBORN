"""A2 shop routines execute in Unicorn against fixture shop and warehouse objects."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

from deploy import client_shop_a2 as shop

ORIGIN, STATE = 0x8d0000, 0x89ff00
HEAP = 0x30000000
VAR, PANEL, WINDOW, KIDS, LIST, PAGE = (HEAP + n*0x1000 for n in range(6))
STOCK_MANAGER, STOCK_LIST, ENTRIES, RECORDS, SOLDIER_RECORDS = (HEAP + 0x8000 + n*0x100 for n in range(5))
SOLDIER, SELECTED_VAR, SOLDIER_ARRAY = HEAP + 0x9000, HEAP + 0x9100, HEAP + 0x9200
CHILD = HEAP + 0x10000
RETURN = HEAP + 0x3ff00
NATIVE_CALLS = (shop.SET_ITEMS, shop.REQUEST_STOCK, shop.SET_CAPTION, shop.CLICK, shop.BUTTON_DRAW,
                0x917fd4, 0x917690)


def child(index):
    return CHILD + index*0x400


class Machine:
    def __init__(self, *, enabled=1, visible=1):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0x400000, 0x900000)
        self.uc.mem_map(HEAP, 0x40000)
        self.uc.mem_write(0x400000+ORIGIN, shop.payload(ORIGIN, STATE, shop.BUTTON_DRAW))
        self.put(0x400000+STATE, enabled)
        self.put(shop.SHOP_PANEL, VAR)
        self.put(VAR, PANEL)
        self.put(PANEL+4, WINDOW)
        self.put(WINDOW+0x2c, KIDS)
        self.put(KIDS+4, LIST)
        self.put(KIDS+8, shop.CHILDREN)
        self.uc.mem_write(WINDOW+0x49, bytes((visible,)))
        for index in range(shop.CHILDREN):
            self.put(LIST+4*index, child(index))
            self.uc.mem_write(child(index)+0x49, b'\x01')
        self.put(WINDOW+0x38, 832)
        self.put(WINDOW+0x3c, 448)
        # Page of the A2 barracks: HEADER -> header object whose parent is the page.
        self.put(shop.HEADER, HEAP+0xa000)
        self.put(HEAP+0xa000+0x4c, PAGE)
        for offset, value in zip((0x30, 0x34, 0x38, 0x3c), (146, 72, 1728, 768)):
            self.put(PAGE+offset, value)
        # Warehouse lists: a clan entry first, then the personal (kind 0) one.
        self.put(shop.STOCKS, HEAP+0xb000)
        self.put(HEAP+0xb000, STOCK_MANAGER)
        self.put(STOCK_MANAGER+0x28, STOCK_LIST)
        self.put(STOCK_LIST+4, ENTRIES)
        self.put(STOCK_LIST+8, 2)
        for index, (kind, records) in enumerate(((1, 0x1234), (0, RECORDS))):
            entry = HEAP+0xc000+index*0x10
            self.put(ENTRIES+4*index, entry)
            self.uc.mem_write(entry, bytes((kind,)))
            self.put(entry+4, records)
        self.put(shop.SELECTED, SELECTED_VAR)
        self.put(SELECTED_VAR, 2)
        self.put(shop.SOLDIERS, SOLDIER_ARRAY)
        self.put(SOLDIER_ARRAY+8, SOLDIER)
        self.put(SOLDIER+0x28, 7)
        self.put(SOLDIER+0x6c, SOLDIER_RECORDS)
        self.calls = []
        self.uc.hook_add(UC_HOOK_CODE, self.native)

    def put(self, address, value):
        self.uc.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def state(self, offset):
        return self.get(0x400000+ORIGIN+offset)

    def visible(self, index):
        return self.uc.mem_read(child(index)+0x49, 1)[0]

    def native(self, uc, address, size, unused):
        reads = (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX)
        if address in NATIVE_CALLS or address in (shop.ABSOLUTE_X, shop.ABSOLUTE_Y, shop.TEXT, 0x4f2888):
            self.calls.append((address, *(uc.reg_read(r) for r in reads)))
            if address in (shop.ABSOLUTE_X, shop.ABSOLUTE_Y):
                uc.reg_write(UC_X86_REG_EAX, 100)
            sp = uc.reg_read(UC_X86_REG_ESP)
            extra = {shop.TEXT: 12, 0x4f2888: 16}.get(address, 0)
            uc.reg_write(UC_X86_REG_EIP, self.get(sp))
            uc.reg_write(UC_X86_REG_ESP, sp+4+extra)

    def run(self, entry, **registers):
        self.put(HEAP+0x3f000, RETURN)
        self.uc.reg_write(UC_X86_REG_ESP, HEAP+0x3f000)
        for name, value in registers.items():
            self.uc.reg_write({'eax': UC_X86_REG_EAX, 'esi': UC_X86_REG_ESI, 'ebx': UC_X86_REG_EBX,
                               'edi': UC_X86_REG_EDI}[name], value)
        self.uc.emu_start(entry, RETURN, count=200000)

    def called(self, target):
        return [call[1:] for call in self.calls if call[0] == target]


def at(offset):
    return shop.BASE+ORIGIN+offset


class OwnerTests(unittest.TestCase):
    def owner(self, *, mode, enabled=1, visible=1):
        machine = Machine(enabled=enabled, visible=visible)
        machine.put(0x400000+ORIGIN+shop.MODE, mode)
        request, pet = HEAP+0xd000, HEAP+0xd100
        machine.put(pet+0x28, 5)
        machine.uc.reg_write(UC_X86_REG_ESI, request)
        machine.uc.reg_write(UC_X86_REG_EAX, pet)
        resume = shop.OWNER_SITES[0] + len(bytes.fromhex(shop.OWNER_CODE))
        machine.uc.reg_write(UC_X86_REG_ESP, HEAP+0x3f000)
        machine.uc.emu_start(at(shop.OWNER_ENTRY), resume, count=1000)
        self.assertEqual(machine.uc.reg_read(UC_X86_REG_ESP), HEAP+0x3f000)
        return machine.get(request+0xc)

    def test_warehouse_mode_requests_owner_zero(self):
        self.assertEqual(self.owner(mode=1), 0)

    def test_soldier_mode_keeps_the_selected_soldier(self):
        self.assertEqual(self.owner(mode=0), 5)

    def test_hidden_shop_or_original_interface_keep_the_soldier(self):
        self.assertEqual(self.owner(mode=1, visible=0), 5)
        self.assertEqual(self.owner(mode=1, enabled=0), 5)


class BackpackTests(unittest.TestCase):
    def test_stock_fill_uses_the_personal_warehouse_with_owner_zero(self):
        machine = Machine()
        machine.run(at(shop.FILL_STOCK))
        self.assertEqual(machine.called(shop.SET_ITEMS), [(PANEL, 0, RECORDS)])

    def test_soldier_fill_uses_the_selected_soldier(self):
        machine = Machine()
        machine.run(at(shop.FILL_SOLDIER))
        self.assertEqual(machine.called(shop.SET_ITEMS), [(PANEL, 2, SOLDIER_RECORDS)])


class SwitchTests(unittest.TestCase):
    def opened(self):
        machine = Machine()
        machine.run(at(shop.SHOW), eax=WINDOW)
        machine.calls.clear()
        return machine

    def test_opening_fills_the_page_in_soldier_mode(self):
        machine = Machine()
        machine.put(0x400000+ORIGIN+shop.MODE, 1)
        machine.run(at(shop.SHOW), eax=WINDOW)
        self.assertEqual([machine.get(WINDOW+o) for o in (0x30, 0x34, 0x38, 0x3c)], [146, 72, 1728, 768])
        self.assertEqual(machine.state(shop.MODE), 0)
        self.assertEqual(machine.called(shop.SET_ITEMS), [(PANEL, 2, SOLDIER_RECORDS)])
        rect = shop.layout(1728, 768, warehouse=False)[shop.BAG]
        self.assertEqual([machine.get(child(shop.BAG)+o) for o in (0x30, 0x34, 0x38, 0x3c)],
                         [rect.x, rect.y, rect.width, rect.height])

    def test_a_too_small_page_restores_the_native_shop(self):
        machine = self.opened()
        machine.run(at(shop.CLICK_ENTRY), eax=child(shop.SWITCH))
        machine.put(PAGE+0x38, 1100)
        machine.run(at(shop.SHOW), eax=WINDOW)
        self.assertEqual((machine.get(WINDOW+0x38), machine.get(WINDOW+0x3c)), shop.NATIVE_SIZE)
        self.assertEqual([machine.get(child(shop.BAG)+o) for o in (0x30, 0x34, 0x38, 0x3c)],
                         list(shop.NATIVE[shop.BAG]))
        self.assertEqual((machine.state(shop.MODE), machine.state(shop.LAID_OUT) & 0xff), (0, 0))
        self.assertEqual(machine.visible(shop.PREVIOUS), 1)

    def test_switch_click_shows_the_warehouse_and_hides_the_soldier(self):
        machine = self.opened()
        machine.run(at(shop.CLICK_ENTRY), eax=child(shop.SWITCH))
        self.assertEqual(machine.state(shop.MODE), 1)
        # REQUEST_STOCK reads only AL (kind 0) and DL (force).
        self.assertEqual([(eax & 0xff, edx & 0xff) for eax, edx, _ in machine.called(shop.REQUEST_STOCK)], [(0, 1)])
        self.assertEqual(machine.called(shop.SET_ITEMS)[-1], (PANEL, 0, RECORDS))
        self.assertEqual(machine.called(shop.CLICK), [])
        for index in shop.SOLDIER_ONLY:
            self.assertEqual(machine.visible(index), 0, index)

    def test_switching_back_restores_the_soldier_controls(self):
        machine = self.opened()
        machine.uc.mem_write(child(20)+0x49, b'\x00')  # a hidden fitting row stays hidden
        machine.run(at(shop.CLICK_ENTRY), eax=child(shop.SWITCH))
        machine.run(at(shop.CLICK_ENTRY), eax=child(shop.SWITCH))
        self.assertEqual(machine.state(shop.MODE), 0)
        self.assertEqual(machine.visible(shop.PREVIOUS), 1)
        self.assertEqual(machine.visible(20), 0)
        self.assertEqual(machine.called(shop.SET_ITEMS)[-1], (PANEL, 2, SOLDIER_RECORDS))

    def test_other_buttons_keep_their_native_click(self):
        machine = self.opened()
        machine.run(at(shop.CLICK_ENTRY), eax=child(shop.BUY))
        self.assertEqual(machine.called(shop.CLICK)[0][0], child(shop.BUY))
        self.assertEqual(machine.state(shop.MODE), 0)

    def test_original_interface_leaves_the_switch_native(self):
        machine = Machine(enabled=0)
        machine.run(at(shop.CLICK_ENTRY), eax=child(shop.SWITCH))
        self.assertEqual(machine.called(shop.CLICK)[0][0], child(shop.SWITCH))
        self.assertEqual(machine.state(shop.MODE), 0)


class RefreshTests(unittest.TestCase):
    def test_wrapped_calls_run_natively_and_mark_the_view(self):
        for index, (_, target) in enumerate(shop.REFRESH_SITES):
            machine = Machine()
            machine.run(at(shop.REFRESH_ENTRY+index*0x100), eax=0x1111)
            self.assertEqual(machine.called(target)[0][0], 0x1111)
            self.assertEqual(machine.state(shop.DIRTY) & 0xff, 1)

    def test_switch_draw_refills_a_marked_warehouse_view(self):
        machine = Machine()
        machine.run(at(shop.SHOW), eax=WINDOW)
        machine.run(at(shop.CLICK_ENTRY), eax=child(shop.SWITCH))
        machine.put(0x400000+ORIGIN+shop.DIRTY, 1)
        machine.calls.clear()
        machine.run(at(shop.DRAW_ENTRY), eax=child(shop.SWITCH))
        self.assertEqual(machine.called(shop.SET_ITEMS), [(PANEL, 0, RECORDS)])
        self.assertEqual(machine.state(shop.DIRTY) & 0xff, 0)
        self.assertEqual(machine.called(shop.BUTTON_DRAW), [])

    def test_draw_follows_a_recentred_window(self):
        machine = Machine()
        machine.run(at(shop.SHOW), eax=WINDOW)
        machine.put(WINDOW+0x38, 832)
        machine.run(at(shop.DRAW_ENTRY), eax=child(shop.SWITCH))
        self.assertEqual(machine.get(WINDOW+0x38), 1728)


class PayloadTests(unittest.TestCase):
    def test_payload_fits_and_keeps_state_clear(self):
        raw = shop.payload(ORIGIN, STATE, shop.BUTTON_DRAW)
        self.assertEqual(len(raw), shop.SIZE)
        self.assertEqual(raw[shop.MODE:], bytes(shop.SIZE-shop.MODE))
        for entry in (shop.SHOW, shop.APPLY, shop.RESTORE, shop.CLICK_ENTRY, shop.FILL_STOCK,
                      shop.FILL_SOLDIER, shop.OWNER_ENTRY, shop.REFRESH_ENTRY, shop.DRAW_ENTRY):
            self.assertNotEqual(raw[entry], 0, hex(entry))

    def test_buy_captions_are_wide_strings(self):
        raw = shop.payload(ORIGIN, STATE, shop.BUTTON_DRAW)
        for index, caption in enumerate(shop.BUY_CAPTIONS):
            at = shop.STRINGS+index*0x100
            length = struct.unpack_from('<I', raw, at)[0]
            self.assertEqual(raw[at+4:at+4+length].decode('utf-16le'), caption)


if __name__ == '__main__':
    unittest.main()
