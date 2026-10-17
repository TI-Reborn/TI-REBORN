"""Verify review-only icon exports without changing native or source assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SILVER_SHA = '87645b946317a645552c3c2a5fcf586784d3920548288e2312dfb9ace065df4d'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
SYMBOLS = ['map', 'soldier', 'crates', 'money', 'info', 'rifle', 'skills', 'squad',
           'handshake', 'search', 'refresh', 'settings', 'check', 'left', 'right', 'close']
DENSITIES = (100, 125, 150, 200)
STYLES = ('a-classic-hd', 'b-tactical-clean', 'c-enamel')
BACKGROUNDS = {'olive': (31, 43, 21, 255), 'dark': (18, 20, 22, 255)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        assert image.format == 'PNG' and image.mode == 'RGBA', str(path)
        return image.copy()


def check_record(record: dict) -> Path:
    path = Path(record['file']).resolve()
    assert path.is_relative_to(ROOT.resolve())
    assert path.stat().st_size == record['bytes']
    assert digest(path) == record['sha256']
    return path


def verify(pack: Path, baseline: Path, vector: Path, proof_path: Path) -> dict:
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    assert not manifest['client_installable']
    assert not manifest['graphical_client_validation'] and not manifest['published']
    assert manifest['symbols_row_major'] == SYMBOLS
    assert manifest['densities_percent'] == list(DENSITIES)
    assert manifest['native_silver_sha256'] == SILVER_SHA
    assert digest(ROOT / 'reports/ui-modernization/client/silver.dll') == SILVER_SHA
    assert digest(ROOT / 'reports/ui-modernization/baseline/ti.exe') == TI_SHA

    native = Path(r'C:\Program Files (x86)\TIOnline\base\pda')
    frozen = ROOT / 'reports/arena-surroundings-implementation/client-qa/game-a/base/pda'
    assert len(manifest['native_resource_contracts']) == 16
    for record in manifest['native_resource_contracts']:
        filename = Path(record['resource']).name
        assert digest(native / filename) == record['original_sha256']
        assert digest(frozen / filename) == record['original_sha256']

    counts = {'symbol_pngs': 0, 'sidebar_atlases': 0, 'composites': 0,
              'hashed_manifest_exports': 0, 'unchanged_a_c_files': 0,
              'vector_sources': 0, 'direct_vector_density_renders': 0}
    source_records = {}
    for style in STYLES:
        style_manifest = manifest['styles'][style]
        source_path = check_record(style_manifest['source'])
        source = load_rgba(source_path)
        assert list(source.size) == style_manifest['source']['dimensions']
        assert min(source.size) >= 1200
        original = ROOT / 'reports/ui-hd-assets/icons/source' / source_path.name
        assert digest(original) == digest(source_path)
        source_records[style] = {'file': str(original), 'sha256': digest(original),
                                 'dimensions': list(source.size)}
        edges_x = [i * source.width // 4 for i in range(5)]
        edges_y = [i * source.height // 4 for i in range(5)]
        assert edges_x[0] == edges_y[0] == 0
        assert edges_x[-1] == source.width and edges_y[-1] == source.height
        assert sum((edges_x[col + 1] - edges_x[col]) * (edges_y[row + 1] - edges_y[row])
                   for row in range(4) for col in range(4)) == source.width * source.height
        exports = style_manifest['exports']
        assert len(exports) == 76
        for record in exports:
            check_record(record)
            counts['hashed_manifest_exports'] += 1
        for density in DENSITIES:
            tile = 40 * density // 100
            strip = Image.new('RGBA', (tile * 16, tile))
            for index, name in enumerate(SYMBOLS):
                path = pack / style / str(density) / 'symbols' / (name + '.png')
                icon = load_rgba(path)
                assert icon.size == (tile, tile)
                alpha = icon.getchannel('A')
                assert alpha.getextrema()[0] == 0 and alpha.getextrema()[1] > 0
                assert all(alpha.getpixel(point) == 0 for point in
                           [(0, 0), (tile - 1, 0), (0, tile - 1), (tile - 1, tile - 1)])
                assert not any(a > 8 and r > 160 and g < 70 and b < 70
                               for r, g, b, a in icon.getdata())
                record = next(row for row in exports if row.get('symbol') == name
                              and row['density_percent'] == density and 'geometry' in row)
                assert record['geometry']['logical_rect'] == [0, 0, 40, 40]
                assert record['geometry']['normalized_uv'] == [0, 0, 1, 1]
                assert 0 < record['geometry']['source_downsample_factor'] <= 1
                expected_bounds = [edges_x[index % 4], edges_y[index // 4],
                                   edges_x[index % 4 + 1], edges_y[index // 4 + 1]]
                assert record['crop']['grid_crop'] == expected_bounds
                strip.alpha_composite(icon, (index * tile, 0))
                counts['symbol_pngs'] += 1
                if name in ('map', 'soldier', 'money'):
                    atlas_record = next(row for row in exports if row.get('symbol') == name
                                        and row['density_percent'] == density and 'frames' in row)
                    sheet = load_rgba(Path(atlas_record['file']))
                    side = 128 * density // 100
                    assert sheet.size == (side, side)
                    blank = Image.new('RGBA', sheet.size)
                    assert atlas_record['logical_tile'] == [40, 40]
                    for frame_index, frame in enumerate(atlas_record['frames']):
                        assert frame['native_frame'] == frame_index
                        assert frame['state'] == ['normal', 'disabled', 'pressed', 'hover'][frame_index]
                        x, y = frame_index % 3 * tile, frame_index // 3 * tile
                        box = [x, y, x + tile, y + tile]
                        assert frame['source_rect_px'] == box
                        assert frame['normalized_image_uv'] == [v / side for v in box]
                        assert frame['destination_logical_rect'] == [0, 0, 40, 40]
                        assert sheet.crop(box).tobytes() == icon.tobytes()
                        blank.alpha_composite(icon, (x, y))
                    assert blank.tobytes() == sheet.tobytes()
                    counts['sidebar_atlases'] += 1
            assert load_rgba(pack / style / str(density) / 'symbols-strip.png').tobytes() == strip.tobytes()
            for background, color in BACKGROUNDS.items():
                composite = load_rgba(pack / style / str(density) / ('composite-' + background + '.png'))
                expected = Image.alpha_composite(Image.new('RGBA', strip.size, color), strip)
                assert composite.size == expected.size and composite.tobytes() == expected.tobytes()
                assert composite.getchannel('A').getextrema() == (255, 255)
                counts['composites'] += 1
        if style != 'b-tactical-clean':
            for path in (pack / style).rglob('*.png'):
                relative = path.relative_to(pack)
                assert digest(path) == digest(baseline / relative)
                counts['unchanged_a_c_files'] += 1

    vector_manifest = json.loads((vector / 'manifest.json').read_text(encoding='utf-8'))
    assert vector_manifest['generated_from_geometry']
    assert not vector_manifest['traced_from_raster'] and not vector_manifest['raster_retouched']
    assert not vector_manifest['client_installable'] and not vector_manifest['published']
    assert vector_manifest['viewBox'] == [0, 0, 64, 64]
    assert len(vector_manifest['symbols']) == 16
    check_record(vector_manifest['masterRecord'])
    assert vector_manifest['masterRecord']['sha256'] == source_records['b-tactical-clean']['sha256']
    unique_svg_hashes = set()
    for index, row in enumerate(vector_manifest['symbols']):
        assert row['index'] == index and row['name'] == SYMBOLS[index]
        path = check_record(row['source'])
        tree = ET.fromstring(path.read_text(encoding='utf-8'))
        assert tree.attrib['viewBox'] == '0 0 64 64'
        assert tree.attrib['width'] == tree.attrib['height'] == '64'
        assert not any(node.tag.split('}')[-1] in ('image', 'text', 'script', 'foreignObject')
                       for node in tree.iter())
        assert not any('href' in attribute for node in tree.iter() for attribute in node.attrib)
        unique_svg_hashes.add(digest(path))
        counts['vector_sources'] += 1
        assert len(row['exports']) == 4
        for rec in row['exports']:
            image = load_rgba(check_record(rec))
            tile = 40 * rec['density'] // 100
            assert image.size == (tile, tile)
            assert image.getchannel('A').getextrema()[0] == 0
            assert image.getchannel('A').getextrema()[1] > 0
            counts['direct_vector_density_renders'] += 1
    assert len(unique_svg_hashes) == 16
    assert counts['symbol_pngs'] == 192 and counts['sidebar_atlases'] == 36
    assert counts['composites'] == 24 and counts['direct_vector_density_renders'] == 64
    result = {
        'status': 'SOURCE_PACK_STATIC_PASS_VISUAL_REVIEW_PASS',
        'client_installable': False, 'graphical_client_validation': False, 'published': False,
        'candidate_manifest': str(pack / 'manifest.json'),
        'candidate_manifest_sha256': digest(pack / 'manifest.json'),
        'native_silver_sha256': SILVER_SHA, 'native_ti_sha256': TI_SHA,
        'counts': counts, 'sources': source_records,
        'assertions': {
            'native_16_hashes_equal_installed_and_frozen_owned_copy': True,
            'source_copies_byte_identical': True, 'proportional_odd_grid_coverage': True,
            'all_192_glyphs_genuine_alpha_and_transparent_corners': True,
            'all_24_composites_exact_source_over_and_opaque': True,
            'all_36_atlases_exact_native_four_state_order_and_40_logical_destination': True,
            'normalized_uv_preserved_at_all_four_densities': True,
            'all_192_glyphs_strong_red_pixel_count_zero': True,
            'classic_and_enamel_exports_byte_identical_to_v1': True,
            'tactical_16_distinct_original_svg_no_embedded_raster_or_external_resources': True,
            'frozen_native_binary_hashes_unchanged': True,
        },
        'visual_review': {
            'method': 'Agent visual review of exported real-density olive/dark composites; not native game validation.',
            'a-classic-hd': 'Clean silhouettes and edges at 40/50/60/80 px; retained previously reviewed A exports.',
            'b-tactical-clean': 'New original SVG companion. Clean 40/50/60/80 px composites; neighboring-cell fragments removed by choosing independent vector geometry, without retouching historical generated masters.',
            'c-enamel': 'Clean silhouettes and edges at 40/50/60/80 px; retained previously reviewed C exports.',
        },
        'limits': ['Prototype source packs require a selected art style and guarded native source/destination adapter.',
                   'Ratings, wrench, mail, filter flag and zoom plus/minus retain unmatched native semantics.',
                   'Crates and skills are concepts without a confirmed replacement control.',
                   'No client installation, native graphical validation, or hosted publication performed.'],
        'historical_proofs_preserved': ['reports/ui-hd-assets/icons/export-static-proof.json'],
    }
    proof_path = proof_path.resolve()
    assert proof_path.is_relative_to(ROOT.resolve()) and not proof_path.exists()
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with proof_path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return {'PASS': True, 'report': str(proof_path), 'manifest_sha256': result['candidate_manifest_sha256'],
            'counts': counts, 'client_installable': False, 'graphical_client_validation': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=ROOT / 'reports/ui-hd-assets/icons/candidate-packs-v3')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'reports/ui-hd-assets/icons/candidate-packs')
    parser.add_argument('--vector', type=Path, default=ROOT / 'reports/ui-hd-assets/icons/vector-b')
    parser.add_argument('--proof', type=Path, default=ROOT / 'reports/ui-hd-assets/icons/export-static-proof-v3.json')
    args = parser.parse_args()
    print(json.dumps(verify(args.pack, args.baseline, args.vector, args.proof), ensure_ascii=False))
