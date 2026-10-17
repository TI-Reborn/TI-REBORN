"""Execute original9595f0 ->6585cc C8/3D builder with real field writers.

Packet begin/end transport calls are isolated. Opcode action meaning and the
second field remain unknown; do not route this as movement on this evidence.
"""
from verify_auth_native import *


def run(actor, unknown, x, y):
    u = emulator()
    put32(u, 0xacd0e0, DATA)
    put32(u, 0xacd0f0, 0)
    sp = u.reg_read(UC_X86_REG_ESP)
    put32(u, sp + 4, y)
    u.reg_write(UC_X86_REG_EAX, actor)
    u.reg_write(UC_X86_REG_EDX, unknown)
    u.reg_write(UC_X86_REG_ECX, x)
    transport = []

    def hook(uc, address, size, user):
        if address in (0x629764, 0x629938):
            transport.append(hex(address))
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(0x9595f0, STOP, count=1000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert u.reg_read(UC_X86_REG_ESP) == sp + 8
    packet = bytes(u.mem_read(DATA, get32(u, 0xacd0f0)))
    assert packet == b'\xc8\x3d' + struct.pack('<IIII', actor, unknown, x, y)
    assert transport == ['0x629764', '0x629938']
    return dict(actor_id=actor, unknown=unknown, x=x, y=y, packet_hex=packet.hex())


if __name__ == '__main__':
    cases = [run(17, 0, 2, 3), run(0x12345678, 0x87654321, 255, 256),
             run(1, 0xffffffff, 0xffffffff, 0)]
    (ROOT / 'evidence/battle_target_request_native.json').write_text(
        json.dumps(dict(sha256=EXPECTED_SHA, method=__doc__, cases=cases,
                        caller='95b943: actor+28, global ad0620, target x/y from parent locals'),
                   indent=2) + '\n', encoding='utf-8')
    print('Original C8/3D target builder: 3 cases PASS')
