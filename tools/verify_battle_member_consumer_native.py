"""Execute original a0a29c slot selection; record conversion and UI are isolated.

This verifies membership routing, not a09b78 nested conversion or live UI.
"""
from verify_auth_native import *


def run(initial, incoming, mode=0, flag=1, gate=0):
    u = emulator()
    root, slots, settings, marker = (DATA + n for n in (0x2000, 0x3000, 0x5000, 0x6000))
    u.mem_write(root, bytes((mode, 1, flag, 1)))
    put32(u, root + 8, len(incoming))
    for address, value in ((0xac62a4, slots), (0xac6008, settings), (0xac585c, marker)):
        put32(u, address, value)
    for index, character in enumerate(initial):
        u.mem_write(slots + index * 0x1c0, b'\x01')
        put32(u, slots + index * 0x1c0 + 4, character)
    selected, updates, transitions = [], [], []

    def hook(uc, address, size, user):
        eax = uc.reg_read(UC_X86_REG_EAX)
        if address in (0x40c8cc, 0x40c9a4):
            return_from_stub(uc)
        elif address == 0x64e9a4:  # managed record copy only
            index = uc.reg_read(UC_X86_REG_EDX)
            target = uc.reg_read(UC_X86_REG_ECX)
            put32(uc, target, incoming[index])
            uc.mem_write(target + 4, b'\x01')
            return_from_stub(uc)
        elif address == 0xa09b78:  # conversion isolated, preserve observed slot writes
            parent = get32(uc, uc.reg_read(UC_X86_REG_ESP) + 4)
            character = get32(uc, parent - 0x138)
            selected.append([eax, character])
            uc.mem_write(slots + eax * 0x1c0, b'\x01')
            put32(uc, slots + eax * 0x1c0 + 4, character)
            return_from_stub(uc)
        elif address == 0xa0ac58:
            updates.append(True)
            return_from_stub(uc)
        elif address == 0x66754c:
            uc.reg_write(UC_X86_REG_EAX, gate)
            return_from_stub(uc)
        elif address == 0x7d0be8:
            transitions.append(True)
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, root)
    u.emu_start(0xa0a29c, STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert bytes(u.mem_read(marker, 1)) == b'\x01'
    assert bytes(u.mem_read(settings + 0x18, 1)) == bytes((1 if mode == 12 else flag,))
    return {'initial': initial, 'incoming': incoming, 'mode': mode, 'flag': flag,
            'selected': selected, 'refresh_count': len(updates),
            'gate': gate, 'transition_count': len(transitions)}


if __name__ == '__main__':
    cases = [run([], [101, 102]), run([101, 102], [102, 103]),
             run(list(range(1, 9)), [99]), run([], [], 12, 0),
             run([], [101], 0, 0, 1), run([], [101], 0, 1, 1),
             run([], [101], 0, 0, 0), run([], [101], 12, 0, 1)]
    assert cases[0]['selected'] == [[0, 101], [1, 102]]
    assert cases[1]['selected'] == [[1, 102], [2, 103]]
    assert cases[1]['refresh_count'] == 2
    assert cases[2]['selected'] == []
    assert cases[3]['refresh_count'] == 1
    assert [c['transition_count'] for c in cases[4:]] == [1, 0, 0, 0]
    (ROOT / 'evidence/battle_member_consumer_native.json').write_text(
        json.dumps({'sha256': EXPECTED_SHA, 'method': __doc__, 'cases': cases}, indent=2) + '\n')
    print('BattleMemberList25 original slot selection: insert/update/full/mode12 PASS')
