"""Dock the existing skills and abilities panel beside the selected mercenary."""
from __future__ import annotations

import hashlib

import pefile

from .client_barracks_a2 import BASE, HEADER, INFO, LEFT, STATE, _child, _global
from .client_equipment_batch import Code

SOURCE_SHA = 'bac5d8f8a4f38578d24fc2af5b4013ee857f404652d7c740ece0abcb2e9f67bf'
HOOK = 0xce932a
ENTRY = 0xce9800
REPARENT = 0xce99f9
SKILL_TAB = 0xad107c
PROFILE_TAB = 0xad1084
PAGE_VMT = 0xa31a40
PANEL_WIDTH = 237
MIN_ACTOR_BAND = 104
GAP = 8


def layout_code() -> bytes:
    c = Code(ENTRY)
    # The existing layout entry saved all registers. The stock epilogue is below.
    c.emit('83ec14 89e5')
    _global(c, INFO, 'done'); c.emit('89c7')
    _global(c, SKILL_TAB, 'done'); c.emit('8b704c 85f6'); c.branch('0f84', 'done')
    _global(c, PROFILE_TAB, 'done')
    c.emit('8b404c 85c0'); c.branch('0f84', 'done')
    c.emit('39784c'); c.branch('0f85', 'done')
    c.emit('894504 8b474c 85c0'); c.branch('0f84', 'done')
    c.emit('894500 8d93'); c.word(PAGE_VMT - BASE)
    c.emit('3910'); c.branch('0f85', 'done')
    _global(c, HEADER, 'done')
    c.emit('8b5500 39504c'); c.branch('0f85', 'done')
    c.emit('8b464c 39f8'); c.branch('0f84', 'ready')
    c.emit('39d0'); c.branch('0f85', 'done')
    c.label('ready')
    c.emit('83bb'); c.word(STATE); c.emit('01'); c.branch('0f85', 'restore')
    _global(c, LEFT, 'restore')
    c.emit('39504c'); c.branch('0f85', 'restore')
    _child(c, LEFT, 2, 'restore'); c.emit('894508')
    _child(c, LEFT, 8, 'restore')
    c.emit(f'8b5030 035038 83c2{GAP:02x}')
    c.emit('8b83'); c.word(LEFT - BASE)
    c.emit('8b4838 81e9'); c.word(PANEL_WIDTH + 10)
    c.emit(f'894d0c 83e9{GAP:02x} 29d1 83f9{MIN_ACTOR_BAND:02x}')
    c.branch('0f8c', 'restore')
    c.emit('894d10 8b5500'); c.branch('e8', 'reparent')
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('8b83'); c.word(LEFT - BASE)
    c.emit('8b5030 03550c 895630 8b5034 83c220 895634 c74638'); c.word(PANEL_WIDTH)
    c.emit('8b4504 c7403008000000')
    # The 3D texture is mostly transparent. Bound its visible model in the gap
    # without squeezing the texture horizontally or covering the controls.
    c.emit('8b4510 6bc005 d1f8 8b5508 3b4238 0f4f4238 894238')
    c.emit(f'034510 d1f8 8b4d0c 83e9{GAP:02x} 29c1 894a30')
    c.branch('e9', 'done')
    c.label('restore')
    c.emit('397e4c'); c.branch('0f84', 'done')
    c.emit('89fa'); c.branch('e8', 'reparent')
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('31c0 894630 894634 c74638eb000000')
    c.emit('8b4504 c74030eb000000')
    c.label('done')
    c.emit('89ec 83c414 619dc3')
    assert ENTRY + len(c.data) == REPARENT
    c.label('reparent')
    # This is the same native child-vector removal and insertion used by
    # TGUIControl.SendToBack, with the destination vector supplied by the layout.
    c.emit('8b464c 39d0'); c.branch('0f84', 'parent_done')
    c.emit('52 8b402c 50 89f2'); c.call(0xa57a70)
    c.emit('5a 85c0'); c.branch('0f88', 'parent_missing')
    c.emit('92'); c.call(0xa576e8)
    c.emit('5a 89564c 8b422c 89f2'); c.call(0xa571f4)
    c.label('parent_done')
    c.emit('b801000000 c3')
    c.label('parent_missing')
    c.emit('5a 31c0 c3')
    return c.finish(0x300)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the barracks candidate with full-height durability bars')
    candidate = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        at = pe.get_offset_from_rva(ENTRY - BASE)
        code = layout_code()
        if any(source[at:at + len(code)]):
            raise ValueError('Reserved skills layout space is in use')
        candidate[at:at + len(code)] = code
        at = pe.get_offset_from_rva(HOOK - BASE)
        jump = Code(HOOK)
        jump.jump(ENTRY)
        candidate[at:at + len(jump.data)] = jump.data
    return bytes(candidate)
