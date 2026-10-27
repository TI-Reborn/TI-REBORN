"""Build the client release that fits item overlays into the A2 cells.

Inputs: the published 2026.10.26.2 manifest (pinned by SHA-256), the pinned
pre-A2 Silver it was built from and the HD item list. Only silver.dll
changes; every other manifest row stays byte-identical. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.client_barracks_a2 import BASE_SHA, patch

PUBLISHED_MANIFEST = 'e2a85aee3d0790dda56ea5721742c934126dd7ec5d4f5e1b3c4c37c9ae6d6562'
PUBLISHED_SILVER = '5c87d334ad3e7e8018339243132b65525030487188bd1c9d8535a4638d11b408'
VERSION = '2026.10.27.1'
NEWS = ('Ячейки предметов в казарме: заточка, патроны, броня и прочность теперь внутри ячейки, '
        'премиум-предметы обведены жёлтой рамкой по краю ячейки. Закройте игру и обновите её через лаунчер.')
NEWS_EN = ('Barracks item cells: upgrade, ammo, armour and durability now stay inside the cell and '
           'premium items get a yellow frame around the whole cell. Close the game and update it through the launcher.')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(workspace: Path) -> dict:
    out = workspace / 'reports/item-cells-20261027'
    raw_manifest = (out / 'manifest-before.json').read_bytes()
    assert digest(raw_manifest) == PUBLISHED_MANIFEST, 'Published manifest changed'
    before = json.loads(raw_manifest)
    rows = {row['path']: row for row in before['files']}
    assert rows['silver.dll']['sha256'] == PUBLISHED_SILVER
    source = (workspace / 'reports/barracks-a2-20261025/source/silver.dll').read_bytes()
    assert digest(source) == BASE_SHA
    items = json.loads((workspace / 'assets/item-icons-hd-v1/manifest.json').read_text(encoding='utf-8'))['items']
    ids = tuple(sorted(item['item_id'] for item in items))
    silver = patch(source, item_ids=ids)
    assert digest(silver) != PUBLISHED_SILVER and len(silver) == rows['silver.dll']['size']

    manifest = json.loads(raw_manifest)
    manifest.pop('archive', None)
    manifest.update(version=VERSION, news=NEWS, newsEn=NEWS_EN)
    for row in manifest['files']:
        if row['path'] == 'silver.dll':
            row.update(sha256=digest(silver), size=len(silver))
    target = out / 'client/silver.dll'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(silver)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    report = dict(passed=True, version=VERSION, before_manifest_sha256=PUBLISHED_MANIFEST,
                  files=len(manifest['files']), silver_before_sha256=PUBLISHED_SILVER,
                  silver_sha256=digest(silver),
                  resources={'silver.dll': dict(sha256=digest(silver), size=len(silver))})
    (out / 'build.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT,
                        help='folder holding reports/ and assets/ release inputs')
    result = build(parser.parse_args().workspace)
    print(json.dumps({key: value for key, value in result.items() if key != 'resources'}))
