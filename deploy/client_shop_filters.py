"""Patch the ordinary shop's own filter callbacks on the published x86 client."""
import hashlib
import struct

import pefile

from .client_equipment_batch import Code

SOURCE_SHA = 'd9d290f238cd0b38d503ab77f227334a86be3f8ad7122a4da725593097cbe719'
BASE = 0x400000
OPEN_HOOK, ITEM_HOOK = 0x974B45, 0x97691F
OPEN, MATCH, LABELS = 0xCEA200, 0xCEA300, 0xCEA480
VISIBLE = sum(1 << group for group in (1, 2, *range(4, 16), 17, 18, 19))

# Array indices from the stock filter constructor at 8e23d0.
CAPTIONS = (
    (6, 'Armor', 'Броня'),
    (18, 'Ammunition', 'Боеприпасы'),
    (5, 'Medicine', 'Медицина'),
    (17, 'Equipment', 'Оборудование'),
    (3, 'Boosters', 'Усилители'),
    (4, 'Implants', 'Импланты'),
)


def _labels() -> bytes:
    table = bytearray((len(CAPTIONS) + 1) * 12)
    for index, (slot, english, russian) in enumerate(CAPTIONS):
        pointers = []
        for caption in (english, russian):
            pointers.append(LABELS - BASE + len(table) + 12)
            table += struct.pack('<HHiI', 1200, 2, -1, len(caption))
            table += caption.encode('utf-16le') + b'\0\0'
        struct.pack_into('<III', table, index * 12, slot, *pointers)
    return bytes(table)


def _open() -> bytes:
    c = Code(OPEN)
    c.emit('53 56 57 89c6 ba'); c.word(VISIBLE)
    c.call(0x8E332C)  # Native visibility-mask setter.
    c.emit('8bb680020000')  # ESI = native filter row array.
    c.base()  # EBX = relocated Silver base.
    c.emit('8dbb'); c.word(LABELS - BASE)
    # The native Armor row is localized already. Cyrillic selects Russian
    # captions, including when the shop is reopened with our own captions.
    c.emit('8b4618 8b4014 31c9 85c0'); c.branch('0f84', 'loop')
    c.emit('6681380004 0f93c1')
    c.label('loop')
    c.emit('8b07 85c0'); c.branch('0f84', 'done')
    c.emit('51 8b0486 83c014 8b548f04 01da')
    c.call(0x40B47C)  # Assign the managed UnicodeString.
    c.emit('59 83c70c'); c.branch('e9', 'loop')
    c.label('done')
    c.emit('5f 5e 5b c3')
    return c.finish(MATCH - OPEN)


def _match() -> bytes:
    c = Code(MATCH)
    c.emit('0fb68884020000')  # ECX = filter ID, EDX = item record, ESI = metadata index.
    for group, condition in ((1, '0f86'), (3, '0f84'), (16, '0f84'), (20, '0f83')):
        c.emit(f'83f9{group:02x}'); c.branch(condition, 'stock')
    c.emit('8b5208 51 e800000000 58 2d')
    c.word(MATCH + len(c.data) - 2 - BASE)  # Recover the ASLR image base in EAX.
    c.emit('8b807c636c00 8b00 69ce783a0000 01c8 59')
    # +118: item type, +120: weapon class, +12d: body part.
    c.emit('6683b81801000009'); c.branch('0f84', 'armor')
    c.emit('6683b81801000008'); c.branch('0f84', 'ammunition')
    c.emit('6683b81801000002'); c.branch('0f84', 'medical_type')
    c.emit('81faeb170000'); c.branch('0f84', 'implant')  # 6123, implant extractor.
    c.emit('0fb79018010000 83ea17 83fa03'); c.branch('0f86', 'implant')
    c.emit('0fb79020010000 83ea02 83fa05'); c.branch('0f87', 'equipment')
    c.emit('83f908'); c.branch('0f84', 'show')
    c.emit('83c209'); c.branch('e9', 'compare')

    c.label('armor')
    c.emit('83f904'); c.branch('0f84', 'show')
    c.emit('0fb6902d010000')
    for part, group in ((3, 'head'), (5, 'legs'), (1, 'body'), (2, 'body'), (9, 'body')):
        c.emit(f'83fa{part:02x}'); c.branch('0f84', group)
    c.branch('e9', 'hide')
    c.label('medical_type')
    # Optics and boosters reuse the legacy medkit ABI for their item action.
    c.emit('81fa8a130000'); c.branch('0f84', 'equipment')  # 5002, night vision.
    c.emit('81ea8b130000 83fa08'); c.branch('0f86', 'boosters')  # 5003–5011.
    for label, group in (('medical_type_tail', 15), ('head', 5), ('body', 6), ('legs', 7),
                         ('ammunition', 17), ('boosters', 18), ('equipment', 19), ('implant', 2)):
        c.label(label)
        c.emit('ba'); c.word(group)
        c.branch('e9', 'compare')
    c.label('compare'); c.emit('31c0 39d1 0f94c0 c3')
    c.label('show'); c.emit('b801000000 c3')
    c.label('hide'); c.emit('31c0 c3')
    c.label('stock'); c.jump(0x8E2E68)  # Reset, contextual ammo and legacy controls.
    return c.finish(LABELS - MATCH)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published Silver 2026.11.18.6')
    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        for site, old_target, target in (
            (OPEN_HOOK, 0x8E3288, OPEN), (ITEM_HOOK, 0x8E2E68, MATCH),
        ):
            start = pe.get_offset_from_rva(site - BASE)
            expected = b'\xe8' + struct.pack('<i', old_target - site - 5)
            if source[start:start + 5] != expected:
                raise ValueError(f'Shop filter call changed at {site:#x}')
            result[start:start + 5] = b'\xe8' + struct.pack('<i', target - site - 5)
        for address, payload in ((OPEN, _open()), (MATCH, _match()), (LABELS, _labels())):
            start = pe.get_offset_from_rva(address - BASE)
            if any(source[start:start + len(payload)]):
                raise ValueError(f'Shop filter region already occupied at {address:#x}')
            result[start:start + len(payload)] = payload
    return bytes(result)
