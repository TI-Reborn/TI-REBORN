"""Extend the .89 client's native game settings and own-shot camera focus."""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import struct

import pefile

from .client_equipment_batch import Code


BASE = 0x400000
SOURCE_SHA = 'c4246171012d4e70969e849d4123824c6437b45584d3417ea58873d822a258cb'
FOCUS = 0xd15600
PLAYBACK = FOCUS + 0x60
POLICY = FOCUS + 0xa0
CREATE = FOCUS + 0x120
CLICK = FOCUS + 0x380
REGISTER = FOCUS + 0x400
TITLE = FOCUS + 0x480
SAVE = FOCUS + 0x500
STRINGS = FOCUS + 0x580
PROJECTILE_FOCUS = FOCUS + 0x800
HIT_FOCUS = PROJECTILE_FOCUS + 0x20
IMPACT_POLICY = HIT_FOCUS + 0x20
MARK_SHOT = FOCUS + 0x900
SHOT_ACTOR = FOCUS + 0x960 - BASE
SHOT_TIME = SHOT_ACTOR + 4
NATIVE_ACTORS = 0xac618c - BASE
NATIVE_TICK = 0xac5fe4 - BASE
# shortcut: correlate the next refresh for three seconds, use a packet marker if long stalls must be supported.
SHOT_REFRESH_MS = 3000
CAMERA_GROUP = 0x54494f43  # TRadioButton group, separate from the ground grid.
MODES = ('0', '1', '2')
CAPTIONS = (
    ('Game', 'Игра'),
    ('Center on your shooter', 'Камера при выстреле своего бойца'),
    ('Always', 'Всегда'),
    ('Only off-screen', 'Только за экраном'),
    ('Never', 'Никогда'),
)
CVAR = 'g_shot_camera'


def strings() -> tuple[bytes, dict[str, int]]:
    data = bytearray()
    addresses = {}
    values = (CVAR, *MODES, *CAPTIONS[0])
    for value in (*values, *(text for pair in CAPTIONS[1:] for text in pair)):
        encoded = value.encode('utf-16le')
        # The native caption setter takes a WideString with a byte length.
        header = (struct.pack('<HHiI', 1200, 2, -1, len(value)) if value in values
                  else struct.pack('<I', len(encoded)))
        addresses[value] = STRINGS + len(data) + len(header) - BASE
        data += header + encoded + b'\0\0'
        data += bytes(-len(data) % 4)
    return bytes(data), addresses


def address(code: Code, register: str, rva: int) -> None:
    code.emit({'eax': '8d83', 'edx': '8d93'}[register])
    code.word(rva)


def focus_code() -> bytes:
    code = Code(FOCUS)
    code.emit('9c60 8b049e')  # EAX = actor table[EBX]; native caller confirmed ownership.
    code.base()
    code.emit('3b83')
    code.word(SHOT_ACTOR)
    code.branch('0f85', 'stock')
    # The networked refresh can arrive after the firing pose has ended.
    code.emit('c783'); code.word(SHOT_ACTOR); code.word(0)
    code.emit('8b93'); code.word(NATIVE_TICK)
    code.emit('8b12 2b93'); code.word(SHOT_TIME)
    code.emit('81fa'); code.word(SHOT_REFRESH_MS)
    code.branch('0f87', 'stock')
    code.emit('8b8d20fdffff 8b951cfdffff')  # Tile in the native snapshot.
    code.jump(POLICY)
    code.label('stock')
    code.emit('619d')
    code.jump(0xa88a78)
    return code.finish(PLAYBACK - FOCUS)


def playback_code() -> bytes:
    code = Code(PLAYBACK)
    code.emit('9c60')
    code.base()
    code.emit('8b83')
    code.word(NATIVE_ACTORS)
    code.emit('8b04b0 80784100')  # The attack decoder keeps the actor index in ESI.
    code.branch('0f84', 'stock')
    code.emit('8b883c600000 8b9040600000')
    code.jump(POLICY)
    code.label('stock')
    code.emit('619d')
    code.jump(0xa88a78)
    return code.finish(POLICY - PLAYBACK)


def policy_code(names: dict[str, int]) -> bytes:
    code = Code(POLICY)
    code.base()
    code.emit('51 52')
    address(code, 'eax', names[CVAR])
    code.call(0x688328)
    code.emit('5a 59')
    code.emit('83f802')
    code.branch('0f84', 'skip')
    code.emit('83f801')
    code.branch('0f85', 'stock')
    code.emit('89c8 01d0 c1e004 83c010 29ca c1e205')  # Project tile XY to its ground point.
    code.emit('8bb3'); code.word(0xac61b0 - BASE)
    code.emit('0316')
    code.emit('8bb3'); code.word(0xac6068 - BASE)
    code.emit('0306')
    # Camera offsets use physical pixels. The inset mouse rectangle excludes
    # part of the battlefield that is still visible around the HUD.
    for dimension, compare in ((0xac56e0, '3b16'), (0xac5e60, '3b06')):
        code.emit('8bb3')
        code.word(dimension - BASE)
        code.emit(compare)
        code.branch('0f83', 'stock')  # Unsigned also rejects negative XY.
    code.label('skip')
    code.emit('619d c3')
    code.label('stock')
    code.emit('619d')
    code.jump(0xa88a78)
    return code.finish(CREATE - POLICY)


