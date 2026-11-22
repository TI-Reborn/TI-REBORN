"""Commit ground-container moves once per frame, waiting for the server's 47."""
import struct

from .client_equipment_batch import Code

DIFF, FRAME, OPCODE, COMMIT, DISPATCH = (
    0xcc3400, 0xcc3500, 0xcc3700, 0xcc3800, 0xcc3900)
STATE, NONCE = 0x8c3f00, 0x8c3f04


def blocks() -> tuple[tuple[int, bytes], ...]:
    c = Code(DIFF)
    c.emit('9c60'); c.base()
    c.emit('8b93'); c.word(0x6c64a0)
    c.emit('803a00'); c.branch('0f84', 'done')
    c.emit('80bb'); c.word(0x6c4c64)
    c.emit('00'); c.branch('0f85', 'done')
    c.emit('c683'); c.word(STATE); c.emit('01')
    c.label('done'); c.emit('619d 5f5e5b89ec'); c.jump(0x9dce58)
    diff = c.finish(0x100)

    c = Code(FRAME)
    c.call(0xc26a00)
    c.emit('9c60'); c.base()
    c.emit('80bb'); c.word(STATE); c.emit('01')
    c.branch('0f85', 'done')
    c.emit('80bb'); c.word(0x6c4c64)
    c.emit('00'); c.branch('0f85', 'clear')
    c.emit('83bb'); c.word(0x6c4c5c); c.emit('00')
    c.branch('0f84', 'clear')
    c.emit('c683'); c.word(STATE); c.emit('02')
    c.call(0x9dce5c)
    c.emit('80bb'); c.word(STATE); c.emit('03')
    c.branch('0f85', 'clear')
    c.emit('c683'); c.word(STATE); c.emit('02')
    c.emit('c683'); c.word(0x6c4c58); c.emit('01')
    c.branch('e9', 'done')
    c.label('clear'); c.emit('c683'); c.word(STATE); c.emit('00')
    c.label('done'); c.emit('619dc3')
    frame = c.finish(0x200)

    c = Code(OPCODE)
    c.emit('9c 51 53 56 89c6'); c.base()
    c.emit('80bb'); c.word(STATE); c.emit('02')
    c.branch('0f85', 'stock')
    c.emit('89f0 b2f5'); c.call(0x675bf8)
    c.emit('ff83'); c.word(NONCE)
    c.emit('83bb'); c.word(NONCE); c.emit('00')
    c.branch('0f85', 'nonzero')
    c.emit('ff83'); c.word(NONCE)
    c.label('nonzero'); c.emit('8b00 8b93'); c.word(NONCE)
    c.call(0x6ac248)
    c.emit('c683'); c.word(STATE); c.emit('03')
    c.branch('e9', 'done')
    c.label('stock'); c.emit('89f0 b240'); c.call(0x675bf8)
    c.label('done'); c.emit('5e5b599d'); c.jump(0x98f61c)
    opcode = c.finish(0x100)

    c = Code(COMMIT)
    c.emit('9c60'); c.base()
    c.emit('80bb'); c.word(STATE); c.emit('01')
    c.branch('0f85', 'done')
    c.emit('c683'); c.word(STATE); c.emit('00')
    c.label('done'); c.emit('619d 558bec83c4f8'); c.jump(0x9dce62)
    commit = c.finish(0x100)

    c = Code(DISPATCH)
    c.emit('9c60'); c.base()
    c.emit('80bb'); c.word(STATE); c.emit('02')
    c.branch('0f85', 'done')
    c.emit('3c47'); c.branch('0f84', 'ack')
    c.emit('3cf0'); c.branch('0f85', 'done')
    c.emit('83f905'); c.branch('0f82', 'done')
    c.emit('813a8a010000'); c.branch('0f85', 'done')
    c.emit('c683'); c.word(STATE); c.emit('00')
    c.call(0x9b17c0)
    c.label('ack')
    c.emit('c683'); c.word(STATE); c.emit('00')
    c.emit('c683'); c.word(0x6c4c58); c.emit('00')
    c.label('done'); c.emit('619d 3cfc')
    c.branch('0f84', 'avatar')
    c.jump(0xc800d4)
    c.label('avatar'); c.jump(0xc80008)
    return ((DIFF, diff), (FRAME, frame), (OPCODE, opcode),
            (COMMIT, commit), (DISPATCH, c.finish(0x200)))


def sites() -> tuple[tuple[int, bytes, bytes], ...]:
    result = []
    for at, before, target, call in (
            (0x9dce53, '5f5e5b8be5', DIFF, False),
            (0x9f40ea, 'e811292300', FRAME, True),
            (0x98f615, 'b240e8dc65ceff', OPCODE, False),
            (0x9dce5c, '558bec83c4f8', COMMIT, False),
            (0xc80000, '3cfc0f85cc000000', DISPATCH, False)):
        raw = bytes.fromhex(before)
        after = bytes((0xe8 if call else 0xe9,)) + struct.pack('<i', target-at-5)
        result.append((at, raw, after.ljust(len(raw), b'\x90')))
    return tuple(result)
