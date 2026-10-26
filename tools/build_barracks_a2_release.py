"""Build an offline client release from pinned published presentation inputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.client_barracks_a2 import patch
from deploy.client_item_icons_hd import copy_stack_flags, replace_item_images

OUT = ROOT / 'reports/barracks-a2-20261025'
ASSETS = ROOT / 'assets/item-icons-hd-v1'
XML = 'base/shared config/items.xml'


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build() -> None:
    before = json.loads((OUT / 'manifest-before.json').read_bytes())
    assert before['version'] == '2026.10.24.2'
    manifest = json.loads(json.dumps(before))
    manifest['version'] = '2026.10.25.2'
    manifest.pop('archive', None)
    manifest['news'] = 'Новая раскладка казармы и склада: крупный боец, экипировка слева, вкладки справа и HD-иконки предметов. Закройте игру и обновите её через лаунчер.'
    manifest['newsEn'] = 'New barracks and warehouse layout with a larger soldier, equipment on the left, tabs on the right and HD item artwork. Close the game and update through the launcher.'
    rows = {row['path']: row for row in manifest['files']}
    items = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))['items']
    ids = tuple(sorted(item['item_id'] for item in items))
    changed_ids = sorted(item['item_id'] for item in items if item['pipeline'] != 'existing')
    assert len(ids) == len(set(ids)) == 146 and len(changed_ids) == 101
    mapping = {identity: f'tio_ii_{identity}.png' for identity in changed_ids}
    server_before = (OUT / 'published-20261025.1/server-items.xml').read_bytes()
    client: dict[str, bytes] = {}
    for name in ('silver.dll', XML):
        raw = (OUT / 'source' / name).read_bytes()
        assert digest(raw) == rows[name]['sha256'] and len(raw) == rows[name]['size']
        client[name] = patch(raw, item_ids=ids) if name == 'silver.dll' else replace_item_images(raw, mapping)
        if name == XML:
            client[name] = copy_stack_flags(client[name], server_before, (17, 18, 19, 30))
    for identity in ids:
        name = f'base/items/hd/tio_ih_{identity}_512.png'
        raw = (ASSETS / f'exports/512x512/tio_ii_{identity}.png').read_bytes()
        assert raw[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('!II', raw[16:24]) == (512, 512)
        client[name] = raw
    for identity in changed_ids:
        name = f'base/items/tio_ii_{identity}.png'
        raw = (ASSETS / f'exports/64x32/tio_ii_{identity}.png').read_bytes()
        assert raw[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('!II', raw[16:24]) == (64, 32)
        client[name] = raw
    additions = []
    for name, raw in client.items():
        target = OUT / 'client' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if name in rows:
            assert name in ('silver.dll', XML)
            row = rows[name]
            row.update(sha256=digest(raw), size=len(raw))
        else:
            row = dict(path=name, size=len(raw), sha256=digest(raw), seed=False)
            additions.append(row)
    manifest['files'].extend(sorted(additions, key=lambda row: row['path']))
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    server_after = replace_item_images(server_before, mapping)
    (OUT / 'server-items.xml').write_bytes(server_after)
    report = dict(passed=True, version=manifest['version'], changed_item_ids=changed_ids,
                  hd_item_ids=ids, additions=len(additions), files=len(manifest['files']),
                  server_before_sha256=digest(server_before), server_sha256=digest(server_after),
                  silver_sha256=rows['silver.dll']['sha256'],
                  resources={name: dict(sha256=digest(raw), size=len(raw)) for name, raw in client.items()})
    (OUT / 'build.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('resources', 'changed_item_ids', 'hd_item_ids')}))


if __name__ == '__main__':
    build()
