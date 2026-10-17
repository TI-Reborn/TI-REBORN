"""Compose the exact hosted client fixes and register reviewed publication ranges.

Only owned incident staging is written. The hosted/installed client is untouched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_battle_tooltip_scale as tooltip
from deploy import client_battle_ui_hd as icons
from tools import publish_battle_ui_hd_remote as publisher


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build():
    incident = publisher.REPORT_ROOT
    destination = incident / 'client'
    if destination.exists():
        raise ValueError('Preserve prior composition; inspect before rebuilding')
    source = (incident / 'baseline/silver.dll').read_bytes()
    if (sha(source), len(source)) != (publisher.SILVER_SHA, publisher.SILVER_BYTES):
        raise ValueError('Expected exact inspected hosted client')
    assets = json.loads((incident / 'icons/assets-manifest.json').read_bytes())
    requested = {'base/' + r['hd_path'].replace('\\', '/') for r in icons.RESOURCES}
    if len(requested) != 117 or {r['client_relative_path'] for r in assets['assets']} != requested:
        raise ValueError('Asset inventory differs from exact native registration')
    # The two transformers touch disjoint hooks and compose in either order.
    icons_only = icons.patch(source, expected_sha=sha(source))
    candidate = tooltip.patch(icons_only, expected_sha=sha(icons_only))
    tooltip_only = tooltip.patch(source, expected_sha=sha(source))
    if icons.patch(tooltip_only, expected_sha=sha(tooltip_only)) != candidate:
        raise ValueError('Native transformers do not commute')
    old = pefile.PE(data=source)
    spans = []
    for field in ('Misc_VirtualSize', 'SizeOfRawData'):
        spans.append((old.sections[-1].get_field_absolute_offset(field), 4,
                      'Map appended item and combat icon runtime in existing final section'))
    spans.append((old.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4,
                  'Extend mapped image size for reviewed icon runtime'))
    for va, size, purpose in (
        (0x4f27fc, 6, 'Chain known item and combat tile drawing before existing PDA HD adapter'),
        (0x4f2910, 6, 'Draw known inventory icons with independent source and destination sizes'),
        (0x4f2c50, 6, 'Register known native item image loads and eagerly load separate HD icons'),
        (0xa6b834, 5, 'Register four existing combat button plate states'),
        (0xa6b852, 5, 'Register existing combat action glyph atlas'),
        (tooltip.HOOK, 5, 'Render cursor attack balloon in logical UI scope'),
    ):
        spans.append((old.get_offset_from_rva(va - icons.IMAGE_BASE), size, purpose))
    spans.append((old.get_offset_from_rva(tooltip.SLOT_RVA), tooltip.SLOT_SIZE,
                  'Reserved existing zero cave for cursor tooltip UI scope wrapper'))
    review = {'changes': [
        {'offset': at, 'size': size, 'source_sha256': sha(source[at:at + size]),
         'candidate_sha256': sha(candidate[at:at + size]), 'purpose': purpose}
        for at, size, purpose in sorted(spans)
    ], 'appended_size': len(candidate) - len(source),
        'appended_sha256': sha(candidate[len(source):])}
    native_proof = publisher.native_preserved(source, candidate, review)
    if review['appended_size'] != icons.SIZE:
        raise ValueError('Unexpected reviewed appended runtime size')
    destination.mkdir()
    (destination / 'silver.dll').write_bytes(candidate)
    qa = incident / 'composition'
    qa.mkdir()
    (qa / 'icons-only.dll').write_bytes(icons_only)
    files = [{'path': 'silver.dll', 'source': 'silver.dll', 'sha256': sha(candidate),
              'size': len(candidate), 'kind': 'native'}]
    for asset in sorted(assets['assets'], key=lambda a: a['client_relative_path']):
        path = Path(asset['path'])
        if not path.resolve().is_relative_to((incident / 'icons/assets').resolve()):
            raise ValueError('Asset source exceeds owned export staging')
        raw = path.read_bytes()
        if (sha(raw), len(raw)) != (asset['sha256'], asset['size']):
            raise ValueError('Exported asset differs from reviewed identity')
        if 'master_path' in asset and sha(Path(asset['master_path']).read_bytes()) != asset['master_sha256']:
            raise ValueError('Selected master changed after asset export')
        target = destination / asset['client_relative_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files.append({'path': asset['client_relative_path'], 'source': asset['client_relative_path'],
                      'sha256': sha(raw), 'size': len(raw), 'kind': 'icon_image'})
    package = {'schema': 1, 'previous_version': publisher.PREVIOUS_VERSION,
               'version': publisher.VERSION, 'baseline_manifest_sha256': publisher.MANIFEST_SHA,
               'selection': {'fix': 'battle-ui-quality-and-tooltip'},
               'native_review': review, 'files': files}
    package_path = destination / 'package.json'
    package_raw = (json.dumps(package, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    package_path.write_bytes(package_raw)
    publisher.load_package(package_path, sha(package_raw))
    report = {'passed': True, 'package_path': str(package_path), 'package_sha256': sha(package_raw),
              'version': publisher.VERSION, 'files': len(files),
              'item_pngs': icons.ITEM_COUNT, 'control_pngs': 2,
              'silver_sha256': sha(candidate), 'silver_size': len(candidate),
              'icons_only_sha256': sha(icons_only), 'native_scope': native_proof,
              'transformers_commute': True, 'installed_client_written': False,
              'hosting_written': False, 'real_client_rendering_verified': False}
    (qa / 'build-proof.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    old.close()
    return report


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
