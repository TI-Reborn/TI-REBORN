"""Extract original low boundary materials at 1:1; no runtime or server edits.

NY sidewalk patterns use complete native TILE v2 numeric reads and native UVs.
Legacy stone v0 geometry uses the same registered native reader, stopped after
all sprite geometry fields. Late legacy fields are deliberately not decoded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from tools.inspect_original_arena_decor import BASE, NativeReader
from tools.extract_original_arena_prop_palette import NativeUV
from tools.build_visual_asset_catalog import decode
from tools.verify_auth_native import UC_HOOK_CODE
from PIL import Image, ImageDraw

DEFAULT_MANIFEST = ROOT / 'reports/arena-surroundings-fog/client-release/manifest.json'
DEFAULT_OUT = ROOT / 'assets/arena-boundaries-v1/native-palette'
AUDIT = ROOT / 'reports/arena-boundaries-implementation/new-york-denver-native-palette.json'
OLD_PALETTE = ROOT / 'reports/arena-surroundings-implementation/native-prop-palette/palette.json'
NY_NAMES = [
    'ny_sidewalk_UL', 'ny_sidewalk_UR', 'ny_sidewalk_DL', 'ny_sidewalk_DR',
    'ny_sidewalk_corner_up', 'ny_sidewalk_corner_down',
    'ny_sidewalk_corner_left', 'ny_sidewalk_corner_right',
    'ny_sidewalk_sewers_UL', 'ny_sidewalk_sewers_UR',
    'ny_sidewalk_sewers_DL', 'ny_sidewalk_sewers_DR',
    'ny_sidewalk_depart_UL', 'ny_sidewalk_depart_UR',
    'ny_sidewalk_depart_DL', 'ny_sidewalk_depart_DR',
]
BUSH_NAMES = ['forest_bush_v1', 'forest_bush_v2', 'forest_bush_v3', 'foliage_bush_01']
GROUND_NAMES = [f'ground_forest_32x_detail_{i}' for i in range(1, 17)]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class LegacyStoneGeometry:
    """Execute the registered reader through fields needed for an atlas crop.

    Native registration at 0x758f10..0x758f3b maps versions 0,1,2,3 to
    0x74a4b4. This avoids rewriting a version byte or fabricating late bytes.
    The v0 files are shorter than later records; they are not cloned at runtime.
    """
    def __init__(self):
        self.reader = NativeReader()
        u = self.reader.u
        expected = bytes.fromhex('bab4a4740033c0e85400f6ff')
        assert bytes(u.mem_read(0x758f10, len(expected))) == expected
        self.registry = {
            'address': '0x758f10', 'bytes': expected.hex(),
            'version_0_native_reader': '0x74a4b4',
            'registered_versions': [0, 1, 2, 3],
        }
        u.hook_add(UC_HOOK_CODE, self.stop_after_geometry)

    @staticmethod
    def stop_after_geometry(u, address, size, data):
        if address == 0x74a6ef:
            u.emu_stop()

    def model(self, raw):
        assert raw[:8] == b'TI TILE\0' and raw[10] == 0
        assert struct.unpack_from('<H', raw, 8)[0] == 1
        n = self.reader
        n.raw, n.position, n.reads = raw, 24, []
        n.put32(n.u, n.stack, n.stop)
        n.u.reg_write(n.esp, n.stack)
        n.u.reg_write(n.eax, n.stream)
        n.u.reg_write(n.edx, 0)
        n.u.emu_start(0x74a4b4, n.stop, count=30000)
        assert n.u.reg_read(n.eip) == 0x74a6ef and n.position == 338
        obj = bytes(n.u.mem_read(n.obj, 0x720))
        x, y = struct.unpack_from('<ii', obj, 4)
        sx, sy = struct.unpack_from('<hh', obj, 0x18)
        fw, fh = struct.unpack_from('<HH', obj, 0x24)
        cw, ch = struct.unpack_from('<HH', obj, 0x334)
        record = dict(
            index=0, world_xy=[x, y], screen_shift_xy=[sx, sy],
            rgb_hex=f'{struct.unpack_from("<I", obj, 0x1c)[0]:08x}',
            transparency=struct.unpack_from('<I', obj, 0x20)[0],
            frame_width=fw, frame_height=fh, cached_width=cw, cached_height=ch,
            pattern_index=obj[0x28], static_flag=obj[0x2c], render_as_tile=obj[0x2d],
            native_texture_filename=obj[0x233:0x233 + obj[0x232]].decode('ascii'),
            original_file_span=[24, 338], native_read_trace=n.reads,
        )
        return dict(
            version=0, records_count=1, records=[record],
            native_reader='0x74a4b4', native_geometry_fields_executed=True,
            native_parsed=False, complete_native_reader_executed=False,
            geometry_stream_stop='0x74a6ef', native_consumed_prefix_bytes=338,
            original_bytes=len(raw), remaining_legacy_bytes=len(raw) - 338,
            registry=self.registry,
            limitation='Only native sprite geometry prefix is decoded; late legacy interaction fields are not inferred or exported.',
        )


def alpha_bounds(image, bbox):
    alpha = image.getchannel('A')
    visible = alpha.point(lambda a: 255 if a >= 16 else 0)
    local = visible.getbbox()
    if local is None:
        raise ValueError('Empty source pattern')
    lo_x, lo_y = bbox[:2]
    # Extrema are measured over actual visible pixels; bounding-box corners
    # can lie far outside a thin diagonal sidewalk's real visual footprint.
    world = []
    for index, value in enumerate(visible.tobytes()):
        if value:
            x, y = lo_x + index % image.width, lo_y + index//image.width
            world.append(((2*y - x)/64, (2*y + x)/64))
    return dict(
        alpha_threshold=16, local_pixel_bbox=list(local),
        world_x_range=[min(w[0] for w in world), max(w[0] for w in world)],
        world_y_range=[min(w[1] for w in world), max(w[1] for w in world)],
        scope='Actual alpha>=16 native-pixel world extrema at original anchor; not collision cells or narrow curb footprint.',
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    cli.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = cli.parse_args()
    manifest_raw = args.manifest.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest['version'] != '2026.10.07.2':
        raise ValueError('Boundary reference baseline must be published client .2')
    published = {e['path']: e for e in manifest['files']}
    baseline_path = ROOT / 'reports/arena-boundaries-implementation/remote-before.json'
    baseline_raw = baseline_path.read_bytes()
    baseline = json.loads(baseline_raw)
    assert baseline['client_version'] == manifest['version']
    assert baseline['manifest_sha256'] == sha(manifest_raw)
    assert baseline['passed'] and baseline['read_only']
    hosted_baseline = dict(path=baseline_path.relative_to(ROOT).as_posix(),
        sha256=sha(baseline_raw), client_version=baseline['client_version'],
        manifest_sha256=baseline['manifest_sha256'], inspected_at_utc=baseline['inspected_at_utc'],
        actual_hosted_manifest_match=True, scope='Reuses independent fresh read-only hosted baseline; extractor makes no network or server changes.')
    sources = {}

    def provenance(name):
        path = BASE / Path(name).relative_to('base')
        raw = path.read_bytes()
        reference = published[name]
        if sha(raw) != reference['sha256'] or len(raw) != reference['size']:
            raise ValueError('Source differs from current .2 manifest: ' + name)
        sources[name] = dict(path=name, sha256=sha(raw), bytes=len(raw), published_match=True)
        return raw, sources[name]

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    png_dir = out / 'png'
    png_dir.mkdir(exist_ok=True)
    native, legacy, uv = NativeReader(), LegacyStoneGeometry(), NativeUV()
    texture_names = {
        'ny': 'base/setting/ny/NY_Road/NY_sidewalk.png',
        'stones': 'base/setting/military/stones.tga',
        'forest_ground': 'base/setting/forest/forest_32X32GroundDetails.png',
    }
    textures = {}
    for kind, name in texture_names.items():
        raw, proof = provenance(name)
        image, codec = decode(raw)
        textures[kind] = image
        proof.update(dimensions=list(image.size), rgba_pixels_sha256=sha(image.tobytes()), decode_format=codec)
    assert textures['ny'].size == (1024, 1024)
    assert textures['stones'].size == (128, 128)
    assert textures['forest_ground'].size == (128, 128)
    models, all_images = {}, {}
    selections = [('ny', stem, f'base/setting/ny/NY_Road/ny_sidewalk/{stem}.t') for stem in NY_NAMES]
    selections += [('stones', f'stone{i}', f'base/setting/military/stone{i}.t') for i in range(1, 17)]
    selections += [('forest_ground', stem, f'base/setting/forest/{stem}.t') for stem in GROUND_NAMES]
    for family, stem, path in selections:
        raw, source = provenance(path)
        parsed = legacy.model(raw) if family == 'stones' else native.model(raw)
        assert parsed['records_count'] == 1
        record = parsed['records'][0]
        assert record['render_as_tile'] == 0 and record['static_flag'] == 0
        assert record['rgb_hex'] == '00ffffff' and record['transparency'] == 255
        image = textures[family]
        assert record['native_texture_filename'].lower() == Path(texture_names[family]).name.lower()
        frame = (record['frame_width'], record['frame_height'])
        assert min(frame) > 0
        uv_proof = uv.crop(image.size, frame, record['pattern_index'])
        crop = uv_proof['crop']
        assert 0 <= crop[0] < crop[2] <= image.width and 0 <= crop[1] < crop[3] <= image.height
        part = image.crop(crop)
        assert part.size == frame
        x, y = record['world_xy']; sx, sy = record['screen_shift_xy']
        px, py = 32*(y - x) + sx, 16*(x + y) + sy
        bbox = [px, py, px + frame[0], py + frame[1]]
        target = png_dir / (stem + '.png')
        part.save(target)
        all_images[stem] = part
        orientation = stem.rsplit('_', 1)[-1] if family == 'ny' else 'individual stone; no directional flip needed'
        models[stem + '.t'] = dict(
            id=stem, category='sidewalk' if family == 'ny' else ('stone_detail' if family == 'stones' else 'forest_ground_detail'),
            candidate_city='new_york' if family == 'ny' else 'denver',
            source_path=path, source_sha256=source['sha256'],
            texture_path=texture_names[family], texture_source_sha256=sources[texture_names[family]]['sha256'],
            native_model=parsed, native_uv=uv_proof, records=[dict(record, native_uv=uv_proof,
                screen_box=bbox, pixel_dimensions=list(frame), native_geometry_matches_1to1=True,
                texture_path=texture_names[family], texture_source_sha256=sources[texture_names[family]]['sha256'])],
            raster=target.relative_to(ROOT).as_posix(), path_rel_root=target.relative_to(ROOT).as_posix(),
            raster_sha256=sha(target.read_bytes()), rgba_pixels_sha256=sha(part.tobytes()),
            dimensions=list(part.size), screen_bbox=bbox, native_offset_xy=[sx, sy],
            source_pattern=record['pattern_index'], pixel_scale=[1, 1], rescaling=False, reflection=False,
            source_pixels_identical=True, alpha_extents=alpha_bounds(part, bbox),
            orientation=orientation, exported=True, usable=True,
            ground_to_foreground_x_compensation=32,
            lighting='Original atlas light and shadow retained; no new light or reflected raster.',
            scope='Whole native pattern, including ground/pavement and alpha fringe; crop is not a newly designed curb.',
        )

    old_raw = OLD_PALETTE.read_bytes()
    old = json.loads(old_raw)
    by_id = {entry['id']: entry for entry in old['models'].values()}
    for stem in BUSH_NAMES:
        entry = by_id[stem]
        provenance(entry['source_path'])
        for rec in entry['records']:
            _, texture_source = provenance(rec['texture_path'])
            assert texture_source['sha256'] == rec['texture_source_sha256']
        original = ROOT / entry['raster']
        raw = original.read_bytes()
        assert sha(raw) == entry['raster_sha256']
        part = Image.open(original).convert('RGBA')
        assert sha(part.tobytes()) == entry['rgba_pixels_sha256']
        target = png_dir / (stem + '.png')
        target.write_bytes(raw)
        all_images[stem] = part
        copied = dict(entry)
        copied.update(
            raster=target.relative_to(ROOT).as_posix(), path_rel_root=target.relative_to(ROOT).as_posix(),
            candidate_city='denver', category='foliage_detail',
            copied_original_palette_raster=True, prior_palette_sha256=sha(old_raw),
            pixel_scale=[1, 1], rescaling=False, reflection=False,
            alpha_extents=alpha_bounds(part, entry['screen_bbox']),
            lighting='Original source atlas light retained; no new light or reflected raster.',
        )
        models[stem + '.t'] = copied

    # Material references for the other two cities are documented, rather
    # than squeezing a pre-existing raised wall into the selected low curb.
    material_candidates = {}
    for path in (
        'base/setting/assault/Assault_v1.png',
        'base/setting/assault/Assault_v2.png',
        'base/setting/military/fence/concrete_wall_01.png',
        'base/setting/military/fence/concrete_wall_01b.png',
    ):
        raw, source = provenance(path)
        image, codec = decode(raw)
        material_candidates[path] = dict(source, dimensions=list(image.size), decode_format=codec,
            pixel_scale=[1, 1], lighting='Original material light retained; new low silhouette requires separate native projection proof.')
    rejected_tall_models = {}
    for path in (
        'base/setting/assault/assault_wall_low_v1.t',
        'base/setting/assault/assault_wall_low_v1b.t',
        'base/setting/military/fence/concrete_wall_01.t',
        'base/setting/military/fence/concrete_wall_01b.t',
    ):
        raw, source = provenance(path)
        info = native.model(raw)
        assert info['native_parsed']
        rejected_tall_models[path] = dict(source, native_model=info,
            approved_low_silhouette_unchanged=False,
            reason='Existing raised wall height does not match the selected low edge; no squash or reflected sprite proposed.')

    # Review artifacts are alpha-composited over a neutral surface at actual
    # native pixel size; extracted transparent sprites remain untouched.
    previews = {}
    for label, names, cell in (
        ('ny', NY_NAMES, (280, 286)),
        ('stones', [f'stone{i}' for i in range(1, 17)], (64, 64)),
        ('forest-ground', GROUND_NAMES, (64, 64)),
        ('foliage', BUSH_NAMES, (220, 220)),
    ):
        columns = 4
        rows = (len(names) + columns - 1)//columns
        board = Image.new('RGBA', (columns*cell[0], rows*cell[1]), (55, 53, 45, 255))
        draw = ImageDraw.Draw(board)
        for index, stem in enumerate(names):
            image = all_images[stem]
            ox = (index % columns)*cell[0] + 8
            oy = (index//columns)*cell[1] + 22
            board.alpha_composite(image, (ox, oy))
            caption = stem.replace('ground_forest_32x_detail_', 'detail')
            draw.text((ox, oy-18), caption, fill=(240, 237, 225, 255))
        target = out / (label + '-review.png')
        board.convert('RGB').save(target)
        previews[label] = dict(path=target.relative_to(ROOT).as_posix(), sha256=sha(target.read_bytes()), pixel_scale=[1, 1])

    result = dict(
        schema='arena-boundary-native-palette/v1', passed=True,
        manifest=dict(path=args.manifest.resolve().relative_to(ROOT).as_posix(), version=manifest['version'], sha256=sha(manifest_raw)),
        hosted_baseline=hosted_baseline,
        extractor=dict(path=Path(__file__).relative_to(ROOT).as_posix(), sha256=sha(Path(__file__).read_bytes())),
        native_exe_sha256=native.exe_sha, models=models, sources=sources,
        model_count=len(models), family_counts=dict(ny=16, stones=16, forest_ground=16, foliage=4),
        previews=previews,
        projection='X=32*(worldY-worldX)+nativeShiftX;Y=16*(worldX+worldY)+nativeShiftY (original type0)',
        foreground_wrapper=dict(type=1, render_as_tile=0, whole_image_uv=True, compensation_x_pixels=32,
            note='Builder owns placement. Original ground pattern must shift wrapperX by+32 to preserve original screen coordinates.'),
        limitations=[
            'No server, runtime assets, gameplay, or production binary changes.',
            'Original numeric reader and UV function execute with file/graphics endpoints stubbed; no new native GPU render.',
            'Legacy v0 stones decode original geometry prefix only; late fields are not guessed or cloned.',
            'Full NY sidewalk patterns include broad pavement alpha; a narrow curb contour and seamless stride need registration proof.',
            'Stones are original ground details, not new raised mossy boulders.',
            'Raw palette pixels keep original light/color. Runtime foreground tint B1 and alpha255 belong to the perimeter builder.',
        ],
    )
    palette_path = out / 'palette.json'
    palette_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    audit = dict(
        schema='arena-boundary-native-audit/v1', passed=True,
        palette_path=palette_path.relative_to(ROOT).as_posix(), palette_sha256=sha(palette_path.read_bytes()),
        manifest=result['manifest'], hosted_baseline=hosted_baseline, native_exe_sha256=native.exe_sha,
        models=models, source_count=len(sources), sources=sources,
        material_candidates=material_candidates, rejected_tall_models=rejected_tall_models,
        city_candidates=dict(
            new_york=dict(original_native_sections=NY_NAMES[:4], original_native_corners=NY_NAMES[4:8],
                sewers=NY_NAMES[8:12], departures=NY_NAMES[12:], scale=[1, 1],
                note='Both native diagonals and four corners exist; retain whole native frame/projection. Width/stride is a separate contour registration check.'),
            denver=dict(stones=[f'stone{i}' for i in range(1, 17)], forest_ground_details=GROUND_NAMES, foliage=BUSH_NAMES, scale=[1, 1],
                note='Small32px stones use stones.tga, not military_decal_stones_01.png. Palette foliage source pixels are copied unchanged.'),
            reservation=dict(material_candidates=['base/setting/assault/Assault_v1.png', 'base/setting/assault/Assault_v2.png'],
                note='assault_wall_low native strips are32×112/128px: existing raised wall exceeds approved low-curb silhouette. Use original materials for a newly bounded low sprite, without squashing the wall.'),
            military_zone=dict(material_candidates=['base/setting/military/fence/concrete_wall_01.png', 'base/setting/military/fence/concrete_wall_01b.png'],
                note='Existing concrete wall is tall; unchanged original wall is not the approved ankle-height concrete edge. A new low shape needs its own projection proof.'),
        ),
        limitations=result['limitations'],
    )
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, count=len(models), palette=str(palette_path), palette_sha256=sha(palette_path.read_bytes()), audit=str(AUDIT))))


if __name__ == '__main__':
    main()
