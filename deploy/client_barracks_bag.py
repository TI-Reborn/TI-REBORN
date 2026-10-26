"""Scoped A2 backpack geometry for the native drawing and input loops.

The native record filtering, selection, hints and transfers stay authoritative.
Only the concrete barracks backpack receives the reference cell dimensions.
"""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE = 0x400000
BAG = 0xac4bd4
SIZE = 0x4000

# site, original instructions, frame X (or EDI), frame Y (or EDI),
# original advance and viewport-exit targets. Branch targets remain intact.
LOOPS = (
    (0x9bc96d, '8345fc428b433883e8403b45fc7f0fc745fc0300000083c7253b7b3c7d0a',
     -4, None, 0x9bc98b, 0x9bc995),
    (0x9bec2c, '83c7428b433883e8403bf87c11bf030000008345dc258b45dc3b433c7d0a',
     None, -0x24, 0x9bec4a, 0x9bec54),
    (0x9bf160, '83c7428b433883e8403bf87c11bf030000008345f4258b45f43b433c7d0a',
     None, -12, 0x9bf17e, 0x9bf188),
    (0x9bcec2, '83c7428b433883e8403bf87c17bf03000000838568fdffff258b8568fdffff3b433c7d0d',
     None, -0x298, 0x9bcee6, 0x9bcef3),
)

# Non-branch instructions ending at a stable native continuation.
HITS = (
    (0x9be8c1, '8d57403bc2', 'width'),
    (0x9be8e4, '83c2203bc2', 'height'),
    (0x9bf087, '8d57403bc2', 'width'),
    (0x9bf0aa, '83c2203bc2', 'height'),
    (0x9bce75, '8d57403bc2', 'width'),
    (0x9bce9c, '83c2203bc2', 'height'),
    (0x9bc640, '8d472085c0', 'cull'),
    (0x9bc84f, '6a206a0068d2d18f44', 'selection_height'),
    (0x9bc86c, 'b93e000000', 'selection_width'),
    (0x9bcb13, '83c7408b4338', 'scroll_pitch'),
    (0x9bcb19, '83e8403bf8', 'scroll_width'),
    (0x9bcb25, 'c645fb008345fc25', 'scroll_row'),
    (0x9bcb37, '807dfb0074048345fc258b45fc', 'scroll_last'),
)


def _guard(c: Code, state: int) -> None:
    """Choose only the two reviewed widths; retain stock everywhere else."""
    c.emit('9c5053')
    c.base()
    c.emit('83bb'); c.word(state); c.emit('01')
    c.branch('0f85', 'stock')
    c.emit('8b0424 3b83'); c.word(BAG-BASE)
    c.branch('0f85', 'stock')
    c.emit('8178389e010000'); c.branch('0f84', 'full')
    c.emit('8178383a010000'); c.branch('0f84', 'compact')
    c.branch('e9', 'stock')


def _slot(c: Code, operation: str, position: int, value: int) -> None:
    # Every frame displacement is explicit; EBP is the original native frame.
    c.emit({'add': '8185', 'mov': 'c785', 'cmp': '3b85'}[operation])
    c.word(position)
    if operation != 'cmp':
        c.word(value)


def _loop(c: Code, row: tuple, width: int, pitch: int, height: int,
          label: str) -> None:
    _, _, x_slot, y_slot, advance, end = row
    if x_slot is None:
        c.emit('81c7'); c.word(pitch)
    else:
        _slot(c, 'add', x_slot, pitch)
    c.emit('8b4338 2d'); c.word(width)
    if x_slot is None:
        c.emit('3bf8'); c.branch('0f8c', label+'_advance')
    else:
        _slot(c, 'cmp', x_slot, 0)
        c.branch('0f8f', label+'_advance')
    if x_slot is None:
        c.emit('bf03000000')
        _slot(c, 'add', y_slot, height)
        c.emit('8b85'); c.word(y_slot); c.emit('3b433c')
    else:
        _slot(c, 'mov', x_slot, 3)
        c.emit('81c7'); c.word(height); c.emit('3b7b3c')
    c.branch('0f8d', label+'_end')
    c.label(label+'_advance'); c.jump(advance)
    c.label(label+'_end'); c.jump(end)


def _replacement(kind: str, width: int) -> str:
    height, pitch = (56 if width==94 else 42), width+6
    replacements = {
        'width': f'8d57{width:02x}3bc2',
        'height': f'83c2{height:02x}3bc2',
        'cull': f'8d47{height:02x}85c0',
        'selection_height': f'6a{height:02x}6a0068d2d18f44',
        'selection_width': 'b9'+struct.pack('<I', width-2).hex(),
        'scroll_pitch': f'83c7{pitch:02x}8b4338',
        'scroll_width': f'83e8{width:02x}3bf8',
        'scroll_row': 'c645fb008345fc'+f'{height+6:02x}',
    }
    return replacements[kind]


def payload(origin: int, layout_state: int) -> bytes:
    from .client_equipment_batch import Code

    result = bytearray(SIZE)
    for index, row in enumerate(LOOPS):
        offset = index*0x400
        code = Code(BASE+origin+offset)
        _guard(code, layout_state)
        for label, width, pitch, height in (
                ('full', 94, 100, 62), ('compact', 69, 75, 48),
                ('stock', 64, 66, 37)):
            code.label(label); code.emit('5b589d')
            _loop(code, row, width, pitch, height, label)
        result[offset:offset+0x400] = code.finish(0x400)
    for index, (site, original, kind) in enumerate(HITS):
        offset = 0x1000+index*0x100
        code = Code(BASE+origin+offset)
        _guard(code, layout_state)
        for label, width in (('full', 94), ('compact', 69), ('stock', 64)):
            code.label(label); code.emit('5b589d')
            if kind == 'scroll_last':
                # The original JE enters the MOV immediately after the ADD.
                # Redirect the whole branch, preserving that entry explicitly.
                code.emit('807dfb00'); code.branch('0f84', label+'_last')
                code.emit('8345fc'+('25' if label=='stock' else ('3e' if width==94 else '30')))
                code.label(label+'_last'); code.emit('8b45fc')
            else:
                code.emit(original if label == 'stock' else _replacement(kind, width))
            code.jump(site+len(bytes.fromhex(original)))
        result[offset:offset+0x100] = code.finish(0x100)
    return bytes(result)


def edits(origin: int) -> tuple[tuple[int, bytes, bytes], ...]:
    rows = [(row[0], row[1], index*0x400) for index, row in enumerate(LOOPS)]
    rows.extend((site, old, 0x1000+index*0x100)
                for index, (site, old, _) in enumerate(HITS))
    return tuple((site, bytes.fromhex(old),
                  (b'\xe9'+struct.pack('<i', BASE+origin+offset-site-5)).ljust(
                      len(bytes.fromhex(old)), b'\x90'))
                 for site, old, offset in rows)
