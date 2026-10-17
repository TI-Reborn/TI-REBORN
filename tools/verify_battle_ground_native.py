"""Original BattleGround35 reader: numeric reads/loops and grid writes execute.

Empty owned-pet table; grid allocation, resource setup, string allocation and
cleanup are isolated. This proves wire consumption, not map loading or combat.
"""
from verify_auth_native import *


def run(width, height, objects):
    first = bytes(range(width * height))
    second = bytes(100 + n for n in range(width * height))
    body = bytes((7, width, height)) + first + struct.pack('<H', len(objects))
    for name, a, b in objects:
        body += name + b'\0' + bytes((a, b))
    body += second
    u = emulator()
    u.mem_write(DATA, body)
    put32(u, 0xac618c, DATA + 0x1000)  # Empty 31-slot owned model table.
    put32(u, 0xac561c, DATA + 0x1100)
    put32(u, 0xac5494, DATA + 0x1104)
    put32(u, 0xac6498, DATA + 0x1200)
    put32(u, DATA + 0x1200, DATA + 0x1300)
    for x in range(width):
        put32(u, DATA + 0x1300 + x * 4, DATA + 0x2000 + x * 0x100)
    result = {'packet_hex': (b'\x35' + body).hex(), 'width': width, 'height': height,
              'strings': [], 'grid': [], 'consumed': None}

    def hook(uc, address, size, user):
        if address in (0x9dc14c, 0x9596b8, 0x95dd54, 0x40b09c, 0x40c9f4):
            return_from_stub(uc)
        elif address == 0x605f1c:
            cursor = uc.reg_read(UC_X86_REG_EAX)
            start = get32(uc, cursor)
            end = start
            while uc.mem_read(end, 1) != b'\0':
                end += 1
            result['strings'].append(bytes(uc.mem_read(start, end-start)).hex())
            put32(uc, cursor, end + 1)
            return_from_stub(uc)
        elif address == 0x95df1a:
            result['consumed'] = get32(uc, uc.reg_read(UC_X86_REG_EBP)-4) - DATA

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, DATA)
    u.emu_start(0x95dd78, STOP, count=10000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert result['consumed'] == len(body)
    assert get32(u, DATA+0x1100) == width
    assert get32(u, DATA+0x1104) == height
    result['grid'] = [get32(u, DATA+0x2000+x*0x100+y*8)
                      for y in range(height) for x in range(width)]
    assert result['grid'] == list(second)
    assert result['strings'] == [obj[0].hex() for obj in objects]
    return result


if __name__ == '__main__':
    cases = [run(0, 0, ()), run(1, 1, ()),
             run(2, 3, ((b'one', 4, 5), (b'two', 6, 7))),
             run(3, 2, ((b'', 0, 255),))]
    (ROOT/'evidence/battle_ground_native.json').write_text(
        json.dumps({'sha256': EXPECTED_SHA, 'method': __doc__, 'cases': cases}, indent=2)+'\n')
    print('Original BattleGround35 reader: 4 cases PASS')
