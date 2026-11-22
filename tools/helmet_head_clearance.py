"""Stop the male head poking through the back of the combat helmets.

All helmets are drawn over the head (showface=1), and helmet and head are
rigidly bound to the single "Bip01 Head" bone, so bind-pose geometry decides
clipping in every animation. The men's combat helmet shell (light, medium and
heavy, each with its damaged _0/_25 states) has a recess at the back of the
skull through which every male head shows (the Veteran head up to ~11 mm).
Renders of all other helmets show no such poke-through: only the neck below
the rim, which is intended.

The fix bulges the shell outward around the clipping points with a smooth
falloff. Only vertex positions change; topology, UVs, normals, weights and
the rig tail stay byte-for-byte the same. One pass, so no vertex moves
further than REACH + MARGIN.

Usage: python tools/helmet_head_clearance.py MODELS_DIR [--fix OUT_DIR]
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.mdjx_mesh import Mesh, encode, read  # noqa: E402

BONE = 'Bip01 Head'
HEADS = ('tio_vet_head', 'chr_man_head', 'chr_man_afro_head')
HELMETS = tuple(f'man_armor_combat_{weight}_head{state}'
                for weight in ('light', 'medium', 'heavy') for state in ('', '_0', '_25'))
MARGIN = 0.003  # clearance left between skin and shell, metres
ALIGNED = 0.6  # cosine between skin and shell normals for a through-the-shell clip
REACH = 0.015  # a shell face further behind the skin is an inner part, not a clip
BACK = 0.3  # skin facing backwards (normal z) = back of the skull
RADIUS = 0.05  # falloff from a pushed corner to its neighbours, about one shell triangle


def positions(mesh: Mesh) -> np.ndarray:
    return np.array([v.position for v in mesh.vertices], dtype=np.float64)


def unit_normals(mesh: Mesh) -> np.ndarray:
    normals = np.array([v.normal for v in mesh.vertices], dtype=np.float64)
    return normals / np.maximum(np.linalg.norm(normals, axis=1), 1e-12)[:, None]


def triangles(mesh: Mesh) -> np.ndarray:
    return np.array(mesh.indices, dtype=np.int64).reshape(-1, 3)


def rigid_to_head(mesh: Mesh) -> bool:
    names = {mesh.bones[j]['name'] for v in mesh.vertices for j, w in zip(v.joints, v.weights) if w > 0}
    return names == {BONE}


def ray_hits(origins: np.ndarray, directions: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Distances (rays x triangles) along each ray to each triangle, inf when missed."""
    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    e1, e2 = b - a, c - a
    p = np.cross(directions[:, None, :], e2[None])
    det = np.einsum('rtk,tk->rt', p, e1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
    s = origins[:, None, :] - a[None]
    u = np.einsum('rtk,rtk->rt', p, s) * inv
    q = np.cross(s, e1[None])
    v = np.einsum('rk,rtk->rt', directions, q) * inv
    t = np.einsum('tk,rtk->rt', e2, q) * inv
    hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-7)
    return np.where(hit, t, np.inf)