def impact_code(names: dict[str, int]) -> bytes:
    projectile = Code(PROJECTILE_FOCUS)
    projectile.emit('9c60 89d8')  # Shooter index in the projectile handler.
    projectile.jump(IMPACT_POLICY)
    hits = Code(HIT_FOCUS)
    hits.emit('9c60 8b45f8')  # Shooter index in the hit handler, independent of the victim.
    hits.jump(IMPACT_POLICY)

    code = Code(IMPACT_POLICY)
    code.emit('83f8ff')
    code.branch('0f84', 'stock')
    code.base()
    code.emit('8b93')
    code.word(NATIVE_ACTORS)
    code.emit('8b0482 80784100')
    code.branch('0f84', 'stock')
    address(code, 'eax', names[CVAR])
    code.call(0x688328)
    # In the optional modes the shooter can be the only automatic focus
    # target of their shot, including bursts with impacts on multiple tiles.
    code.emit('48 83f801')
    code.branch('0f86', 'skip')
    code.label('stock')
    code.emit('619d')
    code.jump(0xa88a78)
    code.label('skip')
    code.emit('619d c3')
    return (projectile.finish(HIT_FOCUS - PROJECTILE_FOCUS)
            + hits.finish(IMPACT_POLICY - HIT_FOCUS) + code.finish(0x80))


def mark_shot_code() -> bytes:
    code = Code(MARK_SHOT)
    code.call(0xa93f70)  # Preserve the original result of the shooter lookup.
    code.emit('9c60')
    code.base()
    code.emit('31c9 83f8ff')
    code.branch('0f84', 'store')
    code.emit('8b93'); code.word(NATIVE_ACTORS)
    code.emit('8b0c82 80794100')
    code.branch('0f85', 'store')
    code.emit('31c9')
    # These two values are used on the game thread and consumed by one refresh.
    code.label('store')
    code.emit('898b'); code.word(SHOT_ACTOR)
    code.emit('8b93'); code.word(NATIVE_TICK)
    code.emit('8b12 8993'); code.word(SHOT_TIME)
    code.emit('619d c3')
    return code.finish(0x60)


def select_caption(code: Code, names: dict[str, int], caption: int, language: str) -> None:
    english, russian = CAPTIONS[caption]
    address(code, 'edx', names[english])
    code.emit(language)
    code.branch('0f84', f'caption_{caption}')
    address(code, 'edx', names[russian])
    code.label(f'caption_{caption}')


def cyrillic(code: Code) -> None:
    """EAX = native caption or NULL, ECX = whether it begins with Cyrillic."""
    code.emit('31c9 85c0')
    code.branch('0f84', 'language')
    code.emit('0fb700 2d00040000 3dff000000 0f96c1')
    code.label('language')


def title_code(names: dict[str, int]) -> bytes:
    code = Code(TITLE)
    code.emit('53 56 89d6')
    code.call(0x6675e0)  # Translate the original Battle label to detect locale.
    code.base()
    code.emit('8b06')
    cyrillic(code)
    select_caption(code, names, 0, '85c9')
    code.emit('89f0')
    code.call(0x40b47c)
    code.emit('5e 5b c3')
    return code.finish(SAVE - TITLE)


def create_code(names: dict[str, int]) -> bytes:
    code = Code(CREATE)
    code.call(0xa54f40)  # Finish the native animation checkbox first.
    code.emit('9c60 83ec08')
    code.base()
    address(code, 'eax', names[CVAR])
    code.call(0x688328)
    code.emit('83f802')
    code.branch('0f86', 'mode')
    code.emit('31c0')
    code.label('mode')
    code.emit('890424 8b465c')
    cyrillic(code)
    code.emit('894c2404')

    code.emit('89f1 b201 8b83'); code.word(0xa30e38 - BASE)
    code.call(0xa47d78)
    code.emit('c7403020000000 c740346b010000 c7808c02000001000000')
    select_caption(code, names, 1, '837c240400')
    code.call(0xa42b04)

    for mode, (x, width) in enumerate(((32, 88), (124, 150), (278, 102))):
        code.emit('56 31c9 b201 8b83'); code.word(0xa309f4 - BASE)
        code.call(0xa44c9c)
        code.emit('89c7 c78778020000'); code.word(mode)
        code.emit('c78784020000'); code.word(CAMERA_GROUP)
        code.emit('c74730'); code.word(x)
        code.emit('c74734'); code.word(382)
        code.emit('c74738'); code.word(width)
        select_caption(code, names, mode + 2, '837c240400')
        code.emit('89f8')
        code.call(0xa42b04)
        code.emit(f'833c24{mode:02x} 0f94c2 89f8')
        code.call(0xa44eac)
    code.emit('83c408 619d c3')
    return code.finish(CLICK - CREATE)


