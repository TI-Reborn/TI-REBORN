"""Encode decorative, noninteractive native TI TILE v2 and TI SET resources.

The source is the installed, hash-pinned one-record forest ground TILE v2.
Only field values are changed; its native record layout is retained. A scene
has a1x1 all-zero gameplay footprint and signed model coordinates. Current
surroundings use type1 foreground, inside border anchors and outward pixel
offsets. Place ground.entries origin at(0,0); the map grid is not enlarged.

UVs are computed by the native renderer, not serialized in the TILE. The
frame and cached dimensions below cover the entire bitmap; pattern is zero.
For exact UV 0..1 the allocated texture dimensions must match these values.
Use power-of-two PNG canvases (e.g. transparent-padded 1024x1024 patches).
"""
from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Iterable

TILE_DONOR = Path(r"C:\Program Files (x86)\TIOnline\base\setting\forest\ground_forest_1.t")
TILE_DONOR_SHA256 = "f07e22b5edf2278dd0cb49fded5dbd3029a73008cc62faa3cf5e372eab25e4be"
SCENE_DONOR = Path(r"C:\Program Files (x86)\TIOnline\base\maps\forest_tree_v01.s")
SCENE_DONOR_SHA256 = "e03924f851028929b35ac2ec3501ceeb62ddf146d02f413180f164c8d580b729"
MAX_TEXTURE_SIZE = 1024


def _donor(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"Unrecognized native donor: {path}")
    return raw


def _basename(value: str, capacity: int, suffix: str | None = None) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9]+", value):
        raise ValueError("Expected an ASCII resource basename without a directory")
    encoded = value.encode("ascii")
    if len(encoded) > capacity:
        raise ValueError(f"Resource basename exceeds {capacity} bytes")
    if suffix and not value.lower().endswith(suffix):
        raise ValueError(f"Expected a {suffix} resource basename")
    return encoded


def _shortstring(raw: bytearray, offset: int, field_size: int, value: bytes) -> None:
    if len(value) >= field_size:
        raise ValueError("Value does not fit the native fixed ShortString")
    raw[offset:offset + field_size] = bytes((len(value),)) + value + bytes(field_size - len(value) - 1)


def encode_tile(texture_basename: str, width: int, height: int,
                screen_offset_x: int, screen_offset_y: int, *,
                render_type: int = 0) -> bytes:
    """Return a rectangular native sprite with full-frame UVs.

    Offsets are signed screen pixels relative to the isometric scene anchor.
    The corresponding model basename may be chosen independently by callers;
    the donor's informational t_file string stays empty.
    Type 1 is the noninteractive foreground path. Its world anchor must be
    inside the existing game grid; signed pixel offsets place its art outside.
    Type 0 is retained for reproducing historical cached-ground diagnostics.
    """
    texture = _basename(texture_basename, 128)
    for value in (width, height):
        if type(value) is not int or not 1 <= value <= MAX_TEXTURE_SIZE:
            raise ValueError("Texture dimensions must be integers in 1..1024")
    for value in (screen_offset_x, screen_offset_y):
        if type(value) is not int or not -32768 <= value <= 32767:
            raise ValueError("Screen offsets must fit signed 16-bit pixels")
    if type(render_type) is not int or render_type not in (0, 1):
        raise ValueError("Only ground type 0 and noninteractive foreground type 1 are supported")
    name = ("ti_" + Path(texture_basename).stem).encode("ascii")
    if len(name) > 64:
        raise ValueError("Texture stem is too long for a unique native texture_name")
    raw = bytearray(_donor(TILE_DONOR, TILE_DONOR_SHA256))
    if len(raw) != 544 or raw[:8] != b"TI TILE\0" or raw[10] != 2:
        raise ValueError("Expected the pinned 544-byte one-record TILE v2")
    struct.pack_into("<ii", raw, 28, 0, 0)  # Scene supplies world coordinates.
    struct.pack_into("<hh", raw, 48, screen_offset_x, screen_offset_y)
    struct.pack_into("<II", raw, 52, 0x00ffffff, 255)
    struct.pack_into("<HH", raw, 60, width, height)  # Frame dimensions.
    raw[64] = 0  # First and only frame; no donor atlas crop.
    raw[68:70] = bytes((render_type, 0))  # Native +0x2c Type_; +0x2d RenderAsTile=false.
    _shortstring(raw, 74, 65, name)
    _shortstring(raw, 139, 64, b"")
    _shortstring(raw, 203, 129, texture)
    struct.pack_into("<HH", raw, 334, width, height)  # Sprite/culling dimensions.
    raw[340:356] = bytes(16)  # Door/special/cell interaction fields.
    raw[440:539] = bytes(99)  # Associated sounds/actions/chained resources.
    raw[539:544] = b"\x01\0\0\0\0"  # Visible, no extra behavior.
    return bytes(raw)


def encode_scene(records: Iterable[tuple[str, int, int]]) -> bytes:
    """Return TI SET v2 with zero1x1 cells and signed decorative model anchors."""
    records = list(records)
    if len(records) > 65535:
        raise ValueError("Native scene count is limited to 65535 records")
    raw = bytearray(_donor(SCENE_DONOR, SCENE_DONOR_SHA256)[:32])
    if raw[:8] != b"TI SET\0\x02":
        raise ValueError("Expected the pinned TI SET v2 scene")
    struct.pack_into("<3H", raw, 12, 1, 1, len(records))
    struct.pack_into("<H", raw, 18, 2)  # Two bytes of cell data.
    struct.pack_into("<I", raw, 20, 0)  # No extra cell section.
    raw.extend(b"\0\0")
    for model, x, y in records:
        name = _basename(model, 63, ".t")
        for value in (x, y):
            if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
                raise ValueError("Scene anchors must fit signed 32-bit coordinates")
        raw.extend(bytes((len(name),)) + name + bytes(63 - len(name)))
        raw.extend(struct.pack("<ii", x, y))
    return bytes(raw)
