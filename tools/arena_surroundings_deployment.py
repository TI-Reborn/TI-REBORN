"""Shared local release constants; importing this module has no side effects."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
from collections import Counter
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/arena-surroundings-implementation/deploy'
OVERLAY = ROOT / 'assets/arena-surroundings-v1/client-overlay'
HOST = '185.184.42.88'
URL = 'https://' + HOST + '/updates/'
OLD_VERSION = '2026.10.06.5'
NEW_VERSION = '2026.10.07.1'
SERVER_FILES = (
    'tio/arena_map.py', 'tio/map_generation.py', 'tio/arena_surroundings.py',
    'config/battle_map_profiles.json', 'config/arena_surroundings.json',
)
BASELINE_FILES = SERVER_FILES + (
    'config/arena_fragments.json', 'config/reservation_visuals.json',
    'tio/protocol/battle_ground.py',
)
TEST_PATTERNS = (
    'test_battle_ground.py', 'test_arena_map.py', 'test_city_ground_brushes.py',
    'test_arena_surroundings.py', 'test_map_generation.py',
    'test_reservation_visuals.py', 'test_forest_encounters.py', 'test_cities.py',
)
ASSET_PROOF_FLAGS = (
    'passed', 'full_set_complete', 'all_gameplay_holes_clear',
    'all_outer_diamonds_clear', 'all_four_sides_covered', 'all_four_corners_covered',
    'all_models_noninteractive', 'all_scenes_1x1_empty_cells',
    'all_patches_1024x1024_full_frame',
    'all_scenes_foreground', 'all_scenes_no_nonlinear_warp',
    'all_native_anchors_inside_game_grid',
)
SSH = ['ssh', '-i', str(Path.home() / '.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=10', 'root@' + HOST]
SCP = ['scp', '-i', str(Path.home() / '.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=10']


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def remote_read(code: str, payload=None):
    response = subprocess.run(SSH + ['python3 -c ' + shlex.quote(code)],
                              input=json.dumps(payload), capture_output=True,
                              text=True, encoding='utf-8', check=False)
    if response.returncode:
        raise RuntimeError('Read-only SSH inspection failed: ' + response.stderr.strip())
    return json.loads(response.stdout)


def allowed_asset(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or '..' in path.parts or '\\' in name or ':' in name:
        return False
    if path.name != path.name.lower() or not path.name.startswith('as_'):
        return False
    if path.parent == PurePosixPath('base/maps'):
        return re.fullmatch(r'as_(rv|de|ny|mz)_[1-3]_(38|57)\.s', path.name) is not None
    return path.parent == PurePosixPath('base/setting/arena_surroundings') and path.suffix in ('.t', '.png')


def validate_asset_proof(summary, detailed, additions, policy, native, native_raw, previous_manifest=None, palette=None, palette_raw=None):
    """Bind recorded native/alpha proofs to every byte in the prepared overlay."""
    def require(condition, message):
        if not condition:
            raise RuntimeError(message)
    require(all(summary.get(key) is True for key in ASSET_PROOF_FLAGS), 'An asset proof flag is incomplete')
    require(summary.get('scene_count') == summary.get('expected_scene_count') == 24, 'Asset proof must contain all 24 scenes')
    actual_files = {name: {key: record[key] for key in ('path', 'size', 'sha256')}
                    for name, record in additions.items()}
    recorded = summary['files']
    require(len(recorded) == len(actual_files) == summary['file_count'] and
            {record['path']: record for record in recorded} == actual_files,
            'Asset summary inventory differs from the current overlay')
    require(native.get('status') == summary['native_proof'].get('status') == 'PASS' and
            sha(native_raw) == summary['native_proof']['sha256'], 'Native proof hash/status differs')
    require(native.get('schema') == 'arena-surroundings-native/v2-foreground' and
            native.get('render_mode') == 'noninteractive_foreground_type1',
            'Cached-ground native proof is superseded; foreground execution proof required')
    foreground = native['foreground']
    require(foreground['model_type'] == 1 and foreground['render_as_tile'] == 0 and
            all(foreground[key] is True for key in ('interactive_fields_zero', 'anchors_inside_game_grid',
                'scene_cells_zero', 'texture_full_uv', 'post_ground_mask')) and
            foreground['scene_footprint'] == [1, 1] and foreground['attachment_limit'] == 255 and
            foreground['map_sizes'] == [38, 57] and '0x6d626c' in foreground['renderer'] and
            foreground.get('visible_from_ground_entry_loader') is True and foreground.get('visible_value') == 1 and
            foreground.get('fog_cell_filter') is False,
            'Native foreground parser/attachment/post-mask proof is incomplete')
    for key in ('foreground_attachment_proof', 'foreground_renderer_proof'):
        reference = native[key]
        require(reference.get('passed') is True and all(re.fullmatch(r'[0-9a-f]{64}', reference[field])
                for field in ('sha256', 'script_sha256')), 'Native foreground evidence reference is incomplete')
    require(detailed.get('schema') == 2 and detailed.get('rendering_pass') == 'foreground' and
            detailed.get('no_nonlinear_warp') is True, 'Old warped/cached-ground asset report is superseded')
    scenes = detailed['scenes']
    town_codes = {'reservation': ('rv', 'R'), 'denver': ('de', 'D'),
                  'new_york': ('ny', 'N'), 'military_zone': ('mz', 'M')}
    expected = {f'base/maps/as_{code}_{variant}_{width}.s': (code, master + str(variant), variant, width)
                for code, master in town_codes.values() for variant in (1, 2, 3) for width in (38, 57)}
    require(len(scenes) == 24 and {scene['scene'] for scene in scenes} == set(expected), 'Detailed scene set is incomplete')
    require(policy.get('version') == 1 and set(policy['profiles']) == set(town_codes), 'Unexpected runtime surroundings profiles')
    policy_scenes = set()
    for town, (code, prefix) in town_codes.items():
        profile = policy['profiles'][town]
        require(profile.get('enabled') is True and len(profile['variants']) == 3, 'Runtime variants are incomplete')
        for index, variant in enumerate(profile['variants'], 1):
            require(variant['id'] == prefix + str(index) and variant['scene_by_size'] ==
                    {str(width): f'as_{code}_{index}_{width}' for width in (38, 57)},
                    'Runtime scene resource code differs from the reviewed asset proof')
            policy_scenes.update('base/maps/' + stem + '.s' for stem in variant['scene_by_size'].values())
    require(policy_scenes == set(expected), 'Runtime scenes and native assets differ')
    files, source_hashes = [], {}
    original_files = {r['path']: r for r in previous_manifest['files']} if previous_manifest else None
    sides = {'x_negative', 'y_negative', 'x_at_or_above_width', 'y_at_or_above_width'}
    for scene in scenes:
        code, master, variant, width = expected[scene['scene']]
        require((scene['town_code'], scene['master_id'], scene['variant'], scene['playable_width']) ==
                (code, master, variant, width), 'Detailed native scene identity differs')
        require(scene['scene_basename'] == PurePosixPath(scene['scene']).name and
                scene['scene_sha256'] == actual_files[scene['scene']]['sha256'] and
                scene['scene_bytes'] == actual_files[scene['scene']]['size'], 'Native scene bytes differ from the proof')
        require(scene.get('passed') is True and scene.get('no_interactions') is True and
                scene.get('native_reconstruction_equals_clipped_master_alpha') is True and
                scene['cell_footprint'] == [1, 1] and scene['cell_payload_hex'] == '0000' and
                scene['scene_origin'] == [0, 0] and scene.get('rendering_pass') == 'foreground' and
                scene.get('no_nonlinear_warp') is True and scene.get('anchors_inside_game_grid') is True and
                scene['native_attachment_limit'] == 255,
                'Detailed native scene safety/placement proof is incomplete')
        depth = {38: 24, 57: 36}[width]
        canvas_width, canvas_height = 64*(width+2*depth), 32*(width+2*depth)
        require(scene['depth'] == depth and scene['canvas_dimensions'] == [canvas_width, canvas_height],
                'Native canvas projection differs from the fixed city/dimension ring')
        require(scene['gameplay_hole_screen_vertices'] == [[0, 0], [-32*width, 16*width],
                [0, 32*width], [32*width, 16*width]], 'Protective hole does not match the playable diamond')
        source_width, source_height = scene['source']['dimensions']
        require(source_width == 2*source_height and scene['uniform_source_scale'] == [1, 1] and
                scene['native_prop_scale'] == [1, 1], 'Original props/canal modules must retain their pixel size')
        require(scene['source'].get('registration', {}).get('nonlinear_transform') is False,
                'Source registration must explicitly reject nonlinear warping')
        underlay = scene['ground_underlay']
        require(underlay['native_world_chunk_cells'] == 8 and
                underlay['pixel_scale'] == [1, 1] and underlay['rescaling'] is False and
                underlay['nonlinear_transform'] is False and underlay['manifest_version'] == OLD_VERSION and
                underlay['placement_stride_world_cells'] == [4, 4] and underlay['original_frame_alpha_unchanged'] is True,
                'Ground underlay must retain original native diamond pixels and scale')
        sprites, sources = underlay['sprites'], underlay['sources']
        require(bool(sprites) and bool(sources) and underlay['native_pixel_dimensions'] ==
                [list(v) for v in sorted({tuple(s['frame_dimensions']) for s in sprites})],
                'Ground sprite dimensions differ from their native source records')
        source_records = {s['published_path']: s for s in sources}
        require(len(source_records) == len(sources), 'Duplicate original ground source')
        for sprite in sprites:
            fw, fh = sprite['frame_dimensions']; left, top, right, bottom = sprite['source_crop']
            require(0 < fw <= 512 and 0 < fh <= 512 and right-left == fw and bottom-top == fh and
                    0 <= left < right <= 512 and 0 <= top < bottom <= 512 and
                    sprite['texture_path'] in source_records and sprite['original_model_version'] in (0, 2),
                    'Original ground frame/crop/model source is invalid')
            if original_files is not None:
                require(original_files[sprite['published_model_path']]['sha256'] == sprite['model_sha256'] and
                        original_files[sprite['texture_path']]['sha256'] == source_records[sprite['texture_path']]['source_sha256'],
                        'Native ground provenance differs from the preserved old client manifest')
        require(underlay['tile_count'] == len(underlay['tiles']) > 0, 'Ground placement inventory is incomplete')
        tile_origins = set()
        for tile in underlay['tiles']:
            x, y = tile['world_origin']; index = tile['frame_index']
            require(type(x) is int and type(y) is int and x % 4 == y % 4 == 0 and
                    (x, y) not in tile_origins and 0 <= index < len(sprites), 'Invalid/duplicate native ground tile origin')
            tile_origins.add((x, y)); sprite = sprites[index]
            wx, wy = x + sprite['native_world_xy'][0], y + sprite['native_world_xy'][1]
            sx, sy = sprite['native_screen_shift']
            require(tile['canvas_origin'] == [32*(wy-wx)+sx+canvas_width//2, 16*(wx+wy)+sy+32*depth],
                    'Native original ground placement changed scale or projection')
        composition = scene['composition']
        require(composition['native_prop_scale'] == [1, 1] and composition['no_nonlinear_warp'] is True and
                composition['rendering_resize'] is False and set(composition['four_sides']) == sides and
                len(composition['instances']) > 0, 'Original prop composition/scale proof is incomplete')
        require(composition['compositor']['path'] == 'tools/arena_surroundings_composition.py' and
                re.fullmatch('[0-9a-f]{64}', composition['compositor']['sha256']) is not None,
                'Composition must record the reviewed native placement implementation SHA')
        require(composition['layout_source']['path'] == 'tools/arena_surroundings_layout.py' and
                re.fullmatch('[0-9a-f]{64}', composition['layout_source']['sha256']) is not None,
                'Composition must pin the current native layout implementation SHA')
        instances = composition['instances']
        building_count = sum(i['role'] == 'building' for i in instances)
        prop_ids = {i.get('palette_record_id') or i['id'] for i in instances}
        layout = composition['layout']
        require(building_count == composition['large_building_count'] <= 6 and
                len(prop_ids) == composition['unique_prop_types'] and layout['layout_version'] == 3 and
                layout['large_building_limit'] == 6 and layout['functional_nodes'] is True and
                layout['regular_building_rows'] is False and
                layout['clusters'] == len({i['group'] for i in instances if i['role'] == 'detail'}),
                'Sparse building/functional detail-group layout proof is inconsistent')
        if master == 'R3':
            require(composition['approved_source'] in ('assets/arena-surroundings-v1/masters/R3.png',
                    'assets/arena-surroundings-v1/masters/R3-detail-bank.png') and
                    re.fullmatch('[0-9a-f]{64}', composition['approved_source_sha256']) is not None and
                    len(composition['canal_modules']) > 0 and
                    all(i['pixel_scale'] == [1, 1] and i['side'] in sides | {'corner'} and
                        len(i['canvas_origin']) == 2 and all(type(v) is int for v in i['canvas_origin'])
                        for i in composition['canal_modules']),
                    'Approved canal modules must only be translated at their source pixel size')
            for module in composition['canal_modules']:
                left, top, right, bottom = module['source_bounds']
                require(all(type(v) is int for v in module['source_bounds']) and
                        0 <= left < right <= source_width and 0 <= top < bottom <= source_height,
                        'Canal module crop is outside the unchanged source bitmap')
        require(re.fullmatch('[0-9a-f]{64}', composition['palette_sha256']) is not None and
                all(i['pixel_scale'] == [1, 1] and i['side'] in sides for i in instances),
                'Native prop palette/translation proof is incomplete')
        if palette is not None:
            require(palette.get('passed') is True and sha(palette_raw) == composition['palette_sha256'],
                    'Original palette bytes differ from composition provenance')
            entries = {r['id']: r for r in palette['models'].values()}
            for instance in instances:
                entry = entries[instance.get('palette_record_id') or instance['id']]
                require(entry.get('usable') is True and instance['raster'] == entry['path_rel_root'] and
                        instance['raster_sha256'] == entry['raster_sha256'] and
                        instance['source_sha256'] == entry['source_sha256'] and
                        instance['original_dimensions'] == entry['dimensions'], 'A placed original sprite differs from its palette')
                path = entry['source_path']
                refs = entry.get('original_scene_references', [])
                city = master[0]
                compatible = ((city == 'M' and '/military/' in path) or
                    (city == 'R' and any('/'+name+'/' in path for name in ('military', 'village'))) or
                    (city == 'D' and ('/forest/' in path or entry['id'] in ('log_single_01','log_single_01b') or
                        any(PurePosixPath(s).stem.startswith('forest_') for s in refs))) or
                    (city == 'N' and ('/ny/' in path or any(PurePosixPath(s).stem.startswith('ny_') for s in refs))))
                require(compatible, 'Placed native prop is from another city family without a known original scene use')
                x, y = instance['world_origin']; bx, by = entry['screen_bbox'][:2]
                require(instance['canvas_origin'] == [canvas_width//2+32*(y-x)+bx, 32*depth+16*(x+y)+by],
                        'Original prop placement contains pixel scaling or a nonnative projection')
                if original_files is not None:
                    require(original_files[entry['source_path']]['sha256'] == entry['source_sha256'],
                            'Original prop model differs from the preserved client manifest')
        alpha = scene['alpha_proof']
        require(alpha.get('passed') is True and alpha['hole_nonzero_pixels'] == alpha['outside_nonzero_pixels'] == 0 and
                alpha['minimum_opaque_fraction'] >= .95 and set(alpha['four_sides']) == sides and all(side['pixels'] > 0 and
                side['opaque_fraction'] >= alpha['minimum_opaque_fraction'] for side in alpha['four_sides'].values()),
                'Detailed alpha coverage proof is incomplete')
        require(set(alpha['four_corners']) == {'corner_origin','corner_x','corner_y','corner_opposite'} and
                all(corner['pixels'] > 0 and corner['opaque_fraction'] >= alpha['minimum_opaque_fraction']
                    for corner in alpha['four_corners'].values()), 'Detailed four-corner coverage proof is incomplete')
        models = scene['models']
        require(scene['patch_count'] == len(models) and len(models) > 0, 'Native model proof is incomplete')
        model_files = {scene['scene']}
        anchors, origins = Counter(), set()
        for model in models:
            model_path = 'base/setting/arena_surroundings/' + model['model_basename']
            texture_path = 'base/setting/arena_surroundings/' + model['texture_basename']
            require(model['texture_dimensions'] == [1024, 1024] and model['static_flag'] == 1 and model['render_as_tile'] == 0 and
                    model['interaction_bytes_hex'] == '00' * 16 and
                    model['native_model_sha256'] == actual_files[model_path]['sha256'],
                    'Native model bytes/interaction proof differs')
            x, y = model['world_anchor']
            require(type(x) is int and type(y) is int and 0 <= x < width and 0 <= y < width,
                    'Foreground attachment anchor is outside the existing game grid')
            anchors[x, y] += 1
            require(anchors[x, y] <= 255, 'Native foreground attachment byte counter would overflow')
            sx, sy = model['screen_offset']
            bx, by = 32*(y-x)+sx-32, 16*(x+y)+sy
            require(model['screen_box_before_camera'] == [bx, by, bx+1024, by+1024],
                    'Foreground sprite placement must include the native minus32 pixel shift')
            cx, cy = model['canvas_origin']
            require([cx, cy] == [bx+canvas_width//2, by+32*depth] and cx % 1024 == cy % 1024 == 0 and
                    0 <= cx < canvas_width and 0 <= cy < canvas_height and (cx, cy) not in origins and
                    model['valid_canvas_extent'] == [min(1024, canvas_width-cx), min(1024, canvas_height-cy)],
                    'Native sprite canvas rectangle/transparent padding differs')
            origins.add((cx, cy))
            model_files.update((model_path, texture_path))
        require(scene['max_models_per_anchor'] == max(anchors.values()), 'Recorded attachment bound differs')
        require(model_files == {record['path'] for record in scene['files']}, 'Detailed scene model/texture inventory differs')
        files.extend(scene['files'])
        source_hashes[master] = scene['source']['sha256']
    require(len(files) == len(actual_files) and {record['path']: record for record in files} == actual_files,
            'Detailed asset inventory differs from the current overlay')
    require(source_hashes == summary['source_hashes'] and len(source_hashes) == 12, 'Detailed source hashes differ from the summary')
    require(summary['maximum_models_per_anchor'] == max(s['max_models_per_anchor'] for s in scenes),
            'Summary attachment bound differs')


def validate_native_asset_bytes(detailed, read_asset):
    """Bind safe foreground fields/anchors/PNG headers to exact packaged bytes."""
    def require(condition, message):
        if not condition:
            raise RuntimeError(message)
    def unpack(blob):
        if blob[:4] != b'\x03ZIP':
            return blob
        raw = zlib.decompress(blob[16:])
        require(len(raw) == struct.unpack_from('<I', blob, 8)[0], 'Native envelope length differs')
        return raw
    for scene in detailed['scenes']:
        raw = unpack(read_asset(scene['scene']))
        count = len(scene['models'])
        width = scene['playable_width']
        anchors = Counter()
        require(width in (38, 57), 'Unexpected native playable dimensions')
        require(raw[:8] == b'TI SET\0\2' and len(raw) == 34+72*count and
                struct.unpack_from('<3H', raw, 12) == (1, 1, count) and raw[32:34] == bytes(2) and
                struct.unpack_from('<H', raw, 18)[0] == 2 and raw[20:32] == bytes(12),
                'Actual native scene cell/record bytes are unsafe')
        for index, model in enumerate(scene['models']):
            record = raw[34+72*index:34+72*(index+1)]; length = record[0]
            require(0 < length <= 63 and record[1:1+length].decode('ascii') == model['model_basename'] and
                    list(struct.unpack_from('<ii', record, 64)) == model['world_anchor'],
                    'Actual native model name/anchor differs from proof')
            x, y = struct.unpack_from('<ii', record, 64)
            anchors[x, y] += 1
            require(0 <= x < width and 0 <= y < width and anchors[x, y] <= 255,
                    'Actual native foreground attachment is outside the grid or overflows its byte counter')
            tile = unpack(read_asset('base/setting/arena_surroundings/' + model['model_basename']))
            require(len(tile) == 544 and tile[:8] == b'TI TILE\0' and struct.unpack_from('<HH', tile, 8) == (1, 2) and
                    tile[12:24] == bytes(12) and tile[28:36] == bytes(8) and tile[68:70] == b'\1\0' and
                    struct.unpack_from('<II', tile, 52) == (0xffffff, 255) and tile[64:66] == bytes(2) and
                    tile[340:356] == bytes(16) and tile[440:539] == bytes(99) and tile[539:544] == b'\1\0\0\0\0' and
                    struct.unpack_from('<HH', tile, 60) == struct.unpack_from('<HH', tile, 334) == (1024, 1024),
                    'Actual native TILE is interactive or differs from safe foreground/full-frame contract')
            require(list(struct.unpack_from('<hh', tile, 48)) == model['screen_offset'] and
                    0 < tile[203] <= 128 and tile[204:204+tile[203]].decode('ascii') == model['texture_basename'],
                    'Actual native texture/signed offset differs from proof')
            png = read_asset('base/setting/arena_surroundings/' + model['texture_basename'])
            require(png[:8] == b'\x89PNG\r\n\x1a\n' and png[12:16] == b'IHDR' and
                    struct.unpack_from('>II5B', png, 16) == (1024, 1024, 8, 6, 0, 0, 0),
                    'Actual foreground PNG is not a standard1024 RGBA bitmap')
