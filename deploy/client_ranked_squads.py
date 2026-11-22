"""Bounded patch for the published Silver TrueSkill turn and score handlers."""
import hashlib
import struct

import pefile

from .client_equipment_batch import Code

BASE_SHA = 'a2845172c850fcc03b9ca93c1d8d95d8a7f797405e15469664f9ed0e78ed70e7'
LOCK_HOOK = 0x953975
SELECT_HOOK = 0x9539fa
SCORE_HOOK = 0x95471d
CAVE = 0xc23000 + 0xb5400
LOCK = bytes.fromhex('8b4728 3b45f8 0f95c0 88471f')
SELECT = bytes.fromhex('8b06 80781f00 755a')
SCORE = bytes.fromhex('e82e61d3ff')


def redirect(address: int, target: int, length: int, opcode: bytes = b'\xe9') -> bytes:
    return opcode + struct.pack('<i', target - address - 5) + b'\x90' * (length - 5)


def sites() -> tuple[tuple[int, bytes, bytes], ...]:
    lock = Code(CAVE)
    lock.emit('8b45fc 8378f001')  # first u32 of C6/14 opts into squad turns
    lock.branch('0f85', 'single')
    lock.emit('8b48f8')  # projected owner from the wire
    lock.emit('394f2c 0f95471f')  # 3B stores the same projected owner at soldier+2c
    lock.jump(LOCK_HOOK + len(LOCK))
    lock.label('single')
    lock.emit(LOCK.hex())
    lock.jump(LOCK_HOOK + len(LOCK))

    select = Code(CAVE + 0x40)
    select.emit('8b06 8b4028 3b45f8')  # select the lead once, unlock the whole squad
    select.branch('0f84', 'lead')
    select.jump(0x953a5c)
    select.label('lead')
    select.jump(SELECT_HOOK + len(SELECT))

    # The score reader only stores numeric fields. Apply it directly, just
    # like the roster reset, so it cannot be dropped with queued scene events.
    score = bytes.fromhex('8bc2 ff542404 c20400')
    extension = lock.finish(0x40) + select.finish(0x20) + score
    return (
        (LOCK_HOOK, LOCK, redirect(LOCK_HOOK, CAVE, len(LOCK))),
        (SELECT_HOOK, SELECT, redirect(SELECT_HOOK, CAVE + 0x40, len(SELECT))),
        (SCORE_HOOK, SCORE, redirect(SCORE_HOOK, CAVE + 0x60, len(SCORE), b'\xe8')),
        (CAVE, bytes(len(extension)), extension),
    )


def build(base: bytes) -> tuple[bytes, dict]:
    if hashlib.sha256(base).hexdigest() != BASE_SHA:
        raise ValueError('Expected published Silver 2026.11.12.2')
    pe = pefile.PE(data=base)
    relocs = {entry.rva for block in pe.DIRECTORY_ENTRY_BASERELOC
              for entry in block.entries if entry.type}
    candidate = bytearray(base)
    changes = []
    for address, before, after in sites():
        rva = address - pe.OPTIONAL_HEADER.ImageBase
        offset = pe.get_offset_from_rva(rva)
        if (len(before) != len(after) or base[offset:offset + len(before)] != before
                or any(rva - 3 <= entry < rva + len(before) for entry in relocs)):
            raise ValueError(f'Unexpected native site {address:#x}')
        candidate[offset:offset + len(before)] = after
        changes.append(dict(offset=offset, before_hex=before.hex(), after_hex=after.hex()))
    result = bytes(candidate)
    return result, dict(previous_sha256=BASE_SHA, updated_sha256=hashlib.sha256(result).hexdigest(),
                        changes=changes, appended_bytes=0, all_other_published_bytes_preserved=True)
