"""Turn a Blender HD weapon export into the client's MDJX mesh and atlas.

Input: the folder written by tools/hd_weapon_<name>_blender.py
(<name>_mesh.json with vertices/normals/UVs/triangles in native coordinates,
<name>_side.png with the side-projected paint, supersampled). Output: the
static MDJX mesh and a copy of the weapon atlas whose rectangle carries the
new paint. Only that rectangle changes; it must be free of every other mesh
that samples the atlas, which is checked against the installed client.

Usage: python tools/build_hd_weapon.py NAME BLENDER_OUT MODELS_DIR ATLAS OTHER_MESH... --out OUT_DIR
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.atlas_registration import uv_mask  # noqa: E402
from tools.mdjx_mesh import Mesh, Vertex, encode, read  # noqa: E402

CLEARANCE = 4  # pixels between the rectangle and any other mesh's UVs


def static_mesh(export: dict) -> Mesh:
    """A bone-less MDJX mesh (zero joint influences per vertex), as the original weapons."""
    vertices = [Vertex(tuple(v['position']), tuple(v['normal']), tuple(v['uv']), 0, (), ())
                for v in export['vertices']]
    indices = tuple(i for triangle in export['triangles'] for i in triangle)
    return Mesh(vertices, indices, [], 1, b'')


def flood(rgba: np.ndarray, rounds: int = 24) -> np.ndarray:
    """Extend opaque colours into transparent pixels so filtering never pulls in background."""
    rgb = rgba[..., :3].astype(np.float64)
    known = rgba[..., 3] >= 128
    for _ in range(rounds):
        if known.all():
            break
        total = np.zeros_like(rgb)
        count = np.zeros(known.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            shifted_known = np.roll(known, (dy, dx), (0, 1))
            total += np.roll(rgb, (dy, dx), (0, 1)) * shifted_known[..., None]
            count += shifted_known
        grow = ~known & (count > 0)
        rgb[grow] = total[grow] / count[grow][:, None]
        known = known | grow
    if not known.all():
        rgb[~known] = rgb[known].mean(0)
    return np.clip(np.round(rgb), 0, 255).astype(np.uint8)


def paint(atlas: Image.Image, side: Image.Image, rect: dict) -> Image.Image:
    """The atlas with the weapon's rectangle replaced by the downsampled side paint."""
    size = (rect['w'], rect['h'])
    rgba = np.asarray(side.convert('RGBA'), dtype=np.float64)
    # Premultiply before resampling so transparent pixels add no colour.
    premultiplied = rgba.copy()
    premultiplied[..., :3] *= rgba[..., 3:4] / 255
    # Area averaging: the paint is an exact integer supersample, and Lanczos rings at part edges.
    small = np.stack([np.asarray(Image.fromarray(premultiplied[..., c].astype(np.float32), 'F').resize(size, Image.Resampling.BOX))
                      for c in range(4)], -1)
    alpha = np.clip(small[..., 3], 0, 255)
    colour = np.where(alpha[..., None] > 1, small[..., :3] * 255 / np.maximum(alpha[..., None], 1), 0)
    patch = flood(np.dstack([np.clip(colour, 0, 255), alpha]))
    out = atlas.convert('RGB').copy()
    out.paste(Image.fromarray(patch, 'RGB'), (rect['x'], rect['y']))
    return out


def rectangle_is_free(rect: dict, others: list[Path], size: int) -> int:
    """Pixels of other meshes inside the rectangle grown by CLEARANCE (0 = free)."""
    mask = np.asarray(uv_mask(others, size)) > 0
    y0, x0 = max(0, rect['y'] - CLEARANCE), max(0, rect['x'] - CLEARANCE)
    return int(mask[y0:rect['y'] + rect['h'] + CLEARANCE, x0:rect['x'] + rect['w'] + CLEARANCE].sum())


def uv_inside(mesh: Mesh, rect: dict, size: int, tolerance: float = 0.5) -> bool:
    cols = [v.uv[0] * size for v in mesh.vertices]
    rows = [(v.uv[1] % 1) * size for v in mesh.vertices]
    return (min(cols) >= rect['x'] - tolerance and max(cols) <= rect['x'] + rect['w'] + tolerance
            and min(rows) >= rect['y'] - tolerance and max(rows) <= rect['y'] + rect['h'] + tolerance)


def build(name: str, blender_out: Path, models: Path, atlas_name: str, others: list[str], out: Path) -> dict:
    export = json.loads((blender_out / f'{name}_mesh.json').read_text(encoding='utf-8'))
    rect = export['rect']
    atlas = Image.open(models / atlas_name)
    if atlas.size[0] != atlas.size[1]:
        raise ValueError('Expected a square atlas')
    busy = rectangle_is_free(rect, [models / f'{m}.mdjx' for m in others], atlas.size[0])
    if busy:
        raise ValueError(f'{busy} pixels of other meshes inside the {name} rectangle')
    mesh = static_mesh(export)
    if not uv_inside(mesh, rect, atlas.size[0]):
        raise ValueError('Mesh UVs leave the rectangle')
    raw = encode(mesh)
    if encode(read_bytes(raw)) != raw:
        raise ValueError('MDJX round trip failed')
    out.mkdir(parents=True, exist_ok=True)
    (out / f'weapon_{name}.mdjx').write_bytes(raw)
    painted = paint(atlas, Image.open(blender_out / f'{name}_side.png'), rect)
    painted.save(out / atlas_name, format='JPEG', quality=98, subsampling=0)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(weapon=name, vertices=len(mesh.vertices), triangles=len(mesh.indices) // 3, rect=rect,
                  source_mesh_sha256=digest(models / f'weapon_{name}.mdjx'), source_atlas_sha256=digest(models / atlas_name),
                  mesh_sha256=digest(out / f'weapon_{name}.mdjx'), atlas_sha256=digest(out / atlas_name),
                  others_checked=sorted(others))
    (out / f'{name}.json').write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    return report


def read_bytes(raw: bytes) -> Mesh:
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'mesh.mdjx'
        path.write_bytes(raw)
        return read(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('blender_out', type=Path)
    parser.add_argument('models', type=Path)
    parser.add_argument('atlas')
    parser.add_argument('others', nargs='+')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.name, args.blender_out, args.models, args.atlas, args.others, args.out)))


if __name__ == '__main__':
    main()
