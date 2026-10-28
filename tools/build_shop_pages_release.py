"""Build the client release with steady full-page shops, SC goods and rental.

Inputs: the published 2026.10.28.1 manifest (pinned by SHA-256), the pinned
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

PUBLISHED_MANIFEST = '76a2b4aa8c2107752449c0eab2e2105e5c3d5f02c38fed4d99ebe834ebe51855'
PUBLISHED_SILVER = 'f4071937a7000bba1f7f760f41d3c6feb7f93eac9fb71a2bb08577a7bd18794e'
VERSION = '2026.10.28.2'
NEWS = ('Магазины в интерфейсе «Новый»: окно больше не моргает при покупке и выборе категории, '
        'его нельзя случайно сдвинуть. «Товары SC» и «Аренда вещей» тоже открываются на всю страницу. '
        'Закройте игру и обновите её через лаунчер.')
NEWS_EN = ('Shops in the New interface no longer flicker on purchases and category changes and can no '
           'longer be dragged by accident. SC goods and item rental now fill the whole page too. '
           'Close the game and update it through the launcher.')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(workspace: Path) -> dict:
    out = workspace / 'reports/shop-a2-20261027/polish'
    raw_manifest = (workspace / 'reports/shop-a2-20261027/manifest-before-polish.json').read_bytes()
    assert digest(raw_manifest) == PUBLISHED_MANIFEST, 'Published manifest changed'
    rows = {row['path']: row for row in json.loads(raw_manifest)['files']}
    assert rows['silver.dll']['sha256'] == PUBLISHED_SILVER
    source = (workspace / 'reports/barracks-a2-20261025/source/silver.dll').read_bytes()
    assert digest(source) == BASE_SHA
    items = json.loads((workspace / 'assets/item-icons-hd-v1/manifest.json').read_text(encoding='utf-8'))['items']
    silver = patch(source, item_ids=tuple(sorted(item['item_id'] for item in items)))
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
                  silver_sha256=digest(silver), silver_size=len(silver),
                  resources={'silver.dll': dict(sha256=digest(silver), size=len(silver))})
    (out / 'build.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT,
                        help='folder holding reports/ and assets/ release inputs')
    result = build(parser.parse_args().workspace)
    print(json.dumps({key: value for key, value in result.items() if key != 'resources'}))
