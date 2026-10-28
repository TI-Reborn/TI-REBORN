"""Build the client release with the full-page A2 shop and buying to the warehouse.

Inputs: the published 2026.10.27.1 manifest (pinned by SHA-256), the pinned
pre-A2 Silver it was built from and the HD item list. Only silver.dll
changes (its A2 region grows by the 0x8000-byte shop block); every other
manifest row stays byte-identical. Nothing is uploaded.
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

PUBLISHED_MANIFEST = 'cefb4c7838a4600db358107faff101c9a439565539571d473e18f76f5d36e94a'
PUBLISHED_SILVER = '23367d6cb1021aec9de4f2ec8f9b159ea5931dc8fdbb61d265e2176f8fccb207'
VERSION = '2026.10.28.1'
NEWS = ('Магазин в интерфейсе «Новый» открывается на всю страницу. Переключатель «Боец / Склад» '
        'выбирает, куда попадёт покупка: в рюкзак бойца или сразу на склад. '
        'Закройте игру и обновите её через лаунчер.')
NEWS_EN = ('The shop in the New interface now fills the whole page. The Fighter / Warehouse switch '
           'chooses where a purchase goes: to the fighter\'s backpack or straight to the warehouse. '
           'Close the game and update it through the launcher.')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(workspace: Path) -> dict:
    out = workspace / 'reports/shop-a2-20261027'
    raw_manifest = (out / 'manifest-before.json').read_bytes()
    assert digest(raw_manifest) == PUBLISHED_MANIFEST, 'Published manifest changed'
    rows = {row['path']: row for row in json.loads(raw_manifest)['files']}
    assert rows['silver.dll']['sha256'] == PUBLISHED_SILVER
    source = (workspace / 'reports/barracks-a2-20261025/source/silver.dll').read_bytes()
    assert digest(source) == BASE_SHA
    items = json.loads((workspace / 'assets/item-icons-hd-v1/manifest.json').read_text(encoding='utf-8'))['items']
    silver = patch(source, item_ids=tuple(sorted(item['item_id'] for item in items)))
    assert digest(silver) != PUBLISHED_SILVER

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