def nearest(origins: np.ndarray, directions: np.ndarray, corners: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest crossing distance and triangle for each ray (inf, -1 when missed)."""
    distance = np.full(len(origins), np.inf)
    triangle = np.full(len(origins), -1)
    for start in range(0, len(origins), 128):
        d = ray_hits(origins[start:start + 128], directions[start:start + 128], corners)
        index = d.argmin(1)
        best = d[np.arange(len(index)), index]
        distance[start:start + 128] = best
        triangle[start:start + 128] = np.where(np.isfinite(best), index, -1)
    return distance, triangle


def back_clips(points: np.ndarray, normals: np.ndarray, shell: np.ndarray, faces: np.ndarray,
               shell_facing: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Depth by which each back-of-skull skin point sticks out through the shell (0 = covered),
    and the shell triangle it crosses (-1 = none).

    A point clips when nothing of the shell covers it along its outward normal
    while a shell face turned the same way lies just behind it.
    """
    corners = shell[faces]
    ahead, _ = nearest(points, normals, corners)
    behind, triangle = nearest(points, -normals, corners)
    aligned = np.einsum('ik,ik->i', shell_facing[np.maximum(triangle, 0)], normals) > ALIGNED
    clips = np.isinf(ahead) & (behind <= REACH) & (triangle >= 0) & aligned & (normals[:, 2] > BACK)
    return np.where(clips, behind, 0.0), np.where(clips, triangle, -1)


def facing(mesh: Mesh) -> np.ndarray:
    """Unit outward direction of each triangle, from the authored vertex normals."""
    normals = unit_normals(mesh)[triangles(mesh)].sum(1)
    return normals / np.maximum(np.linalg.norm(normals, axis=1), 1e-12)[:, None]


def bulge(shell: np.ndarray, sources: np.ndarray, pushes: np.ndarray, radius: float = RADIUS) -> np.ndarray:
    """Smooth outward offset of shell vertices: each source pushes its surroundings along its push.

    Vertices sharing a position (UV seams) get identical offsets, so the shell never opens.
    """
    distance = np.linalg.norm(shell[:, None, :] - sources[None], axis=2)
    weight = np.clip(1 - (distance / radius) ** 2, 0, 1) ** 2
    lengths = np.linalg.norm(pushes, axis=1)
    strongest = (weight * lengths[None]).argmax(1)
    return pushes[strongest] * weight[np.arange(len(shell)), strongest][:, None]


def clear_back(helmet: Mesh, heads: list[Mesh]) -> tuple[Mesh, dict]:
    """Bulge the back of the shell once, sized by the deepest clip through each face.

    One pass on purpose: repeating it lets the moved rim catch neck points
    below it and the offsets pile up. What remains is reported, not hidden.
    """
    original = positions(helmet)
    faces, shell_facing = triangles(helmet), facing(helmet)
    skin = np.concatenate([positions(h) for h in heads])
    skin_normals = np.concatenate([unit_normals(h) for h in heads])
    depth, crossed = back_clips(skin, skin_normals, original, faces, shell_facing)
    clipped = np.flatnonzero(crossed >= 0)
    # The crossed face's corners carry the push; the falloff spreads it to neighbours.
    corners = faces[crossed[clipped]].ravel()
    pushes = np.repeat(skin_normals[clipped] * (depth[clipped] + MARGIN)[:, None], 3, axis=0)
    shell = original + bulge(original, original[corners], pushes) if len(clipped) else original
    before = float(depth.max())
    moved = np.linalg.norm(shell - original, axis=1)
    vertices = [replace(v, position=tuple(float(c) for c in p)) for v, p in zip(helmet.vertices, shell)]
    report = dict(max_clip_before_m=round(before, 5), moved_vertices=int((moved > 1e-9).sum()),
                  max_move_m=round(float(moved.max()), 5))
    return replace(helmet, vertices=vertices), report


def clip_depths(helmet: Mesh, heads: dict[str, Mesh]) -> dict[str, float]:
    shell, faces, shell_facing = positions(helmet), triangles(helmet), facing(helmet)
    return {name: round(float(back_clips(positions(h), unit_normals(h), shell, faces, shell_facing)[0].max()), 5)
            for name, h in heads.items()}


def run(models: Path, out: Path | None = None) -> dict:
    heads = {name: read(models / (name + '.mdjx')) for name in HEADS}
    result = {}
    for name in HELMETS:
        helmet = read(models / (name + '.mdjx'))
        if not rigid_to_head(helmet):
            raise ValueError(f'{name} is not rigidly bound to {BONE}')
        row = dict(clip_before_m=clip_depths(helmet, heads))
        if out is not None:
            fixed, row['fix'] = clear_back(helmet, list(heads.values()))
            row['clip_after_m'] = clip_depths(fixed, heads)
            out.mkdir(parents=True, exist_ok=True)
            (out / (name + '.mdjx')).write_bytes(encode(fixed))
        result[name] = row
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models', type=Path)
    parser.add_argument('--fix', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.models, args.fix), indent=1))


if __name__ == '__main__':
    main()
