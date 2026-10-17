"""Original BA08 consumer: matching search/character only, boolean state."""
from verify_auth_native import *


def run(room, character, ready):
    u = emulator()
    put32(u, 0xac6184, DATA+0x2000)
    put32(u, DATA+0x2000, 42)
    put32(u, 0xac62a4, DATA+0x3000)
    u.mem_write(DATA+0x3000, b'\1')
    put32(u, DATA+0x3004, 7)
    packet = struct.pack('<IIB', room, character, ready)
    u.mem_write(DATA, packet)
    u.reg_write(UC_X86_REG_EAX, DATA)
    u.emu_start(0x85fe00, STOP, count=3000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    result = bytes(u.mem_read(DATA+0x3110, 1))[0]
    assert result == int(room == 42 and character == 7 and ready != 0)
    return {'room': room, 'character': character, 'ready': ready, 'native_state': result}


if __name__ == '__main__':
    cases = [run(42,7,1), run(42,7,0), run(43,7,1), run(42,8,1)]
    (ROOT/'evidence/arena_ready_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Arena BA08 native consumer: 4 cases PASS')
