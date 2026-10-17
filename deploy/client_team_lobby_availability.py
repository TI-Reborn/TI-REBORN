"""Use any owned fighter for Team/Wall list availability in legacy Silver.

The original main-room list compares its level range against the maximum
selected level and even reports level1 when there are no fighters.  Keep its
ordinary list renderer, gradient, filters and row ABI, but ask whether at least
one owned native fighter fits a Team/Wall row.  Other game modes retain the
original maximum-selected predicate.  Pure byte transformer; no deployment.
"""
from __future__ import annotations

import hashlib
import struct

import pefile
from .client_equipment_batch import Code

BASE_SHA = '5afcac81549ac2ca5e6ceb9a015a075c3a986f6fbda24d0a90a4ad407f066d17'
IMAGE_BASE = 0x400000
HOOK = 0x872c55
ORIGINAL = bytes.fromhex('0fb6461a3b45fc7f440fb6461b3b45fc7c3b')
RESUME = HOOK + len(ORIGINAL)
OUTSIDE = 0x872ca2
APPEND_RVA = 0x873000
APPEND_SIZE = 0x1000
HELPER = IMAGE_BASE + APPEND_RVA
PROJECT_CALL = 0xa09337
PROJECT_NATIVE = 0x872f7c
PROJECT_HELPER = HELPER + 0x200
SIGNATURE = b'TIO-Team-Wall-owned-level-availability-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def payload():
    c = Code(HELPER)
    # A matching Team/Wall row temporarily uses the found level for the native
    # gradient. Recompute the original value per row so a subsequent ordinary
    # mode cannot inherit the preceding row's qualifying owned reserve level.
    c.call(0xa8364c)
    c.emit('8945fc 80fb01')
    c.branch('0f84', 'team')
    c.emit('80fb04')
    c.branch('0f85', 'original')
    c.label('team')
    c.emit('837e2c00'); c.branch('0f85', 'original')
    c.emit('53')
    c.base()
    c.emit('8b93'); c.word(0xac618c - IMAGE_BASE)
    c.emit('b91f000000')
    c.label('next_fighter')
    c.emit('8b02 85c0')
    c.branch('0f84', 'next_slot')
    c.emit('80784100')
    c.branch('0f84', 'next_slot')
    # Native object +41 is the populated fighter flag; +5FFC is its level.
    # Selection state +5FF1 is deliberately not required for an owned reserve.
    c.emit('8b80fc5f0000 83f801')
    c.branch('0f8c', 'next_slot')
    c.emit('83f814')
    c.branch('0f8f', 'next_slot')
    c.emit('3a461a')
    c.branch('0f82', 'next_slot')
    c.emit('3a461b')
    c.branch('0f87', 'next_slot')
    # Use the native pure green endpoint for an available Team/Wall row.
    c.emit('0fb6461b 8945fc 5b b801000000 c3')
    c.label('next_slot')
    c.emit('83c204 49')
    c.branch('0f85', 'next_fighter')
    c.emit('5b 31c0 c3')
    c.label('original')
    c.emit('0fb6561a 3bc2')
    c.branch('0f8c', 'unavailable')
    c.emit('0fb6561b 3bc2')
    c.branch('0f8f', 'unavailable')
    c.emit('b801000000 c3')
    c.label('unavailable')
    c.emit('31c0 c3')
    main = c.finish(0x200)
    c = Code(PROJECT_HELPER)
    c.emit('80781001'); c.branch('0f84', 'team')
    c.emit('80781004'); c.branch('0f85', 'resume')
    c.label('team')
    c.emit('83782c00'); c.branch('0f85', 'resume')
    # Integer midpoint±delta encodes 7–10 as 6–10. Correct that one
    # unambiguous ordinary lobby band after the native range projection.
    c.emit('80781a06'); c.branch('0f85', 'resume')
    c.emit('80781b0a'); c.branch('0f85', 'resume')
    c.emit('c6401a07')
    c.label('resume'); c.jump(PROJECT_NATIVE)
    return main + c.finish(0x100) + (SIGNATURE + b'\0').ljust(APPEND_SIZE - 0x300, b'\0')


def call_bytes(address, target):
    return b'\xe8' + struct.pack('<i', target - address - 5)


def hook_bytes():
    return (b'\xe8' + struct.pack('<i', HELPER - HOOK - 5) + b'\x84\xc0'
            + b'\x0f\x84' + struct.pack('<i', OUTSIDE - (HOOK + 13))
            + b'\x90' * (len(ORIGINAL) - 13))


