"""Build the client release that lets the launcher choose the interface.

Inputs are the pinned artefacts of the published 2026.10.25.2 release.
Only silver.dll changes and one catalogue variant is added; every other
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
from deploy.client_barracks_a2 import patch
from deploy.client_item_icons_hd import restore_item_images

PUBLISHED_MANIFEST = 'ae4af3465d765c5dc7fbc2f6836ffb048f74ab99a9cb6e5bf38657a0c4b3629f'
XML = 'base/shared config/items.xml'
ORIGINAL_XML = 'base/interfaces/original/items.xml'
VERSION = '2026.10.26.1'
NEWS = ('В лаунчере появились «Настройки»: выберите новый или оригинальный интерфейс казармы '
        'и склада. Закройте игру и обновите её через лаунчер.')
NEWS_EN = ('The launcher now has Settings: choose the new or the original barracks and warehouse '
           'interface. Close the game and update it through the launcher.')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(workspace: Path) -> dict:
    a2 = workspace / 'reports/barracks-a2-20261025'
    out = workspace / 'reports/interface-mode-20261026'
    raw_manifest = (a2 / 'manifest.json').read_bytes()
    assert digest(raw_manifest) == PUBLISHED_MANIFEST, 'Published manifest changed'
    before = json.loads(raw_manifest)
    assert before['version'] == '2026.10.25.2'
    rows = {row['path']: row for row in before['files']}
    assert ORIGINAL_XML not in rows
    items = json.loads((workspace / 'assets/item-icons-hd-v1/manifest.json').read_text(encoding='utf-8'))['items']
    ids = tuple(sorted(item['item_id'] for item in items))
    changed_ids = tuple(sorted(item['item_id'] for item in items if item['pipeline'] != 'existing'))
    assert len(ids) == 146 and len(changed_ids) == 101

    published = {name: (a2 / 'client' / name).read_bytes() for name in ('silver.dll', XML)}
    for name, raw in published.items():
        assert digest(raw) == rows[name]['sha256'] and len(raw) == rows[name]['size'], name
    source = {name: (a2 / 'source' / name).read_bytes() for name in ('silver.dll', XML)}
    silver = patch(source['silver.dll'], item_ids=ids)
    assert silver != published['silver.dll'] and len(silver) == len(published['silver.dll'])
    original = restore_item_images(published[XML], source[XML], changed_ids)
    assert original != published[XML]

    manifest = json.loads(raw_manifest)
    manifest.pop('archive', None)
    manifest.update(version=VERSION, news=NEWS, newsEn=NEWS_EN)
    for row in manifest['files']:
        if row['path'] == 'silver.dll':
            row.update(sha256=digest(silver), size=len(silver))
    manifest['files'].append(dict(path=ORIGINAL_XML, size=len(original), sha256=digest(original), seed=False))
    resources = {'silver.dll': silver, ORIGINAL_XML: original}
    for name, raw in resources.items():
        target = out / 'client' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    report = dict(passed=True, version=VERSION, before_manifest_sha256=PUBLISHED_MANIFEST,
                  files=len(manifest['files']), silver_before_sha256=rows['silver.dll']['sha256'],
                  silver_sha256=digest(silver), published_catalogue_sha256=rows[XML]['sha256'],
                  original_catalogue_sha256=digest(original), restored_item_ids=list(changed_ids),
                  resources={name: dict(sha256=digest(raw), size=len(raw)) for name, raw in resources.items()})
    (out / 'build.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT,
                        help='folder holding reports/ and assets/ release inputs')
    result = build(parser.parse_args().workspace)
    print(json.dumps({key: value for key, value in result.items() if key not in ('restored_item_ids', 'resources')}))
