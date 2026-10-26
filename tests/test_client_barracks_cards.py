"""Execute completed-click selection and guard drag/native input contracts."""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

from deploy import client_barracks_a2 as a2
from deploy import client_barracks_cards as cards
def check(base, active, owned, button, dx, dy, x, y, selected, scroll=0):
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(base, 0x900000)
    u.mem_write(base+a2.REGION+0x30000, cards.payload(a2.REGION+0x30000, a2.STATE))
    u.mem_map(0x30000000, 0x40000)

    def va(value):
        return base+value-0x400000

    def put(address, value):
        u.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(address):
        return struct.unpack('<I', u.mem_read(address, 4))[0]

    header, other, roster, actor = 0x30001000, 0x30002000, 0x30003000, 0x30004000
    control = header if owned else other
    put(va(0xac4bdc), header)
    put(va(0x400000+a2.STATE), active)
    put(control+0x30, 100)
    put(control+0x34, 10)
    put(control+0x280, roster)
    put(control+0x284, 0x30000200)
    u.mem_write(0x30000200+0x2a4, struct.pack('<f', float(scroll)))
    put(roster-4, 4)
    for i in range(4):
        put(roster+4*i, actor+0x7000*i)
        put(actor+0x7000*i+0x28, 10+i)
    put(va(0xac618c), roster)
    put(va(0xac64b4), 0x30000100)
    put(0x30000100, selected)
    calls = []
    current = {}

    def hook(uc, address, size, unused):
        if address == va(0x407438):
            sp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EAX, scroll)
            uc.reg_write(UC_X86_REG_EIP, get(sp))
            uc.reg_write(UC_X86_REG_ESP, sp+4)
            return
        if address not in (va(0x8d1ec0), va(0x8d1f80), va(0x8d2b7c)):
            return
        sp = uc.reg_read(UC_X86_REG_ESP)
        if address == va(0x8d2b7c):
            assert uc.reg_read(UC_X86_REG_EAX) == control
            calls.append(uc.reg_read(UC_X86_REG_EDX))
            extra = 0
        else:
            assert uc.reg_read(UC_X86_REG_EAX) == control
            assert uc.reg_read(UC_X86_REG_EDX) == button
            assert uc.reg_read(UC_X86_REG_ECX) == current['x']
            assert get(sp+4) == current['y']
            extra = 4
        uc.reg_write(UC_X86_REG_EIP, get(sp))
        uc.reg_write(UC_X86_REG_ESP, sp+4+extra)

    u.hook_add(UC_HOOK_CODE, hook)
    for release in (False, True):
        sp, stop = 0x3003f000, 0x3003ff00
        current.update(x=x+(dx if release else 0), y=y+(dy if release else 0))
        put(sp, stop)
        put(sp+4, current['y'])
        for reg, value in ((UC_X86_REG_EAX, control), (UC_X86_REG_EDX, button),
                           (UC_X86_REG_ECX, current['x']), (UC_X86_REG_EBX, 111),
                           (UC_X86_REG_ESI, 222), (UC_X86_REG_EDI, 333),
                           (UC_X86_REG_EBP, 444), (UC_X86_REG_ESP, sp)):
            u.reg_write(reg, value)
        u.emu_start(va(0x400000+a2.REGION+0x30000+(0xc00 if release else 0x900)), stop, count=10000)
        assert u.reg_read(UC_X86_REG_ESP) == sp+8
        assert [u.reg_read(reg) for reg in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)] == [111, 222, 333, 444]
    valid = active and owned and button == 0 and abs(dx) <= 3 and abs(dy) <= 3
    position = current['x']-105+scroll
    column = position//260
    valid = valid and 0 <= column < 4 and position % 260 < 250 and 15 <= current['y'] < 99
    expected = [10+column] if valid and selected != column else []
    assert calls == expected, (calls, expected, current)


class RosterInputTests(unittest.TestCase):
    def test_completed_click_selects_and_drag_and_foreign_input_keep_native_contract(self):
        for base in (0x400000, 0x10400000):
            for column in range(4):
                for active, owned, button, dx, dy, y in (
                    (1, True, 0, 0, 0, 50), (1, True, 0, 3, -3, 50),
                    (1, True, 0, 4, 0, 50), (1, True, 0, 0, 4, 50),
                    (0, True, 0, 0, 0, 50), (1, False, 0, 0, 0, 50),
                    (1, True, 1, 0, 0, 50), (1, True, 0, 0, 0, 99),
                ):
                    check(base, active, owned, button, dx, dy, 120+260*column, y, 31)
                check(base, 1, True, 0, 0, 0, 120+260*column, 50, column)
            check(base, 1, True, 0, 0, 0, 120, 50, 31, scroll=520)
            check(base, 1, True, 0, 0, 0, 355, 50, 31)

if __name__ == "__main__":
    unittest.main()
