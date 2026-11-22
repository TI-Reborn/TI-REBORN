"""Enemy-target skills require the enemy under the cursor (Silver 2026.11.13.5).

Native validator 8b5d6c reads the cursor cell into EBP-8/EBP-C, but its
Target=enemy branch (8b5e5e) accepts the first visible living enemy in range
anywhere on the field. The skill tooltip is drawn at the mouse, so with a
neighbour present it followed the cursor across the whole map and a click on
empty ground cast on that neighbour. The patched visibility call also requires
the candidate's cell (+603C/+6040) to be the cursor cell; Slash22/Deathbite26
then show their tooltip and accept a click only over the target.
"""
import hashlib

import pefile

from .client_equipment_batch import Code

SOURCE_SHA = '4c4d8e9891ac8f0083cb2d8406aea4428c1ba3278168f28309a102a8918a9133'
VISIBLE = 0xa84248
ENEMY_VISIBLE_CALL = 0x8b5e9f
CURSOR_ENEMY = 0xcc3e00
SIZE = 0x40


def cursor_enemy_code() -> bytes:
    """EAX actor -> AL visible and on the cursor cell; validator EBP frame."""
    code = Code(CURSOR_ENEMY)
    code.emit('50'); code.call(VISIBLE); code.emit('59')
    code.emit('84c0'); code.branch('0f84', 'done')
    code.emit('8b913c600000 3b55f8'); code.branch('0f85', 'outside')
    code.emit('8b9140600000 3b55f4'); code.branch('0f85', 'outside')
    code.emit('b001 c3')
    code.label('outside'); code.emit('31c0')
    code.label('done'); code.emit('c3')
    return code.finish(SIZE)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.13.5 Silver')
    original = Code(ENEMY_VISIBLE_CALL); original.call(VISIBLE)
    hooked = Code(ENEMY_VISIBLE_CALL); hooked.call(CURSOR_ENEMY)
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        for address, expected, replacement in (
            (ENEMY_VISIBLE_CALL, original.finish(5), hooked.finish(5)),
            (CURSOR_ENEMY, bytes(SIZE), cursor_enemy_code()),
        ):
            offset = pe.get_offset_from_rva(address - 0x400000)
            if source[offset:offset+len(expected)] != expected:
                raise ValueError('Skill target span changed')
            result[offset:offset+len(expected)] = replacement
    return bytes(result)
