"""Export selected classic-A native density sheets, retaining native chrome."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_ui_hd_icons as adapter
from tools.export_ui_hd_icon_assets import decode_native, SYMBOLS

SOURCE_SHA = 'aa43dce3978a4841581f5f96b7dce04ed17c291d8b520aab811c3909abb3fbdd'
SUPPLEMENT_SHA = 'ee0404215c7c22ef380bb55f767d805af94807dc9a52742f775d68d4a04d35db'
SUPPLEMENT_SYMBOLS = ('ratings', 'mail', 'wrench', 'filter', 'zoom-minus', 'zoom-plus')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(path):
    data = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(data), 'sha256': sha(data)}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    return record(path)


def png(image):
    output = io.BytesIO()
    image.save(output, format='PNG', compress_level=9)
    return output.getvalue()


def crop_symbol(master, index, columns, rows):
    x, y = index % columns, index // columns
    bounds = (x * master.width // columns, y * master.height // rows,
              (x + 1) * master.width // columns, (y + 1) * master.height // rows)
    cell = master.crop(bounds)
    alpha = cell.getchannel('A')
    bbox = alpha.getbbox()
    assert bbox and alpha.getextrema()[0] == 0
    return cell.crop(bbox), {'cell': list(bounds), 'alpha_bbox': list(bbox),
                             'weak_alpha_preserved': True}


def glyph(crop, size):
    image = Image.new('RGBA', size)
    # Large horizontal buttons retain their plate dimensions and use a compact
    # center glyph. Sidebar/compact controls retain a three-logical-pixel inset.
    maximum = min(size) - 2 * max(2, round(min(size) * .10))
    ratio = min(maximum / crop.width, maximum / crop.height)
    assert ratio <= 1
    target = (max(1, round(crop.width * ratio)), max(1, round(crop.height * ratio)))
    fitted = crop.resize(target, Image.Resampling.LANCZOS)
    image.alpha_composite(fitted, ((size[0] - target[0]) // 2, (size[1] - target[1]) // 2))
    return image


def state_glyph(image, state):
    if state == 1:
        # Native disabled frame1 is grayscale. Preserve original alpha.
        gray = ImageOps.grayscale(image).convert('RGBA')
        gray.putalpha(image.getchannel('A'))
        return gray
    if state == 3:
        return ImageEnhance.Brightness(image).enhance(1.12)
    return image.copy()


def native_frame(original, width, height, state):
    columns = original.width // width
    return original.crop((state % columns * width, state // columns * height,
                          (state % columns + 1) * width, (state // columns + 1) * height))


def compose_frame(art, native, blank, width, height, density, state):
    size = (adapter.physical(width, density), adapter.physical(height, density))
    icon = state_glyph(glyph(art, size), state)
    if width == height == 40:
        return icon, {'native_perimeter_retained': 'sidebar chrome is a separate native control',
                      'glyph_only': True}
    old = native_frame(native, width, height, state)
    if width == height == 16:
        # Native search has no plate. Only its hover frame has corner brackets;
        # keep those brackets, rather than introducing an inventory background.
        corners = Image.new('RGBA', (width, height))
        if state == 3:
            for box in ((0, 0, width, 1), (0, height-1, width, height),
                        (0, 1, 1, height-1), (width-1, 1, width, height-1)):
                corners.paste(old.crop(box), (box[0], box[1]))
        frame = corners.resize(size, Image.Resampling.LANCZOS)
        frame.alpha_composite(icon)
        return frame, {'native_perimeter_retained': 'native hover brackets only',
                       'glyph_only': True, 'native_transparent_background_retained': True}
    # Only asset composition changes: plate perimeter comes byte-for-byte from
    # the original state at100%; its interior uses the existing native empty
    # inventory plate, avoiding old glyph remnants. Generated artwork is never
    # hand-painted, erased or traced.
    border = 3 if width == 88 else 1
    empty = native_frame(blank, 100, 32, state).resize((width, height), Image.Resampling.LANCZOS)
    assembled = empty.copy()
    assembled.paste(old.crop((0, 0, width, border)), (0, 0))
    assembled.paste(old.crop((0, height - border, width, height)), (0, height - border))
    assembled.paste(old.crop((0, border, border, height - border)), (0, border))
    assembled.paste(old.crop((width - border, border, width, height - border)), (width - border, border))
    frame = assembled.resize(size, Image.Resampling.LANCZOS)
    frame.alpha_composite(icon)
    if density == 100:
        for box in [(0, 0, width, border), (0, height - border, width, height),
                    (0, border, border, height - border), (width - border, border, width, height - border)]:
            assert frame.crop(box).tobytes() == old.crop(box).tobytes()
    return frame, {'native_perimeter_retained': True, 'perimeter_logical_pixels': border,
                   'empty_interior_source': 'base/pda/icon_button_inventory.png',
                   'generated_frame': False}


def build(output):
    if output.exists():
        raise ValueError('Preserve existing selected assets; use a new report output')
    source = ROOT / 'reports/ui-hd-assets/icons/source/a-classic-hd-clean.png'
    supplement = ROOT / 'reports/ui-hd-assets/icons/source/a-classic-supplement-v1.png'
    assert sha(source.read_bytes()) == SOURCE_SHA
    assert sha(supplement.read_bytes()) == SUPPLEMENT_SHA
    a, extra = Image.open(source), Image.open(supplement)
    assert a.mode == extra.mode == 'RGBA' and extra.size == (1536, 1024)
    native_dir = Path(r'C:\Program Files (x86)\TIOnline\base\pda')
    blank_path = native_dir / 'icon_button_inventory.png'
    blank = decode_native(blank_path)
    crops = {name: crop_symbol(a, SYMBOLS.index(name), 4, 4)
             for name in SYMBOLS}
    crops.update({name: crop_symbol(extra, index, 3, 2)
                  for index, name in enumerate(SUPPLEMENT_SYMBOLS)})
    output.mkdir(parents=True)
    manifest = {**adapter.metadata(), 'result': 'OFFLINE_SELECTED_ASSETS_PASS',
                'selected_icon_style': 'A classic HD', 'source': record(source),
                'supplement': record(supplement), 'native_empty_plate': record(blank_path),
                'densities_percent': list(adapter.DENSITIES), 'native_adapter_installed': False,
                'client_installed': False, 'source_inputs_preserved': True,
                'state_order': ['normal', 'disabled', 'pressed', 'hover'],
                'state_art': {'normal': 'selected A palette', 'disabled': 'grayscale preserving alpha',
                              'pressed': 'selected A palette; stock click offset retained',
                              'hover': 'brightness1.12; stock hover overlay/fade retained'},
                'native_tint': 'Matched icon draws neutralize RGB only, retain original alpha.',
                'untouched_native_assets': ['base/pda/reading_glass.tga'], 'assets': []}
    review_rows = []
    for filename, symbol, width, height, site in adapter.RESOURCES:
        native_path = native_dir / filename
        native = decode_native(native_path)
        for density in adapter.DENSITIES:
            tile = (adapter.physical(width, density), adapter.physical(height, density))
            sheet = Image.new('RGBA', (tile[0] * 2, tile[1] * 2))
            frame_records = []
            for state in range(4):
                frame, chrome = compose_frame(crops[symbol][0], native, blank, width, height, density, state)
                x, y = state % 2 * tile[0], state // 2 * tile[1]
                sheet.alpha_composite(frame, (x, y))
                frame_records.append({'state': state, 'source_rect': [x, y, x + tile[0], y + tile[1]],
                                      'destination_logical_size': [width, height], **chrome})
            relative = Path('base') / Path(adapter.path_for(symbol, density).replace('\\', '/'))
            exported = write(output / 'assets' / relative, png(sheet))
            manifest['assets'].append({**exported, 'client_relative_path': relative.as_posix(),
                                       'native_resource': 'base/pda/' + filename,
                                       'native_original': record(native_path), 'symbol': symbol,
                                       'density': density, 'source_dimensions': list(sheet.size),
                                       'physical_tile': list(tile), 'logical_tile': [width, height],
                                       'columns': 2, 'frames': frame_records, 'crop': crops[symbol][1]})
            if density == 100:
                review_rows.append((symbol, sheet))
    for label, color in [('olive', (31, 43, 21, 255)), ('dark', (18, 20, 22, 255))]:
        review = Image.new('RGBA', (620, len(review_rows) * 65), color)
        from PIL import ImageDraw
        labels = ImageDraw.Draw(review)
        for index, (symbol, sheet) in enumerate(review_rows):
            # Only a source-over visual contact sheet; no artwork modification.
            labels.text((6, index*65+10), symbol, fill=(220, 225, 206, 255))
            tw, th = sheet.width//2, sheet.height//2
            for state in range(4):
                x, y = state%2*tw, state//2*th
                review.alpha_composite(sheet.crop((x,y,x+tw,y+th)),
                                       (150+state*112, index*65+3))
        write(output / ('selected-states-' + label + '.png'), png(review))
    manifest['checks'] = {'PASS': True, 'density_assets': len(manifest['assets']),
                          'perimeters_preserved_at100': True, 'generated_glyphs_downsampled_only': True,
                          'native_state_count_and_order_preserved': True,
                          'native_file_overwrites': 0, 'native_controls_changed': 0,
                          'installed_client_or_hosting_writes': 0}
    write(output / 'selected-assets-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    return {'PASS': True, 'manifest': str(output / 'selected-assets-manifest.json'),
            'manifest_sha256': sha((output / 'selected-assets-manifest.json').read_bytes()),
            'assets': len(manifest['assets']), 'native_adapter_installed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/ui-hd-integration/icons')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'reports/ui-hd-integration'):
        raise ValueError('Selected assets must stay in the dedicated report tree')
    print(json.dumps(build(output)))
