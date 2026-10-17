"""Technically register the reviewed battle artwork into native atlas cells.

The source artwork is unchanged. Semantic crop fences include soft fringes,
instead of cutting the drifting source rows at nominal 209-pixel boundaries.
Only source placement and aspect-preserving downsampling change. All visible
master pixels must belong to exactly one of the original fifteen actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CELL = 184
CORE_ALPHA = 16
FRINGE = 8
INSET = 12
SOURCE_DENSITY = 184 / 209
MASTER_SHA = 'cc94853d3dcef6a5e8db282a0aad953c1ea2340502b64d78413e247bf29a22c3'
# Independently measured alpha >=16 bounds in the reviewed 1254x1254 master.
# Right and bottom are exclusive. Action order follows the original native
# 6-column atlas, not a rearrangement of the visible battle panel.
SPRITES = (
    ('backpack', (33, 52, 178, 205)),
    ('refresh', (237, 52, 394, 202)),
    ('next-turn', (442, 65, 615, 193)),
    ('grenade', (648, 60, 830, 201)),
    ('rifle', (845, 66, 1022, 208)),
    ('crosshair', (1056, 47, 1220, 213)),
    ('vest', (28, 259, 189, 432)),
    ('binoculars', (224, 273, 414, 432)),
    ('case', (440, 294, 608, 406)),
    ('standing', (657, 259, 813, 443)),
    ('kneeling', (865, 290, 1017, 431)),
    ('sight', (1053, 266, 1222, 435)),
    ('interaction', (26, 481, 189, 668)),
    ('prone', (208, 523, 411, 611)),
    ('reload', (448, 498, 615, 646)),
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bbox(image, threshold=CORE_ALPHA):
    return image.getchannel('A').point(lambda value: 255 if value >= threshold else 0).getbbox()


def metrics(image):
    core, all_alpha = bbox(image), bbox(image, 1)
    alpha = image.getchannel('A')
    values = list(alpha.tobytes())
    mass = sum(values)
    return {'core_bbox': list(core) if core else None,
            'alpha_bbox': list(all_alpha) if all_alpha else None,
            'core_center': [(core[0] + core[2]) / 2, (core[1] + core[3]) / 2] if core else None,
            'alpha_centroid': [sum((i % image.width + .5) * a for i, a in enumerate(values)) / mass,
                               sum((i // image.width + .5) * a for i, a in enumerate(values)) / mass] if mass else None,
            'alpha_mass': mass, 'visible_pixels': sum(a >= CORE_ALPHA for a in values)}


def register(crop):
    """Keep complete soft alpha inside the safe box; anchor its visible bbox."""
    original = bbox(crop)
    assert original
    full = bbox(crop, 1)
    cx, cy = (original[0] + original[2]) / 2, (original[1] + original[3]) / 2
    # Using the largest radius avoids losing an asymmetric antialias fringe
    # while keeping the visible glyph's bbox centered, rather than its mass.
    radius = max(cx - full[0], full[2] - cx, cy - full[1], full[3] - cy)
    factor = min(SOURCE_DENSITY, (CELL / 2 - INSET - 2) / radius)
    for _ in range(12):
        size = (max(1, round(crop.width * factor)), max(1, round(crop.height * factor)))
        resized = crop.resize(size, Image.Resampling.LANCZOS)
        core = bbox(resized)
        dx = round(CELL / 2 - (core[0] + core[2]) / 2)
        dy = round(CELL / 2 - (core[1] + core[3]) / 2)
        full = bbox(resized, 1)
        bounds = (dx + full[0], dy + full[1], dx + full[2], dy + full[3])
        if min(bounds[:2]) >= INSET and max(bounds[2:]) <= CELL - INSET:
            tile = Image.new('RGBA', (CELL, CELL))
            tile.alpha_composite(resized, (dx, dy))
            registered = metrics(tile)
            assert max(abs(c - CELL / 2) for c in registered['core_center']) <= .5
            assert sum(tile.getchannel('A').tobytes()) == sum(resized.getchannel('A').tobytes())
            return tile, {'scale': factor, 'resized_crop': list(size), 'paste': [dx, dy],
                          'no_alpha_clipping': True, 'registered': registered}
        factor *= .98
    raise AssertionError('Cannot register complete sprite inside safe box')


def repack(art, *, source_sha):
    """Shared, pinned-master registration for full builds and atlas-only fixes."""
    if source_sha != MASTER_SHA:
        raise ValueError('Battle glyph registration requires the reviewed master SHA')
    assert art.size == (1254, 1254)
    ownership = bytearray(art.width * art.height)
    atlas = Image.new('RGBA', (CELL * 6, CELL * 6))
    records = []
    for frame, (name, expected) in enumerate(SPRITES):
        fence = (expected[0] - FRINGE, expected[1] - FRINGE,
                 expected[2] + FRINGE, expected[3] + FRINGE)
        crop = art.crop(fence)
        measured = bbox(crop)
        global_box = tuple(v + fence[i % 2] for i, v in enumerate(measured))
        assert global_box == expected, (name, expected, global_box)
        for y in range(fence[1], fence[3]):
            for x in range(fence[0], fence[2]):
                if art.getpixel((x, y))[3] >= CORE_ALPHA:
                    index = y * art.width + x
                    assert ownership[index] == 0, (name, x, y)
                    ownership[index] = frame + 1
        tile, registration = register(crop)
        col, row = frame % 6, frame // 6
        atlas.alpha_composite(tile, (col * CELL, row * CELL))
        records.append({'frame': frame, 'action': name, 'source_core_bbox': list(expected),
                        'source_fence': list(fence), 'source': metrics(crop),
                        **registration})
    visible = bytes(art.getchannel('A').point(lambda v: 255 if v >= CORE_ALPHA else 0).tobytes())
    assert all(bool(alpha) == bool(owner) for alpha, owner in zip(visible, ownership)), 'Unassigned visible source alpha'
    for frame in range(15, 36):
        x, y = frame % 6, frame // 6
        assert atlas.crop((x * CELL, y * CELL, (x + 1) * CELL, (y + 1) * CELL)).getchannel('A').getbbox() is None
    count = sum(bool(v) for v in visible)
    assert count == 227876
    return atlas, records, count


def build(master, old_atlas, plates, output):
    if output.exists():
        raise ValueError('Preserve earlier candidates; use a fresh output directory')
    source_raw = master.read_bytes()
    art = Image.open(master).convert('RGBA')
    atlas, records, visible_count = repack(art, source_sha=sha(source_raw))
    old = Image.open(old_atlas).convert('RGBA')
    plate_sheet = Image.open(plates).convert('RGBA')
    assert old.size == atlas.size and plate_sheet.size == (CELL * 4, CELL)
    for frame, record in enumerate(records):
        col, row = frame % 6, frame // 6
        record['before'] = metrics(old.crop((col * CELL, row * CELL, (col + 1) * CELL, (row + 1) * CELL)))
    output.mkdir(parents=True)
    target = output / 'assets/base/ui-hd/battle-controls/hd4-bui-glyphs.png'
    target.parent.mkdir(parents=True)
    atlas.save(target, format='PNG', compress_level=9)
    # Actual unmodified plate chrome, paired old/new for all original actions.
    preview = Image.new('RGB', (6 * 260, 3 * 156), '#202019')
    draw = ImageDraw.Draw(preview)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    except OSError:
        font = ImageFont.load_default()
    plate = plate_sheet.crop((0, 0, CELL, CELL))
    for frame, record in enumerate(records):
        x, y = frame % 6, frame // 6
        draw.text((x * 260 + 4, y * 156 + 3), f"{frame}: {record['action']} | before / after", font=font, fill='#ececd9')
        for side, sheet in enumerate((old, atlas)):
            glyph = sheet.crop((x * CELL, y * CELL, (x + 1) * CELL, (y + 1) * CELL))
            button = Image.alpha_composite(plate, glyph).resize((124, 124), Image.Resampling.LANCZOS)
            preview.paste(button, (x * 260 + 4 + side * 128, y * 156 + 27), button)
    preview_path = output / 'registration-review.png'
    preview.save(preview_path)
    report = {'PASS': True, 'asset_only': True, 'native_review': None,
              'master_path': str(master.resolve()), 'master_sha256': sha(source_raw),
              'master_preserved': master.read_bytes() == source_raw,
              'old_atlas_path': str(old_atlas.resolve()), 'old_atlas_sha256': sha(old_atlas.read_bytes()),
              'plates_path': str(plates.resolve()), 'plates_sha256': sha(plates.read_bytes()),
              'client_relative_path': 'base/ui-hd/battle-controls/hd4-bui-glyphs.png',
              'path': str(target.resolve()), 'sha256': sha(target.read_bytes()), 'size': target.stat().st_size,
              'dimensions': list(atlas.size), 'source_tile': [CELL, CELL], 'logical_tile': [46, 46],
              'frame_count': 15, 'empty_cells': 21, 'all_visible_master_pixels_assigned_exactly_once': True,
              'visible_master_pixels': visible_count,
              'safe_inset_source_pixels': INSET, 'logical_bbox_center': [23, 23],
              'center_max_error_source_pixels': .5, 'color_channels_preserved_before_downsampling': True,
              'frames': records, 'review_path': str(preview_path.resolve())}
    proof = output / 'registration-proof.json'
    proof.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return {key: report[key] for key in ('PASS', 'path', 'sha256', 'size', 'review_path')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--old-atlas', type=Path, required=True)
    parser.add_argument('--plates', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.master, args.old_atlas, args.plates, args.output)))
