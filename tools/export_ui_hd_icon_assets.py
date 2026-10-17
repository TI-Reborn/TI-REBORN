"""Export generated 4x4 icon masters into reviewable density/source packs.

This is an asset preparation tool, not a client installer. It never changes
native files, callbacks, hit rectangles, the published manifest, or hosting.
The native adapter contracts deliberately distinguish source texels from
logical GUI dimensions. Pillow must not decode legacy BGRA BMP alpha as RGB.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SILVER_SHA = '87645b946317a645552c3c2a5fcf586784d3920548288e2312dfb9ace065df4d'
STYLES = {
    'a-classic-hd': 'a-classic-hd-clean.png',
    'b-tactical-clean': 'b-tactical-clean.png',
    'c-enamel': 'c-enamel-clean.png',
}
SYMBOLS = (
    'map', 'soldier', 'crates', 'money',
    'info', 'rifle', 'skills', 'squad',
    'handshake', 'search', 'refresh', 'settings',
    'check', 'left', 'right', 'close',
)
DENSITIES = (100, 125, 150, 200)
STATE_NAMES = ('normal', 'disabled', 'pressed', 'hover')
LOGICAL_SIZE = 40
INSET = 3
NATIVE = (
    ('map', 'pda_btn_1.png', (128, 128), (40, 40), 'city/map', '0xa62f75', '0x85bd4c'),
    ('soldier', 'pda_btn_2.png', (128, 128), (40, 40), 'city/squad-inventory', '0xa62f93', '0x85bda4'),
    (None, 'pda_btn_3.png', (128, 128), (40, 40), 'city/ratings', '0xa62fb1', '0x85bde7'),
    ('money', 'pda_btn_4.png', (128, 128), (40, 40), 'city/trade', '0xa62fcf', '0x85be3f'),
    ('info', 'squad_page_info_button.tga', (176, 62), (88, 31), 'squad/info', '0xa6bdc5', '0x9a6ff9'),
    ('rifle', 'squad_page_inventory_button.tga', (176, 62), (88, 31), 'squad/inventory', '0xa6be01', '0x9a7027'),
    (None, 'squad_page_inventory_opts_button.png', (62, 62), (31, 31), 'squad/options-wrench', '0xa6be1f', '0x9a7055'),
    (None, 'squad_page_mail_button.tga', (176, 62), (88, 31), 'squad/mail', '0xa6bde3', '0x9a709b'),
    ('squad', 'squad_page_clan_button.tga', (176, 62), (88, 31), 'squad/clan', '0xa6be3d', '0x9a7108'),
    ('handshake', 'squad_page_ally_button.tga', (176, 62), (88, 31), 'squad/ally', '0xa6be5b', '0x9a7134'),
    (None, 'squad_page_filters_button.tga', (64, 64), (32, 32), 'squad/filter', '0xa6be97', '0x9a6734'),
    ('refresh', 'squad_page_refresh_button.tga', (64, 64), (32, 32), 'squad/refresh', '0xa6beb5', '0x9aa3ce'),
    (None, 'squad_page_toggle_compact_one_button.tga', (64, 64), (32, 32), 'squad/compact-toggle-minus', '0xa6c01d', '0x9aa176'),
    (None, 'squad_page_toggle_compact_two_button.tga', (64, 64), (32, 32), 'squad/compact-toggle-plus', '0xa6c03b', '0x9a8a13'),
    ('search', 'btn_search.png', (32, 32), (16, 16), 'generic/search-shared-with-chat', '0xa6b8f7', '0xa4e760'),
    (None, 'reading_glass.tga', (128, 128), (64, 64), 'separate/reading-glass', '0xa6bf69', '0x7ecd9c'),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_native(path: Path) -> Image.Image:
    """Read file magic, retaining the fourth byte of legacy BI_RGB BMPs."""
    data = path.read_bytes()
    if data[:2] == b'BM':
        offset = struct.unpack_from('<I', data, 10)[0]
        width, height = struct.unpack_from('<ii', data, 18)
        bits = struct.unpack_from('<H', data, 28)[0]
        compression = struct.unpack_from('<I', data, 30)[0]
        if bits == 32 and compression == 0:
            return Image.frombytes('RGBA', (width, abs(height)), data[offset:],
                                   'raw', 'BGRA', 0, -1 if height > 0 else 1)
    with Image.open(io.BytesIO(data)) as image:
        return image.convert('RGBA')


def png_bytes(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format='PNG', optimize=False, compress_level=9)
    return out.getvalue()


def exclusive_write(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    return {'file': path.as_posix(), 'bytes': len(data), 'sha256': sha(data)}


def grid_bounds(size: tuple[int, int], index: int) -> tuple[int, int, int, int]:
    width, height = size
    col, row = index % 4, index // 4
    # Proportional integer edges cover odd sizes (e.g. 1254) exactly once.
    return (col * width // 4, row * height // 4,
            (col + 1) * width // 4, (row + 1) * height // 4)


def symbol_crop(master: Image.Image, index: int) -> tuple[Image.Image, dict]:
    bounds = grid_bounds(master.size, index)
    cell = master.crop(bounds)
    alpha = cell.getchannel('A')
    if alpha.getextrema()[0] != 0:
        raise ValueError(f'{SYMBOLS[index]} cell has no genuine transparent pixels')
    bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    if bbox is None:
        raise ValueError(f'Empty symbol: {SYMBOLS[index]}')
    # Keep all weak antialiasing/shadow pixels around the substantive shape.
    all_bbox = alpha.getbbox()
    assert all_bbox is not None
    return cell.crop(all_bbox), {
        'index': index, 'row': index // 4, 'column': index % 4,
        'grid_crop': list(bounds), 'alpha_crop_in_cell': list(all_bbox),
        'substantive_alpha_bbox': list(bbox),
    }


def fit_symbol(crop: Image.Image, density: int) -> tuple[Image.Image, dict]:
    pixels = LOGICAL_SIZE * density // 100
    inset = round(INSET * density / 100)
    maximum = pixels - 2 * inset
    factor = min(maximum / crop.width, maximum / crop.height)
    if factor > 1:
        raise ValueError('Source is too small: export must not enlarge generated art')
    size = (max(1, round(crop.width * factor)), max(1, round(crop.height * factor)))
    # Pillow RGBA resize uses premultiplied working pixels, avoiding dark fringes.
    icon = crop.resize(size, Image.Resampling.LANCZOS)
    result = Image.new('RGBA', (pixels, pixels))
    x, y = (pixels - size[0]) // 2, (pixels - size[1]) // 2
    result.alpha_composite(icon, (x, y))
    return result, {'size': [pixels, pixels], 'content_rect': [x, y, x + size[0], y + size[1]],
                    'logical_rect': [0, 0, LOGICAL_SIZE, LOGICAL_SIZE],
                    'inset_physical_px': inset, 'source_downsample_factor': factor,
                    'normalized_uv': [0, 0, 1, 1]}


def alpha_proof(icon: Image.Image) -> dict:
    alpha = icon.getchannel('A')
    extrema = alpha.getextrema()
    assert extrema[0] == 0 and extrema[1] > 0
    assert alpha.getpixel((0, 0)) == 0 and alpha.getpixel((icon.width - 1, icon.height - 1)) == 0
    # Test actual source-over composition against two GUI backgrounds.
    backgrounds = ((31, 43, 21, 255), (18, 20, 22, 255))
    for color in backgrounds:
        composed = Image.alpha_composite(Image.new('RGBA', icon.size, color), icon)
        assert composed.getpixel((0, 0)) == color
        assert composed.getchannel('A').getextrema() == (255, 255)
    return {'alpha_extrema': list(extrema), 'transparent_corners': True,
            'source_over_olive_and_dark': True, 'straight_alpha_png': True}


def atlas(icon: Image.Image, density: int) -> tuple[Image.Image, list[dict]]:
    """128*D square, native 3-column 40*D linear state ordering, with padding."""
    side, tile = 128 * density // 100, LOGICAL_SIZE * density // 100
    result = Image.new('RGBA', (side, side))
    rects = []
    for index, name in enumerate(STATE_NAMES):
        x, y = index % 3 * tile, index // 3 * tile
        result.alpha_composite(icon, (x, y))
        box = [x, y, x + tile, y + tile]
        rects.append({'state': name, 'native_frame': index, 'source_rect_px': box,
                      'normalized_image_uv': [v / side for v in box],
                      'destination_logical_rect': [0, 0, 40, 40],
                      'destination_physical_rect': [0, 0, tile, tile]})
        assert result.crop(box).tobytes() == icon.tobytes()
    assert side // tile == 3
    return result, rects


def native_contracts(root: Path) -> list[dict]:
    result = []
    for symbol, filename, size, tile, semantics, load, ctor in NATIVE:
        path = root / filename
        data = path.read_bytes()
        image = decode_native(path)
        if image.size != size:
            raise ValueError('Unexpected native source dimensions: ' + filename)
        result.append({'resource': 'base/pda/' + filename, 'symbol': symbol,
                       'mapping_confirmed': symbol is not None, 'semantics': semantics,
                       'original_sha256': sha(data), 'source_dimensions': list(size),
                       'logical_draw_tile': list(tile), 'format_magic': data[:8].hex(),
                       'alpha_extrema': list(image.getchannel('A').getextrema()),
                       'load_call_preferred_va': load, 'control_ctor_or_callback_va': ctor,
                       'density_physical_tile': {str(d): [v * d / 100 for v in tile] for d in DENSITIES}})
    return result


def build(source_dir: Path, output: Path, native_dir: Path, silver: Path,
          tactical_filename: str = STYLES['b-tactical-clean']) -> dict:
    if sha(silver.read_bytes()) != SILVER_SHA:
        raise ValueError('Native evidence must use the frozen published .12 Silver')
    if output.exists():
        raise ValueError('Output already exists; choose a new directory to preserve previous artifacts')
    originals = native_contracts(native_dir)
    if Path(tactical_filename).name != tactical_filename:
        raise ValueError('Tactical source override must be a filename inside source-dir')
    source_names = dict(STYLES)
    source_names['b-tactical-clean'] = tactical_filename
    prepared = {}
    for style, filename in source_names.items():
        path = source_dir / filename
        data = path.read_bytes()
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'PNG' or image.mode != 'RGBA':
                raise ValueError('Generated masters must be genuine RGBA PNG: ' + filename)
            master = image.copy()
        if min(master.size) < 1200:
            raise ValueError('Master grid is too small for downsample-only exports')
        bounds = [grid_bounds(master.size, index) for index in range(16)]
        if sum((right - left) * (bottom - top)
               for left, top, right, bottom in bounds) != master.width * master.height:
            raise ValueError('Proportional source grid did not cover the master exactly')
        for row in range(4):
            boxes = bounds[row * 4:(row + 1) * 4]
            assert boxes[0][0] == 0 and boxes[-1][2] == master.width
            assert all(boxes[i][2] == boxes[i + 1][0] for i in range(3))
        crops = [symbol_crop(master, index) for index in range(16)]
        prepared[style] = (filename, data, master.size, crops)
    output.mkdir(parents=True)
    manifest = {'schema': 1, 'status': 'SOURCE_PACK_STATIC_VALIDATION_ONLY',
                'client_installable': False, 'graphical_client_validation': False,
                'published': False, 'native_silver_sha256': SILVER_SHA,
                'densities_percent': list(DENSITIES), 'symbols_row_major': list(SYMBOLS),
                'native_resource_contracts': originals,
                'not_generated_native_symbols': ['ratings', 'wrench-options', 'mail', 'filter-flag', 'zoom-plus', 'zoom-minus'],
                'unmapped_concepts': ['crates', 'skills'],
                'adapter_requirements': [
                    'Retain existing controls, callbacks, logical bounds and native state indices.',
                    'Separate source texel dimensions from destination logical dimensions; never multiply GUI scale twice.',
                    'Use actual D3D texture dimensions for normalized UV when the device pads NPOT images.',
                    'Do not copy density atlases over original resources without a guarded source/destination adapter.',
                    'Wide native toolbar buttons remain 88x31; square source glyphs must fit inside their existing plate.',
                    'Crates cannot replace the ratings button; generic search is shared with chat and other dialogs.',
                ],
                'native_states': {
                    'indices': dict(enumerate(STATE_NAMES)),
                    'artwork': 'identical generated palette in all four candidate frames; no state repaint',
                    'stock_draw_evidence': 'Silver a45400/a45294: normal0, disabled1, pressed2, hover3 overlay',
                    'disabled_image_only_argb': '0x90ffffff when control+0x4a is zero',
                    'stock_common_tint': 'control+0x2dc; sidebar constructors use 0xffdbefb1',
                    'pressed_offset': 'native +1,+1 unless control+0x2f4 suppresses it',
                    'hover_overlay_alpha': 'native control+0x290 fade, preserve existing behavior',
                    'palette_adapter': 'use neutral RGB tint for colored artwork, retain native disabled alpha/state behavior',
                }, 'styles': {}, 'checks': {}}
    checks = 0
    for style, (filename, data, master_size, crops) in prepared.items():
        source_record = exclusive_write(output / 'source' / filename, data)
        source_record['dimensions'] = list(master_size)
        exports = []
        for density in DENSITIES:
            strip = Image.new('RGBA', (16 * (40 * density // 100), 40 * density // 100))
            for index, (crop, crop_record) in enumerate(crops):
                name = SYMBOLS[index]
                icon, geometry = fit_symbol(crop, density)
                proof = alpha_proof(icon)
                record = exclusive_write(output / style / str(density) / 'symbols' / (name + '.png'), png_bytes(icon))
                record.update(symbol=name, density_percent=density, crop=crop_record,
                              geometry=geometry, proof=proof)
                exports.append(record)
                strip.alpha_composite(icon, (index * icon.width, 0))
                if name in ('map', 'soldier', 'money'):
                    sheet, frames = atlas(icon, density)
                    pack = exclusive_write(output / style / str(density) / 'sidebar-atlases' / (name + '-states.png'), png_bytes(sheet))
                    pack.update(symbol=name, density_percent=density, frames=frames,
                                source_tile_px=list(icon.size), logical_tile=[40, 40],
                                source_dimensions=list(sheet.size), columns=3,
                                requires_native_adapter=True)
                    exports.append(pack)
                    checks += 4
                checks += 3
            exclusive_write(output / style / str(density) / 'symbols-strip.png', png_bytes(strip))
            for background, color in [('olive', (31, 43, 21, 255)), ('dark', (18, 20, 22, 255))]:
                composed = Image.alpha_composite(Image.new('RGBA', strip.size, color), strip)
                exclusive_write(output / style / str(density) / ('composite-' + background + '.png'), png_bytes(composed))
        manifest['styles'][style] = {'source': source_record, 'exports': exports}
    manifest['checks'] = {'PASS': True, 'assertion_count': checks,
                          'master_hashes_preserved': True, 'proportional_grid_coverage': True,
                          'downsample_only': True, 'four_state_crops_equal_symbol': True,
                          'native_client_unchanged': sha(silver.read_bytes()) == SILVER_SHA}
    exclusive_write(output / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    return {'PASS': True, 'output': str(output.resolve()), 'manifest_sha256': sha((output / 'manifest.json').read_bytes()),
            'styles': 3, 'symbol_pngs': 192, 'sidebar_atlases': 36, 'densities': list(DENSITIES),
            'client_installable': False, 'graphical_client_validation': False, 'published': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=ROOT / 'reports/ui-hd-assets/icons/source')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/ui-hd-assets/icons/candidate-packs')
    parser.add_argument('--native-pda', type=Path, default=Path(r'C:\Program Files (x86)\TIOnline\base\pda'))
    parser.add_argument('--silver', type=Path, default=ROOT / 'reports/ui-modernization/client/silver.dll')
    parser.add_argument('--tactical-filename', default=STYLES['b-tactical-clean'],
                        help='Use a reviewed grid-clean variant without replacing the original B master')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT.resolve()) or output == ROOT.resolve():
        raise ValueError('Generated output must stay inside this workspace')
    protected = [args.source_dir.resolve(), args.native_pda.resolve(), args.silver.resolve().parent]
    if any(output == folder or output.is_relative_to(folder) for folder in protected):
        raise ValueError('Output must not overlap source, native client, or frozen binary directories')
    print(json.dumps(build(args.source_dir, output, args.native_pda, args.silver,
                           args.tactical_filename), ensure_ascii=False))


if __name__ == '__main__':
    main()
