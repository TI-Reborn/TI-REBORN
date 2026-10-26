"""Build the client release with the full-height A2 warehouse column.

Inputs: the published 2026.10.26.1 manifest (pinned by SHA-256), the pinned
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

PUBLISHED_MANIFEST = '83a292fd4850784a78080499c06c896e830024ed718849672571323fe24c7445'
PUBLISHED_SILVER = '8ec07dd8c2bdc80e05cb883f83dc1a1b01735dbc5d121ce9c144b962101aa7f2'
VERSION = '2026.10.26.2'
NEWS = ('Склад в казарме стал больше: сетка на всю колонку, фильтры открываются кнопкой «ФИЛЬТР», '
        'вкладки — под бойцом, на карточках — суммарная броня. Закройте игру и обновите её через лаунчер.')
NEWS_EN = ('A larger barracks warehouse: a full-height grid, filters under the FILTER button, tabs '
           'under the soldier and total armour on the cards. Close the game and update it through the launcher.')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(workspace: Path) -> dict:
    out = workspace / 'reports/warehouse-v2-20261026'
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
