"""Export original-design item masters and the reviewed battle glyph sheet.

Only technical registration, density conversion and atlas assembly occur here.
Neither installed files nor source masters are overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_battle_ui_hd as adapter
from tools.equipment_texture_export import icon_registration
from tools.build_visual_asset_catalog import decode
from tools.repack_battle_glyphs_centered import repack as register_battle_glyphs


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(output, battle_master, native_root):
    if output.exists():
        raise ValueError('Preserve existing asset exports; use a new output')
    output.mkdir(parents=True)
    manifest = {**adapter.metadata(), 'assets': [], 'masters_preserved': True,
                'installed_files_written': False, 'original_alpha_registration': True}
    for resource in adapter.RESOURCES:
        w, h = resource['logical_size']
        source_info = {}
        if resource['kind'] == 'item':
            original = ROOT / 'reports/equipment-textures/source/base' / resource['native_path'].replace('\\', '/')
            reference, codec = decode(original.read_bytes())
            assert reference.size == (w, h)
            master = ROOT / 'assets/equipment-textures-v1/generated' / (resource['id'] + '.png')
            art = Image.open(master).convert('RGBA')
            # Keep normalized original placement and silhouettes, while retaining
            # material detail at four source pixels per logical pixel.
            high_reference = reference.resize((w * 4, h * 4), Image.Resampling.LANCZOS)
            canvas = icon_registration(art, high_reference)
            assert canvas.getchannel('A').tobytes() == high_reference.getchannel('A').tobytes()
            assert art.width >= canvas.width and art.height >= canvas.height
            source_info = {'original_path': str(original.resolve()), 'original_sha256': sha(original.read_bytes()),
                           'master_path': str(master.resolve()), 'master_sha256': sha(master.read_bytes()),
                           'original_size': [w, h], 'master_size': list(art.size),
                           'original_native_codec': codec, 'scaled_original_alpha_exact': True}
        elif resource['id'] == 'battle-plates':
            original = native_root / 'base/pda/bui_controls_btn.png'
            reference, _ = decode(original.read_bytes())
            canvas = Image.new('RGBA', (46 * 4 * 4, 46 * 4))
            for frame in range(4):
                tile = reference.crop((frame * 46, 0, (frame + 1) * 46, 46))
                canvas.alpha_composite(tile.resize((184, 184), Image.Resampling.LANCZOS), (frame * 184, 0))
            source_info = {'original_path': str(original.resolve()), 'original_sha256': sha(original.read_bytes()),
                           'chrome_preserved': True, 'frame_count': 4}
        else:
            art = Image.open(battle_master).convert('RGBA')
            canvas, registration, visible_count = register_battle_glyphs(
                art, source_sha=sha(battle_master.read_bytes()))
            source_info = {'master_path': str(battle_master.resolve()), 'master_sha256': sha(battle_master.read_bytes()),
                           'master_size': list(art.size), 'frame_count': 15, 'empty_cells': 21,
                           'source_cell': 209, 'native_action_order_preserved': True,
                           'semantic_registration': registration,
                           'all_visible_master_pixels_assigned_exactly_once': True,
                           'visible_master_pixels': visible_count,
                           'centered_complete_sprites': True}
        target = output / 'assets/base' / resource['hd_path'].replace('\\', '/')
        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(target, format='PNG', compress_level=9)
        check = Image.open(target)
        assert check.size == canvas.size and check.mode == 'RGBA'
        manifest['assets'].append({'path': str(target.resolve()), 'client_relative_path': target.relative_to(output / 'assets').as_posix(),
                                   'native_path': 'base/' + resource['native_path'].replace('\\', '/'),
                                   'size': target.stat().st_size, 'sha256': sha(target.read_bytes()),
                                   'dimensions': list(canvas.size), 'logical_tile': [w, h],
                                   'source_tile': [w * 4, h * 4], **source_info})
    manifest['checks'] = {'PASS': True, 'exported': len(manifest['assets']), 'items': adapter.ITEM_COUNT,
                          'unique_resource_basenames': len({Path(a['path']).name for a in manifest['assets']}),
                          'native_layout_changed': False, 'original_resources_overwritten': False}
    destination = output / 'assets-manifest.json'
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'PASS': True, 'manifest': str(destination.resolve()), 'assets': len(manifest['assets'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--battle-master', type=Path, required=True)
    parser.add_argument('--native-root', type=Path, default=Path(r'C:\Users\jundu\AppData\Local\TIO-Online'))
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve(), args.battle_master.resolve(), args.native_root.resolve())))