def click_code() -> bytes:
    code = Code(CLICK)
    code.call(0xa54964)
    code.emit('9c60 81bb84020000'); code.word(CAMERA_GROUP)
    code.branch('0f85', 'done')
    code.emit('8b8378020000')
    code.call(SAVE)
    code.label('done')
    code.emit('619d c3')
    return code.finish(REGISTER - CLICK)


def register_code(names: dict[str, int]) -> bytes:
    code = Code(REGISTER)
    code.emit('9c60')
    code.base()
    # The host's register callback can be called before its cvar store exists.
    code.emit('833d8867780000')
    code.branch('0f84', 'done')
    code.emit('8b83'); code.word(0xac5b40 - BASE)
    code.emit('85c0')
    code.branch('0f84', 'done')
    code.emit('833800')
    code.branch('0f84', 'done')
    address(code, 'eax', names[CVAR])
    code.call(0x6882f0)
    code.emit('84c0')
    code.branch('0f85', 'done')
    code.emit('31c0')
    code.call(SAVE)
    code.label('done')
    code.emit('619d')
    code.jump(0xc74000)  # Preserve all pre-existing registration hooks.
    return code.finish(TITLE - REGISTER)


def save_code(names: dict[str, int]) -> bytes:
    code = Code(SAVE)
    code.emit('83f802')
    code.branch('0f87', 'done')
    code.emit('53')
    code.base()
    for mode, value in enumerate(MODES):
        address(code, 'edx', names[value])
        if mode < len(MODES) - 1:
            code.emit(f'83f8{mode:02x}')
            code.branch('0f84', 'write')
    code.label('write')
    code.emit('6a01 52')
    address(code, 'eax', names[CVAR])
    code.emit('50')
    code.call(0x688420)  # Native archived cvar, used by game config saving.
    code.emit('5b')
    code.label('done')
    code.emit('c3')
    return code.finish(STRINGS - SAVE)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the reviewed Silver client 2026.11.21.89')
    text, names = strings()
    payload = (focus_code() + playback_code() + policy_code(names) + create_code(names) + click_code()
               + register_code(names) + title_code(names) + save_code(names) + text)
    changes = [
        (FOCUS, bytes(len(payload)), payload),
        (0x885bf0, bytes.fromhex('68a0010000'), bytes.fromhex('68c0010000')),
    ]
    impacts = impact_code(names)
    changes.append((PROJECTILE_FOCUS, bytes(len(impacts)), impacts))
    marker = mark_shot_code() + bytes(8)
    changes.append((MARK_SHOT, bytes(len(marker)), marker))
    for site, original, target, is_call in (
        (0x8c5c96, 0xa88a78, FOCUS, True),
        (0x95f38b, 0xa88a78, PLAYBACK, True),
        (0x95fab4, 0xa93f70, MARK_SHOT, True),
        (0x95fcf9, 0xa88a78, PROJECTILE_FOCUS, True),
        (0x9600b4, 0xa88a78, PROJECTILE_FOCUS, True),
        (0x961726, 0xa88a78, HIT_FOCUS, True),
        (0x961863, 0xa88a78, HIT_FOCUS, True),
        (0x9619a0, 0xa88a78, HIT_FOCUS, True),
        (0x886793, 0xa54f40, CREATE, True),
        (0xa44f6c, 0xa54964, CLICK, True),
        (0x4f255f, 0xc74000, REGISTER, False),
        (0x885ae9, 0x6675e0, TITLE, True),
        (0x885c30, 0x6675e0, TITLE, True),
    ):
        opcode = b'\xe8' if is_call else b'\xe9'
        changes.append((site, opcode + struct.pack('<i', original - site - 5),
                        opcode + struct.pack('<i', target - site - 5)))

    result = bytearray(source)
    with pefile.PE(data=source) as image:
        relocations = {entry.rva for block in image.DIRECTORY_ENTRY_BASERELOC
                       for entry in block.entries if entry.type}
        for site, expected, replacement in changes:
            rva = site - BASE
            section = image.get_section_by_rva(rva)
            offset = image.get_offset_from_rva(rva)
            if (section is None or not section.IMAGE_SCN_MEM_EXECUTE
                    or offset + len(expected) > section.PointerToRawData + section.SizeOfRawData
                    or any(i in relocations for i in range(rva - 3, rva + len(expected)))
                    or source[offset:offset + len(expected)] != expected):
                raise ValueError(f'Unexpected camera patch span at {site:#x}')
            result[offset:offset + len(expected)] = replacement
    return bytes(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    candidate = patch(args.source.read_bytes())
    output = args.output.open('xb')
    try:
        with output:
            output.write(candidate)
    except OSError:
        args.output.unlink(missing_ok=True)
        raise
    print(sha256(candidate).hexdigest())
