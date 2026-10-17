"""Scoped native filled-disc removal and label adjustments.

These wrappers act only while the town renderer uses the borrowed projected
array. Every other native call keeps its original arguments and cleanup.
"""
from __future__ import annotations

import struct
from .client_equipment_batch import Code

RING_OFFSET = 0x13000
NAME_OFFSET = 0x13200
LABEL_HIT_OFFSET = 0x13400
LABEL_IDS = (11, 16)
LABEL_CENTER_PADDING = 10
LABEL_HIT_PADDING = LABEL_CENTER_PADDING - 6


def scope(c, a):
    c.emit('9c60'); c.base()
    c.emit('8d83'); c.word(a.TABLE)
    c.emit('3b83'); c.word(0xb749e4 - a.IMAGE_BASE)
    c.branch('0f85', 'stock')


def selected_town(c, a):
    # The original 9ebda4 frame keeps ESI=&loop_index. pushad saved it at +4.
    c.emit('8b83'); c.word(0xb749e4 - a.IMAGE_BASE)
    c.emit('8b542404 8b12 85d2'); c.branch('0f88', 'stock')
    c.emit('3b50fc'); c.branch('0f83', 'stock')
    c.emit('8b0490 0fb65008 83fa0b'); c.branch('0f84', 'selected')
    c.emit('83fa10'); c.branch('0f85', 'stock')
    c.label('selected')


def ring_code(a):
    address = a.DRAW + RING_OFFSET
    c = Code(address); scope(c, a)
    # townzone.tga has an opaque rim and translucent filled center. Both native
    # passes otherwise paint over the new object PNGs. Keep the native labels,
    # clan badges and hover code, while consuming the exact five draw arguments.
    c.emit('619d c21400')
    c.label('stock'); c.emit('619d'); c.jump(0x4f2910)
    return c.finish(0x200)


def name_code(a):
    c = Code(a.DRAW + NAME_OFFSET); scope(c, a); selected_town(c, a)
    # The center-Y argument is S+8 (native pushed Y before color).
    c.emit('8b801c020000 83c0'); c.emit(f'{LABEL_CENTER_PADDING:02x}')
    c.emit('8944242c')
    c.label('stock'); c.emit('619d'); c.jump(0x4f2a0c)
    return c.finish(0x200)


def label_hit_code(a):
    c = Code(a.DRAW + LABEL_HIT_OFFSET); scope(c, a); selected_town(c, a)
    # Original label hover rect is centered on text: top=centerY-6, height13.
    c.emit('8b801c020000 83c0'); c.emit(f'{LABEL_HIT_PADDING:02x}')
    c.emit('89442414')  # Saved EDX=rectangle top.
    c.label('stock'); c.emit('619d'); c.jump(0x4121ac)
    return c.finish(0x200)


def extra_entries(a):
    return ((a.DRAW + RING_OFFSET, ring_code(a)),
            (a.DRAW + NAME_OFFSET, name_code(a)),
            (a.DRAW + LABEL_HIT_OFFSET, label_hit_code(a)))


def native_edits(a):
    out = []
    for site, original, target in ((0x9ebf4d, 0x4f2910, a.DRAW + RING_OFFSET),
                                    (0x9ebf9b, 0x4f2910, a.DRAW + RING_OFFSET),
                                    (0x9ec0c4, 0x4f2a0c, a.DRAW + NAME_OFFSET),
                                    (0x9ec274, 0x4121ac, a.DRAW + LABEL_HIT_OFFSET)):
        out.append((site, b'\xe8' + struct.pack('<i', original - site - 5),
                    b'\xe8' + struct.pack('<i', target - site - 5)))
    return out


def metadata():
    return {'native_filled_discs_removed': True,
            'native_filled_disc_call_sites': ['0x9ebf4d', '0x9ebf9b'],
            'native_filled_disc_stack_cleanup_bytes': 20,
            'original_disc_calls_preserved_outside_scope': True,
            'labels_below_marker_ids': list(LABEL_IDS), 'label_center_padding': LABEL_CENTER_PADDING,
            'label_hover_rect_tracks_displayed_label': True,
            'scope': 'Only b749e4 == mapped borrowed global-map table',
            'native_font_names_clan_badges_and_tooltips': True,
            'authoritative_bounds_modified': False}
