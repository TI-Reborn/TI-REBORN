"""Original658bc8/658824 writes known mines; real writers, no stubs."""
from verify_auth_native import *
from tio.protocol.known_mines import KnownMine, encode_known_mines


def run(rows):
    u = emulator()
    obj, entries, flags, output = DATA, DATA+0x1000, DATA+0x2000, DATA+0x3000
    put32(u, obj, entries)
    put32(u, obj+4, len(rows))
    put32(u, obj+8, flags)
    if rows:
        u.mem_write(flags, b'\x01' * len(rows))
    for n, row in enumerate(rows):
        for k, value in enumerate(row):
            put32(u, entries+n*32+k*8, value)
            u.mem_write(entries+n*32+k*8+4, b'\x01')
    put32(u, 0xacd0e0, output)
    put32(u, 0xacd0f0, 0)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x658bc8, STOP, count=3000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    packet = bytes(u.mem_read(output, get32(u, 0xacd0f0)))
    assert packet == encode_known_mines(KnownMine(*row) for row in rows)
    return dict(rows=rows, packet_hex=packet.hex())


if __name__ == '__main__':
    cases = [run([]), run([(2,3,901,1)]), run([(0,255,902,2),(7,6,903,0)])]
    (ROOT/'evidence/known_mines_native.json').write_text(json.dumps(
        dict(sha256=EXPECTED_SHA, method=__doc__, cases=cases,
             rtti='623d08 Write ->658bc8; 623af2 item Write ->658824; fields x,y,itemId,team'),
        indent=2)+'\n', encoding='utf-8')
    print('Known mines original serializer: 3 cases PASS')
