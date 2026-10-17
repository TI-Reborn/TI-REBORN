"""Bounded native refresh while the authenticated server-list window is visible.

Extends the separately reviewed row-status transformer. Calls the unchanged
native 05 request builder from presentation Draw, never rewrites auth/network
functions, and marks displayed rows stale after one unanswered refresh.
"""
from __future__ import annotations

import struct

import pefile
from .client_equipment_batch import Code
from .client_server_list_status import sha, call_bytes

BASE_SHA = 'efc655e70cdc1e414270f6e5a4651d4c2927e866c7ae878edb6d54cb118049bf'
IMAGE_BASE = 0x400000
APPEND_RVA = 0x877000
APPEND_SIZE = 0x1000
POLL_HELPER = IMAGE_BASE + APPEND_RVA
REPLY_HELPER = POLL_HELPER + 0x200
COLOUR_HELPER = POLL_HELPER + 0x300
STATE = APPEND_RVA + 0xf00
ACTIVE, PENDING, STALE, LAST_SEND, LAST_REPLY = STATE, STATE+1, STATE+2, STATE+4, STATE+8
POLL_MS, TIMEOUT_MS = 5000, 3000
TICK_IAT_RVA = 0xb79b10 - IMAGE_BASE
SIGNATURE = b'TIO-native-server-list-visible-refresh-v1'


def poll_code():
    c = Code(POLL_HELPER)
    c.emit('9c60'); c.base()  # Restore every original Draw argument and flags.
    c.emit('80bb'); c.word(ACTIVE); c.emit('00'); c.branch('0f84', 'done')
    c.emit('8b44241c 8b404c 85c0'); c.branch('0f84', 'done')
    c.emit('80784900'); c.branch('0f84', 'done')  # Original TWindow.Visible.
    c.emit('ff93'); c.word(TICK_IAT_RVA)
    c.emit('2b83'); c.word(LAST_SEND)  # Unsigned delta handles GetTickCount wrap.
    c.emit('80bb'); c.word(PENDING); c.emit('00'); c.branch('0f84', 'idle')
    c.emit('3d'); c.word(TIMEOUT_MS); c.branch('0f82', 'done')
    # A single unanswered request invalidates displayed availability. It also
    # stops additional requests; an actual valid native 06 is the only recovery.
    for field, value in ((STALE, 1), (PENDING, 0), (ACTIVE, 0)):
        c.emit('c683'); c.word(field); c.emit(f'{value:02x}')
    c.branch('e9', 'done')
    c.label('idle')
    c.emit('3d'); c.word(POLL_MS); c.branch('0f82', 'done')
    c.emit('0383'); c.word(LAST_SEND)  # Recover actual clock from elapsed delta.
    c.emit('8983'); c.word(LAST_SEND)
    c.emit('c683'); c.word(PENDING); c.emit('01')
    c.call(0x87c76c)  # Exact original writer/transport; original 05 ABI intact.
    c.label('done'); c.emit('619d'); c.jump(0xa53b08)
    return c.finish(0x200)


def reply_code():
    c = Code(REPLY_HELPER)
    c.call(0x71e594)  # Preserve native list UI callback and its return registers.
    c.emit('9c60'); c.base()
    c.emit('ff93'); c.word(TICK_IAT_RVA)
    for field in (LAST_SEND, LAST_REPLY):
        c.emit('8983'); c.word(field)
    for field, value in ((ACTIVE, 1), (PENDING, 0), (STALE, 0)):
        c.emit('c683'); c.word(field); c.emit(f'{value:02x}')
    c.emit('619d c3')
    return c.finish(0x100)


def colour_code():
    c = Code(COLOUR_HELPER)
    c.emit('53'); c.base()
    c.emit('80bb'); c.word(STALE); c.emit('00'); c.branch('0f85', 'stale')
    c.emit('8b45e4 0fb6400e 5b c3')
    c.label('stale'); c.emit('31c0 5b c3')
    return c.finish(0x100)


