"""Quick software preview of icon framing without Blender (numpy + Pillow).

    python -m tools.item_icons_hd.preview --client "C:/Program Files (x86)/TIOnline" \
        --manifest assets/item-icons-hd-v1/manifest.json --ids 210 211 --out work/item-icons-hd/preview

Flat-shaded, nearest-texel output that uses exactly the projection contract of
framing.py and render_blender.py. It is a QA aid for camera, scale and texture
orientation, never a final icon.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from . import framing, mesh

LIGHT = (-0.5, -0.6, 0.62)


def rasterize(geometry, slot, canvas, texture=None):
    import numpy as np
    from PIL import Image
    frame = framing.frame(geometry.positions, slot, canvas)
    points = np.array([framing.to_blender(p) for p in geometry.positions]) - np.array(frame.center)
    yaw, pitch = math.radians(frame.yaw), math.radians(frame.pitch)
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    u = x * math.cos(yaw) + y * math.sin(yaw)
    depth = -x * math.sin(yaw) + y * math.cos(yaw)
    v = z * math.cos(pitch) + depth * math.sin(pitch)
    distance = depth * math.cos(pitch) - z * math.sin(pitch)
    width, height = canvas
    scale = (width if width >= height else height) / frame.ortho_scale
    sx, sy = width / 2 + u * scale, height / 2 - v * scale
    pixels = np.asarray(Image.open(texture).convert('RGB'), dtype=np.float32) if texture else None
    image = np.zeros((height, width, 4), np.float32)
    zbuffer = np.full((height, width), np.inf)
    uvs = np.array(geometry.uvs)
    normals = np.array([framing.to_blender(n) for n in geometry.normals])
    light = np.array(LIGHT) / np.linalg.norm(LIGHT)
    for a, b, c in geometry.triangles:
        xs, ys = sx[[a, b, c]], sy[[a, b, c]]
        x0, x1 = int(max(0, xs.min())), int(min(width - 1, xs.max()))
        y0, y1 = int(max(0, ys.min())), int(min(height - 1, ys.max()))
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        area = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(area) < 1e-9:
            continue
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / area
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        depth_here = w0 * distance[a] + w1 * distance[b] + w2 * distance[c]
        window = zbuffer[y0:y1 + 1, x0:x1 + 1]
        inside &= depth_here < window
        if not inside.any():
            continue
        window[inside] = depth_here[inside]
        if pixels is not None:
            uv = w0[..., None] * uvs[a] + w1[..., None] * uvs[b] + w2[..., None] * uvs[c]
            # Native V grows downward, like image rows.
            tu = (uv[..., 0] % 1) * (pixels.shape[1] - 1)
            tv = (uv[..., 1] % 1) * (pixels.shape[0] - 1)
            colour = pixels[tv.astype(int), tu.astype(int)]
        else:
            colour = np.full(gx.shape + (3,), 150.0)
        normal = normals[a] + normals[b] + normals[c]
        normal = normal / (np.linalg.norm(normal) or 1)
        shade = 0.45 + 0.55 * max(0.0, float(np.dot(normal, light)))
        block = image[y0:y1 + 1, x0:x1 + 1]
        block[inside, :3] = colour[inside] * shade
        block[inside, 3] = 255
    return Image.fromarray(image.clip(0, 255).astype(np.uint8), 'RGBA')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ids', type=int, nargs='*')
    parser.add_argument('--size', type=int, default=512)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for item in json.loads(args.manifest.read_text(encoding='utf-8'))['items']:
        if item['pipeline'] != 'render' or (args.ids and item['item_id'] not in args.ids):
            continue
        models = args.client / 'base/models'
        texture = item['textures'][0] if item['textures'] else ''
        canvas = (args.size * item['canvas'][0] // item['canvas'][1], args.size)
        image = rasterize(mesh.read(models / f"{item['models'][0]}.mdjx"), item['slot'], canvas,
                          models / texture if texture and (models / texture).is_file() else None)
        image.save(args.out / f"{item['item_id']}-preview.png")
        print('preview', item['item_id'])


if __name__ == '__main__':
    main()
