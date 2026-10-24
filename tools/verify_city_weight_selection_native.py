"""Execute original status6/7 selection and redraw paths with UI calls stubbed.

Actor lookup is supplied by the fixture. Original selection branches and
scale-call arguments execute unchanged; this is not graphical-client QA.
"""
import json
import struct

from verify_auth_native import (DATA, STACK, STOP, emulator, get32, put32,
                                return_from_stub, UC_HOOK_CODE)
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                              UC_X86_REG_ESP, UC_X86_REG_EIP)
from tio.protocol.binary import Reader
from tio.weight import encode_weight


def redraws(packets: tuple[bytes, ...], selected: int) -> list[dict]:
    machine = emulator()
    slots = DATA + 0x100
    put32(machine, 0xac618c, slots)
    put32(machine, 0xac64b4, DATA + 0x200)
    put32(machine, DATA + 0x200, selected)
    for index, (weight, capacity) in enumerate(((136, 1470), (0, 1000))):
        actor = DATA + 0x1000 + index * 0x7000
        put32(machine, slots + index * 4, actor)
        machine.mem_write(actor + 0x1e, bytes((index,)))
        put32(machine, actor + 0x6020, weight)
        put32(machine, actor + 0x6024, capacity)
    result = []

    def hook(uc, address, size, user):
        if address == 0xa93f70:
            uc.reg_write(UC_X86_REG_EAX, uc.reg_read(UC_X86_REG_EAX) - 1)
            return_from_stub(uc)
        elif address == 0x66754c:
            uc.reg_write(UC_X86_REG_EAX, 1)  # City / mercenary selection.
            return_from_stub(uc)
        elif address == 0x9b6ef0:
            sp = uc.reg_read(UC_X86_REG_ESP)
            result.append(dict(slot=uc.reg_read(UC_X86_REG_EAX),
                               capacity=uc.reg_read(UC_X86_REG_ECX),
                               weight=struct.unpack('<f', uc.mem_read(sp + 8, 4))[0]))
            return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP) + 8)
        elif address == 0x9b0090:
            return_from_stub(uc)
        elif address == 0x8c7c99:
            uc.emu_stop()  # Stop before unrelated string/UI cleanup.

    machine.hook_add(UC_HOOK_CODE, hook)
    for packet in packets:
        reader = Reader(packet)
        assert reader.u8() == 0x4e
        owner, count = reader.u32(), reader.u32()
        for _ in range(count):
            attribute, value = reader.u32(), reader.u32()
            put32(machine, STACK + 0x8000, STOP)
            machine.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
            machine.reg_write(UC_X86_REG_EAX, owner)
            machine.reg_write(UC_X86_REG_EDX, attribute)
            machine.reg_write(UC_X86_REG_ECX, value)
            machine.emu_start(0x8c7320, STOP, count=5000)
            assert machine.reg_read(UC_X86_REG_EIP) == 0x8c7c99
        assert reader.u8() == 0
        reader.finish()
    return result


def main() -> None:
    old = (encode_weight(1, 136, 1470), encode_weight(2, 0, 1000))
    fixed = (encode_weight(1, 136), encode_weight(2, 0))
    cases = []
    for selected in (0, 1):
        before = redraws(old, selected)
        after = redraws(fixed, selected)
        assert any(row['slot'] != selected for row in before)
        assert after == [dict(slot=selected, weight=136.0 if selected == 0 else 0.0,
                              capacity=1470 if selected == 0 else 1000)]
        cases.append(dict(selected=selected, before=before, after=after))
    print(json.dumps(dict(passed=True, cases=cases, graphical_client=False)))


if __name__ == '__main__':
    main()