def patch(data, *, expected_sha=BASE_SHA):
    if sha(data) != expected_sha:
        raise ValueError('Team availability requires the exact inspected Silver')
    p = pefile.PE(data=data)
    try:
        last = p.sections[-1]
        if (p.FILE_HEADER.Machine != 0x14c or p.OPTIONAL_HEADER.ImageBase != IMAGE_BASE
                or len(p.sections) != 13 or p.OPTIONAL_HEADER.SizeOfImage != APPEND_RVA
                or p.OPTIONAL_HEADER.FileAlignment != 0x200
                or p.OPTIONAL_HEADER.SectionAlignment != 0x1000
                or last.Name != b'.tioscr\0' or last.VirtualAddress != 0x823000
                or last.Misc_VirtualSize != 0x50000 or last.SizeOfRawData != 0x50000
                or last.PointerToRawData != 0x76b200
                or last.PointerToRawData + last.SizeOfRawData != len(data)
                or not last.Characteristics & 0x20000000
                or p.get_data(HOOK - IMAGE_BASE, len(ORIGINAL)) != ORIGINAL
                or p.get_data(PROJECT_CALL - IMAGE_BASE, 5) != call_bytes(PROJECT_CALL, PROJECT_NATIVE)):
            raise ValueError('Team availability PE geometry or original predicate differs')
        for block in p.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                if (entry.type == 3 and any(start - IMAGE_BASE <= entry.rva < start - IMAGE_BASE + size
                        for start, size in ((HOOK, len(ORIGINAL)), (PROJECT_CALL, 5)))):
                    raise ValueError('Team availability predicate overlaps relocation')
        result = bytearray(data)
        at = p.get_offset_from_rva(HOOK - IMAGE_BASE)
        result[at:at + len(ORIGINAL)] = hook_bytes()
        at = p.get_offset_from_rva(PROJECT_CALL - IMAGE_BASE)
        result[at:at + 5] = call_bytes(PROJECT_CALL, PROJECT_HELPER)
        for field in ('Misc_VirtualSize', 'SizeOfRawData'):
            struct.pack_into('<I', result, last.get_field_absolute_offset(field),
                             getattr(last, field) + APPEND_SIZE)
        struct.pack_into('<I', result, p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),
                         APPEND_RVA + APPEND_SIZE)
        result.extend(payload())
        return bytes(result)
    finally:
        p.close()


def review(source, candidate):
    if patch(source) != candidate:
        raise ValueError('Candidate differs from the exact availability transformer')
    p = pefile.PE(data=source)
    try:
        fields = [(p.sections[-1].get_field_absolute_offset(field), 4,
                   'Extend existing executable final section for the bounded availability helper')
                  for field in ('Misc_VirtualSize', 'SizeOfRawData')]
        fields += [(p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4,
                    'Map the appended availability helper'),
                   (p.get_offset_from_rva(HOOK - IMAGE_BASE), len(ORIGINAL),
                    'Use any owned eligible fighter for Team/Wall availability'),
                   (p.get_offset_from_rva(PROJECT_CALL - IMAGE_BASE), 5,
                    'Correct ordinary Team/Wall displayed 7–10 band after native midpoint projection')]
        return {'changes': [{'offset': at, 'size': size,
                             'source_sha256': sha(source[at:at + size]),
                             'candidate_sha256': sha(candidate[at:at + size]),
                             'purpose': purpose} for at, size, purpose in sorted(fields)],
                'appended_size': APPEND_SIZE,
                'appended_sha256': sha(candidate[len(source):])}
    finally:
        p.close()


def metadata():
    return {'scope': 'Legacy main battle list Team/Wall owned-fighter level availability',
            'source_sha256': BASE_SHA, 'hook_va': hex(HOOK), 'hook_size': len(ORIGINAL),
            'helper_rva': hex(APPEND_RVA), 'appended_size': APPEND_SIZE,
            'fighter_slots': 31, 'level_offset': '0x5ffc',
            'owned_reserves_included': True, 'other_modes_keep_original_predicate': True,
            'available_team_wall_colour': 'ffb1efdb', 'ordinary_7_to_10_range_corrected': True,
            'network_packets_unchanged': True, 'renderer_and_filters_unchanged': True,
            'graphical_validation': False, 'published': False}
