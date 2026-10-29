"""Build the road-layout global map (v3) from the installed v2 map assets.

Locations are baked into the terrain by their own building silhouettes,
graded to the surrounding ground and labelled; per-location highlight
sprites (hover and current/destination) are cut from the same image; the
squad marker is a gold arrow in 32 headings. The manifest written next to the PNGs is the contract with
deploy/client_global_map_roads.py and the server bounds (tio.locations).

Offline tool: needs numpy, opencv-python, scikit-image and Pillow, which the
server does not use.

    python tools/build_global_map_v3.py --client "%LOCALAPPDATA%/TIO-Online" --out <folder>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from skimage.segmentation import slic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WIDTH, HEIGHT = 1819, 865
CLIENT_FOLDER = 'pda\\global-map-v3'
SOURCE_FOLDER = Path('base/pda/global-map-v2')
FONT = Path('C:/Windows/Fonts/bahnschrift.ttf')
MARKER_FRAMES = 32
MARKER_SIZE = 64
SPRITE_MARGIN = 10

# id: (v2 asset, baked label, centre and longest side in map px, town).
LOCATIONS = {
    2: ('denver', 'DENVER', (268, 98), 175, True),
    3: ('reservation', 'RES', (598, 226), 150, True),
    9: ('miner-s-town', 'MT', (762, 110), 130, True),
    4: ('military-outpost', 'MO', (1412, 60), 196, True),
    5: ('new-york', 'NY', (1300, 408), 290, True),
    8: ('military-zone', 'MZ', (1705, 312), 210, True),
    18: ('detroit', 'DETROIT', (716, 690), 195, True),
    10: ('prison', 'PRISON', (418, 576), 150, True),
    6: ('denver-base', 'DB', (98, 188), 84, False),
    7: ('military-outpost-base', 'MOB', (1502, 212), 84, False),
    11: ('ny-base', 'NYB', (1326, 606), 84, False),
    12: ('mz-base', 'MZB', (1546, 616), 84, False),
    13: ('mine-4-6', 'M 4-6', (740, 296), 80, False),
    14: ('mine-7-10', 'M 7-10', (1252, 146), 76, False),
    15: ('mine-11-15', 'M 11-15', (1214, 700), 82, False),
    16: ('mine-16-20', 'M 16-20', (1445, 666), 82, False),
    17: ('shooting-range', 'RANGE', (958, 322), 84, False),
    19: ('training-base-4-6', 'T 4-6', (628, 524), 78, False),
    20: ('training-base-7-10', 'T 7-10', (472, 98), 78, False),
    21: ('training-base-11-15', 'T 11-15', (1072, 664), 80, False),
    22: ('training-base-16-20', 'T 16-20', (1140, 138), 78, False),
}
LABEL_SIZE = {'NY': 54, 'MZ': 46, 'MO': 40, 'RES': 32, 'MT': 32, 'DENVER': 30, 'DETROIT': 30, 'PRISON': 28}
HOT_STROKE, HOT_GLOW = (255, 181, 92), (255, 140, 26)
SELECTED_STROKE = (255, 160, 60)
# Prison is entered only by a sentence: its hover outline reads as closed.
LOCKED_STROKE, LOCKED_GLOW = (236, 84, 64), (190, 36, 24)
LOCKED = {10}
HALO = (14, 9, 4)  # Dark rim that separates the outline from the sandy map.
GOLD_HI, GOLD_LO = (255, 222, 128), (178, 108, 24)


def world_x(px: float) -> float:
    return px * 1024 / WIDTH - 512


def world_y(py: float) -> float:
    return py * 1024 / HEIGHT - 512


def location_layer(folder: Path, asset: str, centre, size):
    image = cv2.imread(str(folder / f'gm-v2-{asset}.png'), cv2.IMREAD_UNCHANGED)
    ys, xs = np.where(image[..., 3] > 30)
    image = image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    scale = size / max(image.shape[:2])
    image = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    rgb = np.zeros((HEIGHT, WIDTH, 3), np.float32)
    alpha = np.zeros((HEIGHT, WIDTH), np.float32)
    x0, y0 = round(centre[0] - image.shape[1] / 2), round(centre[1] - image.shape[0] / 2)
    sx, sy, dx, dy = max(0, -x0), max(0, -y0), max(0, x0), max(0, y0)
    w, h = min(image.shape[1] - sx, WIDTH - dx), min(image.shape[0] - sy, HEIGHT - dy)
    rgb[dy:dy + h, dx:dx + w] = image[sy:sy + h, sx:sx + w, :3]
    alpha[dy:dy + h, dx:dx + w] = image[sy:sy + h, sx:sx + w, 3] / 255
    return rgb, alpha


def ring(mask, width=31):
    return (cv2.dilate(mask, np.ones((width, width), np.uint8)) > 0) & (mask == 0)


def grade(rgb, inside, around, terrain_lab, k=(.28, .5, .5)):
    """Pull the location's LAB statistics toward the ground around it."""
    lab = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    out = lab.copy()
    for ch in range(3):
        mc, sc = lab[..., ch][inside].mean(), lab[..., ch][inside].std() + 1e-3
        mt, st = terrain_lab[..., ch][around].mean(), terrain_lab[..., ch][around].std() + 1e-3
        out[..., ch] = (lab[..., ch] - mc) / sc * (sc * (1 - k[ch]) + st * k[ch] * 1.5) + mc * (1 - k[ch]) + mt * k[ch]
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR).astype(np.float32)


