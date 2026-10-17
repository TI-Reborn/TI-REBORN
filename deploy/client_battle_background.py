"""Checked native queue wakeup for the original Windows client.

An unfocused client enqueues battle callbacks without waking its queue once
the loading overlay closes. Keep the original queue scheduler, delays and
pause flag, but let each received callback wake it in the background too.
This pure transformer does not write clients, publish files or touch a server.
"""
from __future__ import annotations

import hashlib

import pefile


BASE_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
PATCHED_SHA = '2ed6fac47bd478d37b8ef76001b124b5b2da2ef84460c5b0648b3284e0761b91'
IMAGE_BASE = 0x400000
GATE_VA = 0x6f6aff
GATE_FILE_OFFSET = 0x2f5eff
SPAN_VA = 0x6f6ae3
BEFORE = b'\x74\x1a'  # JE: skip queue wakeup when unfocused and overlay == 0.
AFTER = b'\x90\x90'   # Continue into the original 6f57a8 queue wakeup.
ORIGINAL_SPAN = bytes.fromhex(
    'a168e576008b0066beb1ffe8752ad1ff84c0750aa1ace27600803800741a'
    'a114e376008b0005d00700008b55fc89420c8b45fce88decffff'
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def restore(data: bytes) -> bytes:
    """Return the exact original image, or reject any unrelated modification."""
    candidate = bytes(data)
    try:
        pe = pefile.PE(data=candidate)
        if (pe.FILE_HEADER.Machine != 0x14c
                or pe.OPTIONAL_HEADER.Magic != 0x10b
                or pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE
                or pe.get_offset_from_rva(GATE_VA - IMAGE_BASE) != GATE_FILE_OFFSET):
            raise ValueError('Unexpected original client PE layout')
        offset = pe.get_offset_from_rva(SPAN_VA - IMAGE_BASE)
    except pefile.PEFormatError as error:
        raise ValueError('Unsupported native client PE') from error

    gate = candidate[GATE_FILE_OFFSET:GATE_FILE_OFFSET + len(BEFORE)]
    if gate not in (BEFORE, AFTER):
        raise ValueError('Native background queue gate differs')
    restored = bytearray(candidate)
    restored[GATE_FILE_OFFSET:GATE_FILE_OFFSET + len(BEFORE)] = BEFORE
    original = bytes(restored)
    if original[offset:offset + len(ORIGINAL_SPAN)] != ORIGINAL_SPAN:
        raise ValueError('Native queue wakeup span differs')
    if _digest(original) != BASE_SHA:
        raise ValueError('Expected exact original client; unrelated edits are rejected')
    if gate == AFTER and _digest(candidate) != PATCHED_SHA:
        raise ValueError('Unexpected background queue candidate')
    return original


def patch(data: bytes) -> bytes:
    """Patch only the two-byte gate; already checked candidates are idempotent."""
    original = restore(data)
    changed = bytearray(original)
    changed[GATE_FILE_OFFSET:GATE_FILE_OFFSET + len(AFTER)] = AFTER
    candidate = bytes(changed)
    if _digest(candidate) != PATCHED_SHA:
        raise ValueError('Background queue candidate hash differs')
    return candidate


def patch_plan(previous: bytes, updated: bytes) -> dict:
    """Prove the precise edit and exact restoration of the complete executable."""
    original = restore(previous)
    if patch(previous) != bytes(updated):
        raise ValueError('Background queue candidate differs from checked patch')
    restored = restore(updated)
    if restored != original:
        raise ValueError('Background queue restoration differs')
    return {
        'base_sha256': BASE_SHA,
        'patched_sha256': PATCHED_SHA,
        'restored_sha256': _digest(restored),
        'changed_file_offsets': [GATE_FILE_OFFSET, GATE_FILE_OFFSET + 1],
        'gate_va': GATE_VA,
        'before_hex': BEFORE.hex(),
        'after_hex': AFTER.hex(),
        'unchanged_size': len(original) == len(updated),
        'scope': 'Wake the original callback queue on enqueue; focus, input and rendering unchanged',
    }
