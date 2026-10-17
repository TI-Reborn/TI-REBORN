"""Execute original95d39c and its real x87 distance helper; selection isolated.

This establishes a same-cell gate for this caller, not the meaning of opcode46.
The outbound writer is observed at its entry; its bytes have a separate probe.
"""
from verify_auth_native import *


def run(x, y, *, mode=5, selected=True):
    u = emulator()
    actor = DATA + 0x1000
    put32(u, 0xac5a30, DATA + 0x100)
    u.mem_write(DATA + 0x100, bytes((mode,)))
    put32(u, 0xac618c, DATA + 0x200)
    put32(u, DATA + 0x200, actor)
    put32(u, actor + 0x28, 17)
    put32(u, actor + 0x603c, 2)
    put32(u, actor + 0x6040, 3)
    put32(u, 0xad08a4, x)
    put32(u, 0xad08a8, y)
    calls = []
    distances = []

    def hook(uc, address, size, user):
        if address == 0xa843d4:
            uc.reg_write(UC_X86_REG_EAX, 0 if selected else 0xffffffff)
            return_from_stub(uc)
        elif address == 0x95d3fb:
            distances.append(uc.reg_read(UC_X86_REG_EAX) & 0xffff)
        elif address == 0x95e114:
            calls.append([uc.reg_read(UC_X86_REG_EAX),
                          uc.reg_read(UC_X86_REG_EDX),
                          uc.reg_read(UC_X86_REG_ECX)])
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(0x95d39c, STOP, count=500)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    expected = [[17, x, y]] if mode == 5 and selected and (x, y) == (2, 3) else []
    assert calls == expected, (x, y, distances, calls)
    return dict(target=[x, y], mode=mode, selected=selected,
                rounded_distance=distances, writer_calls=calls)


if __name__ == '__main__':
    cases = [run(2, 3), run(3, 3), run(2, 4), run(3, 4),
             run(5, 7), run(2, 3, mode=4), run(2, 3, selected=False)]
    assert cases[4]['rounded_distance'] == [5]
    (ROOT / 'evidence/battle_position_gate_native.json').write_text(
        json.dumps(dict(sha256=EXPECTED_SHA, method=__doc__, cases=cases,
                        limitation='Other caller9b8008 and action semantics remain unresolved.'),
                   indent=2) + '\n', encoding='utf-8')
    print('Original coordinate caller: 7 distance/mode/selection cases PASS')
