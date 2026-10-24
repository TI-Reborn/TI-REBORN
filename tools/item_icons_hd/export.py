"""Deterministic size exports from one approved master icon (Pillow).

Mirrors tools/WeaponIconPack: trim fully transparent margins, fit with the
aspect ratio kept, centre on a transparent canvas, downscale with Lanczos.
Wide sizes serve weapons and the native 64x32 inventory cell; square sizes
serve the barracks redesign and future HD densities (100/125/150/200 %).
"""
from __future__ import annotations

import argparse
from pathlib import Path

WIDE = ((64, 32), (128, 64), (256, 128), (512, 256))
SQUARE = ((64, 64), (128, 128), (256, 256), (512, 512))
PADDING = 0.06


def fit(image, size):
    from PIL import Image
    if image.mode != 'RGBA':
        raise ValueError('Master icons must keep an alpha channel')
    box = image.getbbox()
    if box is None:
        raise ValueError('Master icon is fully transparent')
    item = image.crop(box)
    width, height = size
    usable = (max(1, round(width * (1 - 2 * PADDING))), max(1, round(height * (1 - 2 * PADDING))))
    ratio = min(usable[0] / item.width, usable[1] / item.height)
    resized = item.resize((max(1, round(item.width * ratio)), max(1, round(item.height * ratio))), Image.LANCZOS)
    canvas = Image.new('RGBA', size, (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    return canvas


def export(master: Path, out: Path, stem: str) -> list[Path]:
    from PIL import Image
    image = Image.open(master)
    image.load()
    written = []
    for size in (*WIDE, *SQUARE):
        folder = out / f'{size[0]}x{size[1]}'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{stem}.png'
        fit(image, size).save(path, optimize=True)
        written.append(path)
    return written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('masters', type=Path, help='folder of approved <id>.png masters')
    parser.add_argument('out', type=Path)
    parser.add_argument('--prefix', default='tio_ii_')
    args = parser.parse_args()
    for master in sorted(args.masters.glob('*.png')):
        export(master, args.out, args.prefix + master.stem)
        print('exported', master.stem)


if __name__ == '__main__':
    main()
