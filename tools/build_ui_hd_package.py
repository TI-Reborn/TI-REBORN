"""Assemble only the frozen selected HD client files for the update publisher."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_ui_hd_client as client

FONT_MANIFEST = ROOT / 'reports/ui-hd-assets/selected-fonts/manifest.json'
FONT_SHA = '85ed0c1421ed284a77a17e1f9e7f19761955a0cebb44b750827d5fef2d8a2393'
ICON_MANIFEST = ROOT / 'reports/ui-hd-integration/icons-fixed-cache/selected-assets-manifest.json'
ICON_SHA = '753f1ec53ca3568c020d89851c2f193971efc26a07502ee8db4ad66313e15e71'
MANIFEST_SHA = '77c984e9346f1208c84ee739ca18ebebdd45fcdc970cd4de50f618627191738d'


def checked_manifest(path, expected):
    data = path.read_bytes()
    client.require(client.sha(data) == expected, 'Frozen selected asset manifest differs: ' + str(path))
    return json.loads(data)


def build():
    output = client.safe_output(client.OUT)
    candidate = output / 'silver.dll'
    data = candidate.read_bytes()
    rebuilt, _ = client.reconstruct()
    client.require(data == rebuilt, 'Candidate is not the exact composed native build')
    entries = [{'path': 'silver.dll', 'source': 'silver.dll', 'sha256': client.sha(data),
                'size': len(data), 'kind': 'native'}]
    font = checked_manifest(FONT_MANIFEST, FONT_SHA)
    icon = checked_manifest(ICON_MANIFEST, ICON_SHA)
    client.require(len(font['assets']) == 37 and len(icon['assets']) == 60,
                   'Selected native asset count differs')
    seen = {'silver.dll'}
    for manifest, root, icon_mode in ((font, FONT_MANIFEST.parent, False),
                                      (icon, ICON_MANIFEST.parent / 'assets', True)):
        for asset in manifest['assets']:
            relative = asset['client_relative_path'] if icon_mode else asset['path']
            source = root / relative
            client.require(source.resolve().is_relative_to(root.resolve()) and not source.is_symlink(),
                           'Selected asset source escaped its frozen folder')
            client.require(relative.lower() not in seen, 'Duplicate selected asset path')
            seen.add(relative.lower())
            content = source.read_bytes()
            client.require(client.sha(content) == asset['sha256'] and len(content) == asset['bytes'],
                           'Frozen selected asset bytes differ: ' + relative)
            kind = 'icon_image' if icon_mode else ('license' if relative.endswith('.txt') else 'font_atlas')
            target = client.safe_output(output / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            entries.append({'path': relative, 'source': relative, 'sha256': client.sha(content),
                            'size': len(content), 'kind': kind})
    package = {'schema': 1, 'previous_version': '2026.10.09.12', 'version': '2026.10.09.13',
               'baseline_manifest_sha256': MANIFEST_SHA,
               'selection': {'icons': 'a-classic-hd', 'font_family': 'Roboto Condensed'},
               'files': [entries[0]] + sorted(entries[1:], key=lambda a: a['path'].lower())}
    target = client.safe_output(output / 'package.json')
    target.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    from tools import publish_ui_hd_assets_remote as publisher
    validated, payloads = publisher.load_package(target, expected_sha=client.sha(target.read_bytes()))
    client.require(len(payloads) == 98 and validated == package, 'Strict publisher validation differs')
    report = {'result': 'PASS', 'package': str(target), 'package_sha256': client.sha(target.read_bytes()),
              'candidate_sha256': client.sha(data), 'files': len(payloads),
              'total_bytes': sum(len(p) for p in payloads.values()),
              'selected_font_manifest_sha256': FONT_SHA, 'selected_icon_manifest_sha256': ICON_SHA,
              'font_atlases': 36, 'icons': 60, 'licenses': 1,
              'public_version': package['version'], 'published': False, 'graphical_validation': False}
    client.safe_output(output / 'package-proof.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    build()
