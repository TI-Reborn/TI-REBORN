"""Read native MDJX geometry for icon rendering: skinned and static variants.

``tools/mdjx_mesh.py`` round-trips skinned fighter parts and therefore rejects
meshes without bones. Weapon models are static (no bones, zero influences per
vertex). Icons need only positions, normals, UVs and triangles, so this reader
accepts both layouts and never writes models.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import struct

MAX_VERTICES = 100_000
MAX_INDICES = 1_000_000
MAX_BONES = 512
MAX_INFLUENCES = 8


@dataclass(frozen=True)
class Geometry:
    positions: tuple[tuple[float, float, float], ...]
    normals: tuple[tuple[float, float, float], ...]
    uvs: tuple[tuple[float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    skinned: bool


def parse(raw: bytes) -> Geometry:
    if len(raw) < 16:
        raise ValueError('Truncated MDJX header')
    vertex_count, index_count, bone_count, flag = struct.unpack_from('<4I', raw)
    if (flag != 1 or not 0 < vertex_count <= MAX_VERTICES or not 0 < index_count <= MAX_INDICES
            or index_count % 3 or bone_count > MAX_BONES):
        raise ValueError('Unsupported MDJX header')
    at = 16
    positions, normals, uvs = [], [], []
    skinned = bone_count > 0
    for _ in range(vertex_count):
        influences = struct.unpack_from('<I', raw, at)[0]
        if influences > MAX_INFLUENCES or (influences == 0) == skinned:
            raise ValueError('Vertex influences do not match the bone table')
        floats = struct.unpack_from('<8f', raw, at + 4)
        if not all(math.isfinite(v) for v in floats):
            raise ValueError('Non-finite vertex data')
        positions.append(floats[0:3])
        normals.append(floats[3:6])
        uvs.append(floats[6:8])
        at += 40 + 8 * influences
    if at + 4 * index_count > len(raw):
        raise ValueError('Truncated MDJX index table')
    indices = struct.unpack_from(f'<{index_count}I', raw, at)
    if max(indices) >= vertex_count:
        raise ValueError('Triangle index outside the vertex table')
    triangles = tuple(tuple(indices[i:i + 3]) for i in range(0, index_count, 3))
    return Geometry(tuple(positions), tuple(normals), tuple(uvs), triangles, skinned)


def read(path: Path) -> Geometry:
    return parse(Path(path).read_bytes())