def house_cut(graded, mask, around, terrain_lab, band, delta_e=11):
    """Keep the core; at the edge keep only superpixels unlike the ground (roofs, yards, streets)."""
    x, y, w, h = cv2.boundingRect(mask)
    x0, y0, x1, y1 = max(0, x - 6), max(0, y - 6), min(WIDTH, x + w + 6), min(HEIGHT, y + h + 6)
    samples = terrain_lab[around].reshape(-1, 3)[::3].copy()
    _, _, ground = cv2.kmeans(samples, 6, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, .5),
                              2, cv2.KMEANS_PP_CENTERS)
    factor = 3
    crop = cv2.resize(np.clip(graded[y0:y1, x0:x1], 0, 255).astype(np.uint8), None, fx=factor, fy=factor,
                      interpolation=cv2.INTER_CUBIC)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    inside = cv2.resize(mask[y0:y1, x0:x1], (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    segments = slic(lab, n_segments=max(60, int(crop.shape[0] * crop.shape[1] / 420)), compactness=5,
                    convert2lab=False, start_label=0, channel_axis=-1)
    depth = cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5) / factor
    flat = segments.ravel()
    count = np.maximum(np.bincount(flat).astype(np.float32), 1)
    covered = np.bincount(flat, weights=inside.ravel()) / count
    mean_depth = np.bincount(flat, weights=depth.ravel()) / count
    mean_lab = np.stack([np.bincount(flat, weights=lab[..., c].ravel()) / count for c in range(3)], 1)
    is_ground = np.min(np.linalg.norm(mean_lab[:, None, :] - ground[None], axis=2), 1) < delta_e
    keep = (covered > .5) & ((mean_depth > band) | ~is_ground)
    kept = (keep[segments] & inside).astype(np.float32)
    out = np.zeros((HEIGHT, WIDTH), np.float32)
    out[y0:y1, x0:x1] = cv2.resize(kept, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    return out


def silhouette(alpha):
    """Filled smooth outline of the kept buildings (the highlight shape)."""
    mask = (alpha > .5).astype(np.uint8)
    mask = cv2.morphologyEx(cv2.dilate(mask, np.ones((5, 5), np.uint8)), cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = [c for c in contours if cv2.contourArea(c) > 40]
    filled = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.drawContours(filled, contours, -1, 255, cv2.FILLED)
    return filled, contours


def font(size):
    face = ImageFont.truetype(str(FONT), size)
    try:
        face.set_variation_by_name('Bold Condensed')
    except (OSError, ValueError):
        pass  # Older Bahnschrift without variations still renders the label.
    return face


def bake(folder: Path):
    terrain = cv2.imread(str(folder / 'gm-v2-terrain.png')).astype(np.float32)
    if terrain.shape[:2] != (HEIGHT, WIDTH):
        raise ValueError('Unexpected v2 terrain size')
    terrain_lab = cv2.cvtColor(terrain.astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    baked = terrain.copy()
    shapes = {}
    for town, (asset, _, centre, size, is_town) in LOCATIONS.items():
        rgb, alpha = location_layer(folder, asset, centre, size)
        mask = (alpha > .5).astype(np.uint8)
        around = ring(mask)
        graded = grade(rgb, mask > 0, around, terrain_lab)
        kept = house_cut(graded, mask, around, terrain_lab, band=14 if is_town else 9) * np.clip(alpha * 1.5, 0, 1)
        shadow = np.clip(cv2.GaussianBlur(np.roll(kept, (2, 1), (0, 1)), (0, 0), 1.8) - kept, 0, 1)
        baked *= (1 - shadow * .5)[..., None]
        baked[:] = baked * (1 - kept[..., None]) + graded * kept[..., None]
        shapes[town] = silhouette(kept)
    image = Image.fromarray(cv2.cvtColor(np.clip(baked, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)).convert('RGBA')
    shade = Image.new('RGBA', image.size, (0, 0, 0, 0))
    text = Image.new('RGBA', image.size, (0, 0, 0, 0))
    shade_draw, text_draw = ImageDraw.Draw(shade), ImageDraw.Draw(text)
    labels = {}
    for town, (_, label, centre, _, is_town) in LOCATIONS.items():
        size = LABEL_SIZE.get(label, 17)
        face, stroke = font(size), max(2, size // 11)
        shade_draw.text((centre[0] + 1, centre[1] + 3), label, font=face, fill=(0, 0, 0, 210), anchor='mm',
                        stroke_width=5, stroke_fill=(0, 0, 0, 210))
        text_draw.text(centre, label, font=face, fill=(255, 238, 200, 255) if is_town else (255, 214, 140, 255),
                       anchor='mm', stroke_width=stroke, stroke_fill=(24, 18, 10, 240))
        labels[town] = text_draw.textbbox(centre, label, font=face, anchor='mm', stroke_width=stroke)
    image = Image.alpha_composite(image, shade.filter(ImageFilter.GaussianBlur(3)))
    return Image.alpha_composite(image, text).convert('RGB'), shapes, labels


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def check_layout(shapes, labels):
    """Nothing overlaps; every server rectangle covers its footprint and road end."""
    from tio.locations import TOWNS, center
    footprints = {}
    for town, (_, contours) in shapes.items():
        x, y, w, h = cv2.boundingRect(np.vstack(contours))
        footprints[town] = (x, y, x + w, y + h)
    problems = []
    towns = sorted(footprints)
    for i, a in enumerate(towns):
        for b in towns[i + 1:]:
            if overlaps(footprints[a], footprints[b]):
                problems.append(f'footprints {a}/{b}')
            if overlaps(labels[a], labels[b]):
                problems.append(f'labels {a}/{b}')
        for b in towns:
            if b != a and overlaps(labels[a], footprints[b]):
                problems.append(f'label {a} on {b}')
    for town, (x0, y0, x1, y1) in footprints.items():
        bounds = [math.floor(world_x(x0)), math.floor(world_y(y0)), math.ceil(world_x(x1)) - 1, math.ceil(world_y(y1)) - 1]
        gx, gy = center(town)
        bounds = [min(bounds[0], gx - 2), min(bounds[1], gy - 2), max(bounds[2], gx + 2), max(bounds[3], gy + 2)]
        if tuple(bounds) != TOWNS[town]:
            problems.append(f'server bounds of {town} must be {bounds}, not {list(TOWNS[town])}')
    if problems:
        raise ValueError('Layout check failed: ' + '; '.join(problems))
    return footprints


def highlight(image: Image.Image, filled, contours, *, hot: bool, locked: bool = False):
    """Lit location plus its outline: solid glowing (hover) or dashed (selected)."""
    x, y, w, h = cv2.boundingRect(np.vstack(contours))
    x0, y0 = max(0, x - SPRITE_MARGIN), max(0, y - SPRITE_MARGIN)
    x1, y1 = min(WIDTH, x + w + SPRITE_MARGIN), min(HEIGHT, y + h + SPRITE_MARGIN)
    crop = np.asarray(image)[y0:y1, x0:x1]
    inside = cv2.GaussianBlur(filled[y0:y1, x0:x1].astype(np.float32) / 255, (0, 0), .6)
    shifted = [c - np.array([[x0, y0]]) for c in contours]
    scale = 4  # Supersampled stroke for smooth anti-aliased outlines.
    stroke = np.zeros(((y1 - y0) * scale, (x1 - x0) * scale), np.uint8)
    for contour in shifted:
        points = cv2.approxPolyDP(contour, 1.2, True)[:, 0, :] * scale + scale // 2
        if hot:
            cv2.polylines(stroke, [points], True, 255, round(2.4 * scale), cv2.LINE_AA)
        else:
            dash(stroke, points, on=7 * scale, off=5 * scale, width=2 * scale)
    stroke = cv2.resize(stroke, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    glow = cv2.GaussianBlur(stroke, (0, 0), 4 if hot else 3) * (2.2 if hot else 1.4)
    halo = np.clip(cv2.GaussianBlur(cv2.dilate(stroke, np.ones((3, 3), np.uint8)), (0, 0), 1.6) * 1.8, 0, .8) * (1 - inside)
    stroke_colour = (LOCKED_STROKE if locked else HOT_STROKE) if hot else SELECTED_STROKE
    rgba = np.zeros((y1 - y0, x1 - x0, 4), np.float32)
    rgba[..., :3] = crop
    rgba[..., 3] = inside
    for colour, weight in ((LOCKED_GLOW if locked else HOT_GLOW, np.clip(glow, 0, .7)), (HALO, halo),
                           (stroke_colour, stroke)):
        a = weight[..., None]
        rgba[..., :3] = rgba[..., :3] * (1 - a) + np.array(colour, np.float32) * a
        rgba[..., 3] = rgba[..., 3] + weight * (1 - rgba[..., 3])
    rgba[..., 3] *= 255
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), 'RGBA'), (x0, y0, x1, y1)


def dash(canvas, points, *, on, off, width):
    closed = np.vstack([points, points[:1]]).astype(np.float32)
    phase = 0.0
    for p, q in zip(closed, closed[1:]):
        length = float(np.linalg.norm(q - p))
        start = 0.0
        while start < length:
            cycle = (phase + start) % (on + off)
            step = (on - cycle) if cycle < on else (on + off - cycle)
            end = min(length, start + step)
            if cycle < on:
                a, b = p + (q - p) * start / length, p + (q - p) * end / length
                cv2.line(canvas, tuple(map(int, a)), tuple(map(int, b)), 255, width, cv2.LINE_AA)
            start = end
        phase += length


def marker_frames():
    """Gold navigation arrow; frame k points k*360/32 degrees clockwise from +x on screen.

    Each frame is drawn already turned, so the metal light stays top-left.
    """
    unit = 16
    side = MARKER_SIZE * unit
    arrow = ((13, 0), (-8, -8), (-3.5, 0), (-8, 8))
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    shade = np.clip(((xx + yy) / (2 * side) - .3) / .4, 0, 1)[..., None]
    gold = np.array(GOLD_HI, np.float32) * (1 - shade) + np.array(GOLD_LO, np.float32) * shade
    frames = []
    for k in range(MARKER_FRAMES):
        turn = k * 2 * math.pi / MARKER_FRAMES
        cos, sin = math.cos(turn), math.sin(turn)
        points = [(side / 2 + (x * cos - y * sin) * unit, side / 2 + (x * sin + y * cos) * unit) for x, y in arrow]
        picture = Image.new('L', (side, side), 0)
        ImageDraw.Draw(picture).polygon(points, fill=255)
        shape = np.asarray(picture).astype(np.float32) / 255
        # Soft bevel: darker rim inside, a highlight on the lit edges.
        depth = cv2.distanceTransform((shape > .5).astype(np.uint8), cv2.DIST_L2, 5) / unit
        bevel = np.clip(1 - depth / 1.2, 0, 1)
        lit = np.clip(shape - np.roll(shape, (-unit // 2, -unit // 2), (0, 1)), 0, 1) * bevel
        body = gold * (1 - .25 * bevel[..., None]) + 255 * .35 * lit[..., None]
        rim = cv2.GaussianBlur(np.clip(cv2.dilate(shape, np.ones((unit * 3 // 2,) * 2, np.uint8)) - shape, 0, 1),
                               (0, 0), unit * .25)
        glow = np.clip(cv2.GaussianBlur(shape, (0, 0), unit * 3.2) * 2.0, 0, .8)
        rgba = np.zeros((side, side, 4), np.float32)
        for colour, weight in ((np.array(HOT_GLOW, np.float32), glow), (np.array(HALO, np.float32), rim), (body, shape)):
            a = weight[..., None]
            rgba[..., :3] = rgba[..., :3] * (1 - a) + colour * a
            rgba[..., 3] = rgba[..., 3] + weight * (1 - rgba[..., 3])
        rgba[..., 3] *= 255
        frame = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), 'RGBA')
        frames.append(frame.resize((MARKER_SIZE, MARKER_SIZE), Image.LANCZOS))
    return frames


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(client: Path, out: Path) -> dict:
    folder = client / SOURCE_FOLDER
    image, shapes, labels = bake(folder)
    footprints = check_layout(shapes, labels)
    target = out / 'base/pda/global-map-v3'
    target.mkdir(parents=True, exist_ok=True)

    def save(picture: Image.Image, stem: str) -> dict:
        path = target / f'{stem}.png'
        picture.save(path, optimize=True)
        return {'path': f'{CLIENT_FOLDER}\\{stem}.png', 'sha256': sha256(path), 'size': path.stat().st_size}

    import PIL
    import skimage
    # PNG bytes depend on these libraries; the release build checks the hashes.
    built_with = {'numpy': np.__version__, 'opencv-python': cv2.__version__,
                  'scikit-image': skimage.__version__, 'Pillow': PIL.__version__}
    manifest = {'built_with': built_with, 'map': {**save(image, 'gm3-map'), 'pixels': [WIDTH, HEIGHT]},
                'locations': [], 'marker': {'pixels': [MARKER_SIZE, MARKER_SIZE], 'frames': []}}
    for town, (asset, label, _, _, _) in sorted(LOCATIONS.items()):
        filled, contours = shapes[town]
        entry = {'id': town, 'asset': asset, 'label': label, 'footprint': list(footprints[town])}
        # Short unique stems: the native loader caches textures by bare stem.
        for kind, hot in (('hover', True), ('selected', False)):
            sprite, rect = highlight(image, filled, contours, hot=hot, locked=town in LOCKED)
            entry[kind] = save(sprite, f'gm3{kind[0]}-{town:02d}')
            entry['rect'] = list(rect)
        manifest['locations'].append(entry)
    for k, frame in enumerate(marker_frames()):
        manifest['marker']['frames'].append(save(frame, f'gm3m-{k:02d}'))
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--client', type=Path, required=True, help='installed client folder with base/pda/global-map-v2')
    parser.add_argument('--out', type=Path, required=True, help='output folder (base/pda/global-map-v3 and manifest.json)')
    arguments = parser.parse_args()
    result = build(arguments.client, arguments.out)
    print(json.dumps({'map': result['map']['sha256'], 'locations': len(result['locations']),
                      'marker_frames': len(result['marker']['frames'])}))
