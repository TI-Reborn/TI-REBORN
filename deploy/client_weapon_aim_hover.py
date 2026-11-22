"""Keep the selected mercenary aimed across a shot while the target is hovered."""
from hashlib import sha256

import pefile

from .client_equipment_batch import Code


SOURCE_SHA = 'd18da1a674017952104b865fb911cb3bc7cbfedb20472111a6135658221c5cad'
SHOOTING_RANGE_AP_SHA = '46374254b8ba48afb0f1ae67b87e797f83c4555d2938b612d085e27ceaeafe42'
BASE = 0x400000
SLOT = 0xd15400
SET_ANIMATION = 0xa84704


def hover_during_shot() -> bytes:
    code = Code(SLOT)
    code.emit('66 83 f8 02')  # TSoldier.anim_Sequence = firing.
    code.branch('0f84', 'firing')
    code.emit('66 83 f8 0b')
    code.branch('0f84', 'preview')
    code.jump(0x9ef072)
    code.label('preview')
    code.jump(0x9ef087)
    code.label('firing')
    code.emit('53'); code.base()
    code.emit('8b8b'); code.word(0xac618c - BASE)  # Actor table.
    code.emit('8b3c91 5b 8b03')  # EDI = selected mercenary, EAX = hovered enemy.
    code.emit('8b903c600000 3b9798600000')
    code.branch('0f85', 'other_target')
    code.emit('8b9040600000 3b979c600000')
    code.branch('0f85', 'other_target')
    code.jump(0x9ef0b1)  # Refresh the pose without turning or interrupting recoil.
    code.label('other_target')
    code.jump(0x9ef136)
    return code.finish(0x80)


def hover_refresh() -> bytes:
    code = Code(SLOT + 0x80)
    code.emit('8987a0600000 c687a860000002 c3')  # UnaimStart and preview seen this frame.
    return code.finish(0x20)


def hover_start() -> bytes:
    code = Code(SLOT + 0xa0)
    code.emit('c680a860000002')
    code.jump(SET_ANIMATION)
    return code.finish(0x20)


def hold_or_lower() -> bytes:
    code = Code(SLOT + 0xc0)
    # Only the native hover code sets AimedX. Other actors keep their stock timer.
    code.emit('83bf98600000ff')
    code.branch('0f84', 'stock')
    code.emit('80bfa860000002')
    code.branch('0f85', 'lower')
    code.emit('c687a860000001')
    code.jump(0xa8651d)
    code.label('lower')
    code.jump(0xa86503)  # Native lowering, reached only once the active clip ends.
    code.label('stock')
    code.emit('80bfa860000000')
    code.jump(0xa864d7)
    return code.finish(0x40)


def idle_after_equipment_refresh() -> bytes:
    code = Code(SLOT + 0x100)
    code.emit('83b898600000ff')  # No active hover preview.
    code.branch('0f84', 'stock')
    code.emit('6683b8b260000002')
    code.branch('0f84', 'compare_weapon')
    code.emit('6683b8b26000000c')
    code.branch('0f85', 'stock')
    code.label('compare_weapon')
    # Ammo and wear refresh the same mesh after a shot. A genuine weapon
    # change still needs the new weapon's idle animation.
    code.emit('8b90f40d0000 3b5038')
    code.branch('0f85', 'stock')
    code.emit('31c0 c20800')
    code.label('stock')
    code.emit('31d2')
    code.jump(SET_ANIMATION)
    return code.finish(0x60)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() not in (SOURCE_SHA, SHOOTING_RANGE_AP_SHA):
        raise ValueError('Expected the reviewed hosted Silver baseline')

    entry = hover_during_shot() + hover_refresh() + hover_start() + hold_or_lower() + idle_after_equipment_refresh()
    changes = [(SLOT, bytes(len(entry)), entry)]
    for address, expected, target, is_call in (
        (0x9ef06c, '66 83 f8 0b 74 15', SLOT, False),
        (0x9ef0b8, '89 87 a0 60 00 00', SLOT + 0x80, True),
        (0x9ef131, 'e8 ce 55 09 00', SLOT + 0xa0, True),
        (0xa864d0, '80 bf a8 60 00 00 00', SLOT + 0xc0, False),
        (0xa85a1e, 'e8 e1 ec ff ff', SLOT + 0x100, True),
        (0x8c5f4a, 'e8 b5 e7 1b 00', SLOT + 0x100, True),
    ):
        old = bytes.fromhex(expected)
        hook = Code(address)
        if is_call:
            hook.call(target)
        else:
            hook.jump(target)
        hook.emit('90' * (len(old) - 5))
        changes.append((address, old, hook.finish(len(old))))

    result = bytearray(source)
    with pefile.PE(data=source) as pe:
        relocations = {reloc.rva for block in pe.DIRECTORY_ENTRY_BASERELOC
                       for reloc in block.entries if reloc.type}
        for address, expected, replacement in changes:
            rva = address - BASE
            section = pe.get_section_by_rva(rva)
            offset = pe.get_offset_from_rva(rva)
            if (section is None or not section.IMAGE_SCN_MEM_EXECUTE
                    or offset + len(expected) > section.PointerToRawData + section.SizeOfRawData
                    or any(i in relocations for i in range(rva - 3, rva + len(expected)))
                    or source[offset:offset + len(expected)] != expected):
                raise ValueError(f'Unexpected weapon hover span at {address:#x}')
            result[offset:offset + len(expected)] = replacement
    return bytes(result)