def payload():
    return (poll_code()+reply_code()+colour_code()+SIGNATURE+b'\0').ljust(APPEND_SIZE, b'\0')


def specifications():
    return (
        (0x71f034, call_bytes(0x71f034, 0xa53b08), call_bytes(0x71f034, POLL_HELPER),
         'While original list window is visible, send one unchanged 05 every five seconds'),
        (0x87d392, call_bytes(0x87d392, 0x71e594), call_bytes(0x87d392, REPLY_HELPER),
         'Observe successful original 06 completion at its existing UI callback'),
        (0x71f256, bytes.fromhex('8b45e4 80780e00 7507 c745f0606060ff'),
         call_bytes(0x71f256, COLOUR_HELPER)+bytes.fromhex('84c0 7507 c745f0606060ff'),
         'Use gray after a missing response without mutating the native row status'),
    )


def patch(data):
    if sha(data) != BASE_SHA:
        raise ValueError('Freshness requires the exact reviewed status-only candidate')
    p = pefile.PE(data=data)
    try:
        last = p.sections[-1]
        if (p.FILE_HEADER.Machine != 0x14c or p.OPTIONAL_HEADER.ImageBase != IMAGE_BASE
                or len(p.sections) != 13 or p.OPTIONAL_HEADER.SizeOfImage != APPEND_RVA
                or last.Name != b'.tioscr\0' or last.VirtualAddress != 0x823000
                or last.Misc_VirtualSize != 0x54000 or last.SizeOfRawData != 0x54000
                or last.PointerToRawData != 0x76b200
                or last.PointerToRawData+last.SizeOfRawData != len(data)):
            raise ValueError('Server-list freshness PE geometry differs')
        result = bytearray(data)
        for address, before, after, _ in specifications():
            if len(before) != len(after) or p.get_data(address-IMAGE_BASE, len(before)) != before:
                raise ValueError('Server-list presentation callback differs: '+hex(address))
            at = p.get_offset_from_rva(address-IMAGE_BASE)
            result[at:at+len(after)] = after
        for field in ('Misc_VirtualSize', 'SizeOfRawData'):
            struct.pack_into('<I', result, last.get_field_absolute_offset(field), getattr(last, field)+APPEND_SIZE)
        struct.pack_into('<I', result, p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), APPEND_RVA+APPEND_SIZE)
        result.extend(payload())
        return bytes(result)
    finally:
        p.close()


def review(source, candidate):
    if patch(source) != candidate:
        raise ValueError('Candidate differs from the exact server-list freshness transformer')
    p = pefile.PE(data=source)
    try:
        ranges = [(p.get_offset_from_rva(a-IMAGE_BASE), len(old), purpose)
                  for a, old, _, purpose in specifications()]
        ranges += [(p.sections[-1].get_field_absolute_offset(f), 4, 'Extend existing executable final section for refresh helpers/state')
                   for f in ('Misc_VirtualSize', 'SizeOfRawData')]
        ranges += [(p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4, 'Map appended native refresh helpers/state')]
        return dict(changes=[dict(offset=a, size=n, purpose=why, source_sha256=sha(source[a:a+n]), candidate_sha256=sha(candidate[a:a+n]))
                             for a, n, why in sorted(ranges)], appended_size=APPEND_SIZE, appended_sha256=sha(candidate[len(source):]))
    finally:
        p.close()


def metadata():
    return dict(source_sha256=BASE_SHA, append_rva=hex(APPEND_RVA), appended_size=APPEND_SIZE,
                poll_interval_ms=POLL_MS, response_timeout_ms=TIMEOUT_MS,
                max_unanswered_refreshes=1, visible_field='original list control.parent+0x49',
                recovery='Only original successfully parsed 06 UI completion',
                stops_after_selection='Original 07 callback hides window_servers_list before sending 07',
                authentication_functions_unchanged=True, packet05_builder_unchanged=True,
                list06_parser_unchanged_except_ui_completion_callback=True,
                native_row_bytes_unchanged=True, snapshot_status_patch_preserved=True,
                real_graphical_clients=False, published=False)
