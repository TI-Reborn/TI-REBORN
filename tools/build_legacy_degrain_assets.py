"""Export reviewed imagegen cleanups into unchanged native texture layouts.

This only encodes / slices reviewed bitmap masters. It performs no procedural
denoising, sharpening or new image generation and never writes the source client.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
import sys

from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_visual_asset_catalog import decode
from tools.build_menu_interface_assets import frame_atlas, button_atlas, framed_plate
from tools.equipment_texture_export import native_encode
from tools.native_texture_contract import validate_replacement

OUT = ROOT / 'reports/gameplay-completion/legacy-status-20261011/textures'
BASELINE = ROOT / 'reports/new-player/client-a'
UI_WINDOWS = ('c_window.png', 'd_window.png', 'd_window2.png', 'd_window3.png',
              'd_window4.png', 'steel_window.png')
WORLD = ('base/setting/reservation_v2/rvy_ground.png',
         'base/setting/reservation_v2/rv_outdoor_v01.png',
         'base/setting/reservation_v2/rv_bunker.png',
         'base/setting/military/ground_military_base_a.tga',
         'base/setting/military/ground_military_base_b.tga')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def codec(raw: bytes) -> str:
    if raw.startswith(bytes.fromhex('07e181')): return 'AJPG_EX'
    if raw.startswith(b'BM'): return 'BMP'
    if raw.startswith(b'\x89PNG'): return 'PNG'
    if raw.startswith(b'\xff\xd8'): return 'JPEG'
    if len(raw) >= 18 and raw[2] in (2, 10): return 'TGA'
    raise ValueError('Unsupported native codec')


def records() -> dict:
    manifest = json.loads((OUT / 'baseline-manifest.json').read_bytes())
    assert manifest['version'] == '2026.10.11.1'
    return {r['path']: r for r in manifest['files']}


def original(relative: str, manifest: dict) -> tuple[bytes, Image.Image]:
    record = manifest[relative]
    assert not record.get('seed'), relative
    raw = (BASELINE / relative).read_bytes()
    assert len(raw) == record['size'] and sha(raw) == record['sha256'], relative
    image, _ = decode(raw)
    return raw, image


def audit() -> None:
    manifest = records()
    inventory = []
    for relative in [*['base/pda/' + n for n in UI_WINDOWS],
                     'base/pda/menuframe.png', 'base/pda/charbevel.png',
                     'base/pda/gui_button.png', 'base/pda/menubutton.png', *WORLD]:
        raw, image = original(relative, manifest)
        target = OUT / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        decoded = OUT / 'decoded' / (Path(relative).name + '.png')
        decoded.parent.mkdir(parents=True, exist_ok=True)
        image.save(decoded)
        if relative in WORLD:
            image.convert('RGB').save(decoded.with_name(Path(relative).name + '.opaque.png'))
        inventory.append(dict(path=relative, sha256=sha(raw), size=len(raw),
                              dimensions=list(image.size), codec=codec(raw),
                              alpha_extrema=list(image.getchannel('A').getextrema()),
                              decoded=str(decoded.relative_to(ROOT))))
    (OUT / 'asset-audit.json').write_text(json.dumps(inventory, indent=2) + '\n')
    print(json.dumps(inventory))


def build() -> None:
    manifest = records()
    masters = OUT / 'masters'
    frame = Image.open(masters / 'frame-clean.png')
    button = Image.open(masters / 'button-clean.png')
    window = frame_atlas(frame)
    planned = {**{'base/pda/' + n: (window, 'frame-clean.png', 'native frame_atlas 4x4, cell32, edge8')
                  for n in UI_WINDOWS},
               'base/pda/menuframe.png': (frame_atlas(frame, edge_width=24), 'frame-clean.png',
                                        'native frame_atlas 4x4, cell32, edge24'),
               'base/pda/gui_button.png': (button_atlas(button, 25), 'button-clean.png',
                                         'native left/middle/right, four state rows, cell25'),
               'base/pda/menubutton.png': (button_atlas(button, 50), 'button-clean.png',
                                         'native left/middle/right, four state rows, cell50')}
    bevel = Image.new('RGBA', (256, 128))
    plate = framed_plate(window, (216, 60))
    bevel.alpha_composite(plate, (0, 0))
    bright = ImageEnhance.Brightness(plate.convert('RGB')).enhance(1.3).convert('RGBA')
    bright.putalpha(plate.getchannel('A'))
    bevel.alpha_composite(bright, (0, 64))
    planned['base/pda/charbevel.png'] = (bevel, 'frame-clean.png',
                                      'native two64px state rows, plate216x60 at0,0 and0,64')
    world_plan = masters / 'world-clean-index.json'
    if world_plan.exists():
        for item in json.loads(world_plan.read_text(encoding='utf-8')):
            assert item['path'] in WORLD, item['path']
            art = Image.open(masters / item['master']).convert('RGBA')
            # Resolution adaptation is codec export, never noise reduction.
            _, reference = original(item['path'], manifest)
            if art.size != reference.size:
                art = art.resize(reference.size, Image.Resampling.LANCZOS)
            planned[item['path']] = (art, item['master'], 'original full canvas and exact original alpha')
    proofs, paths, paired_paths = [], [], []
    for relative, (art, master, layout) in planned.items():
        raw, reference = original(relative, manifest)
        assert art.size == reference.size, relative
        if codec(raw) == 'TGA':
            # Original native TGA header, origin, alpha bytes and trailer remain
            # byte-identical. Only RGB channels are rewritten with reviewed art.
            assert raw[1] == 0 and raw[2] == 2 and raw[16] == 32
            offset = 18 + raw[0]
            pixels = art.convert('RGB').tobytes()
            payload = bytearray(raw)
            width, height = reference.size
            for y in range(height):
                row = y if raw[17] & 32 else height - 1 - y
                for x in range(width):
                    col = width - 1 - x if raw[17] & 16 else x
                    source = (y * width + x) * 3
                    target = offset + (row * width + col) * 4
                    red, green, blue = pixels[source:source + 3]
                    payload[target:target + 3] = bytes((blue, green, red))
            data = bytes(payload)
        else:
            data = native_encode(raw, art.copy(), reference)
        contract = validate_replacement(raw, data)
        check, _ = decode(data)
        assert check.size == reference.size, relative
        assert check.getchannel('A').tobytes() == reference.getchannel('A').tobytes(), relative
        assert codec(data) == codec(raw), relative
        assert data != raw, relative
        destination = OUT / 'candidate' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        preview = OUT / 'review-decoded' / (Path(relative).name + '.png')
        preview.parent.mkdir(parents=True, exist_ok=True)
        check.save(preview)
        paths.append(str(destination.resolve()))
        paired_paths.extend((str((OUT / 'source' / relative).resolve()), str(destination.resolve())))
        proofs.append(dict(path=relative, original_sha256=sha(raw), original_size=len(raw),
                           sha256=sha(data), size=len(data), dimensions=list(check.size),
                           original_alpha_exact=True, native_codec=codec(data), layout=layout,
                           master='masters/' + master, master_sha256=sha((masters / master).read_bytes()),
                           seed=False, **{k: v for k, v in contract.items() if k not in ('codec',)}))
    report = dict(baseline_version='2026.10.11.1',
                  baseline_manifest_sha256=sha((OUT / 'baseline-manifest.json').read_bytes()),
                  operation='imagegen reference edits; original native atlas/compiler/codec export',
                  files=proofs, changed_count=len(proofs),
                  executables_modified=False, model_uv_or_xml_modified=False)
    (OUT / 'changed-files.json').write_text(json.dumps(report, indent=2) + '\n')
    (OUT / 'native-decoder-list.txt').write_text('\n'.join(paths) + '\n', encoding='utf-8')
    (OUT / 'native-decoder-pairs.txt').write_text('\n'.join(paired_paths) + '\n', encoding='utf-8')
    print(json.dumps(dict(changed=len(proofs), total_size=sum(p['size'] for p in proofs))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    audit() if args.audit else build()
