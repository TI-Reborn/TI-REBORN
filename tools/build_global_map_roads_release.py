"""Build client release 2026.10.29.1: the road-layout global map (v3).

Inputs: the published 2026.10.28.2 manifest and Silver (both pinned by
SHA-256) and the v3 PNGs built by tools/build_global_map_v3.py, which must
match assets/global-map-v3/manifest.json byte for byte. silver.dll changes
and 75 PNGs are added; every other manifest row stays identical (the unused
v2 map PNGs are kept so updated installs need no deletions). Nothing is
uploaded.

    python tools/build_global_map_v3.py --client <installed client> --out <workspace>/assets/global-map-v3
    python tools/build_global_map_roads_release.py --workspace <workspace> --silver <published silver.dll>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.client_global_map_roads import BASE_SHA, patch

PUBLISHED_MANIFEST = 'b06e9ff53f9ee38b67180de39d7508b719fac5d5530a532d77d5d64d625326df'
PUBLISHED_VERSION = '2026.10.28.2'
VERSION = '2026.10.29.1'
OUT = 'reports/global-map-roads-20261029'
NEWS = ('Новая глобальная карта: города и базы нарисованы прямо на ней, отряд едет по дорогам, '
        'маршрут показан пунктиром, а локация под курсором подсвечивается. '
        'Закройте игру и обновите её через лаунчер.')
NEWS_EN = ('New global map: towns and bases are part of the map, the squad drives along the roads, '
           'the route is shown as a dashed line and the location under the cursor is highlighted. '
           'Close the game and update it through the launcher.')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def assets(folder: Path, manifest: dict) -> dict[str, bytes]:
    """Client path -> PNG bytes, checked against the committed v3 manifest."""
    entries = [manifest['map'], *manifest['marker']['frames']]
    for location in manifest['locations']:
        entries += [location['hover'], location['selected']]
    out = {}
    for entry in entries:
        relative = 'base/' + entry['path'].replace('\\', '/')
        raw = (folder / relative).read_bytes()
        if digest(raw) != entry['sha256'] or len(raw) != entry['size']:
            raise ValueError(f'{relative} differs from assets/global-map-v3/manifest.json; rebuild with its built_with versions')
        out[relative] = raw
    return out


def build(workspace: Path, silver_path: Path) -> dict:
    out = workspace / OUT
    raw_manifest = (out / 'manifest-before.json').read_bytes()
    if digest(raw_manifest) != PUBLISHED_MANIFEST:
        raise ValueError('Published manifest changed')
    release = json.loads(raw_manifest)
    rows = {row['path']: row for row in release['files']}
    if release['version'] != PUBLISHED_VERSION or rows['silver.dll']['sha256'] != BASE_SHA:
        raise ValueError('Unexpected published release')
    source = silver_path.read_bytes()
    if digest(source) != BASE_SHA:
        raise ValueError('The Silver source is not the published 2026.10.28.2 Silver')
    v3 = json.loads((ROOT / 'assets/global-map-v3/manifest.json').read_text(encoding='utf-8'))
    pngs = assets(workspace / 'assets/global-map-v3', v3)
    if set(pngs) & set(rows):
        raise ValueError('v3 map files already published')
    silver = patch(source, v3)

    release.pop('archive', None)
    release.update(version=VERSION, news=NEWS, newsEn=NEWS_EN)
    rows['silver.dll'].update(sha256=digest(silver), size=len(silver))
    release['files'].extend({'path': path, 'size': len(raw), 'sha256': digest(raw), 'seed': False}
                            for path, raw in sorted(pngs.items()))
    client = out / 'client'
    (client / 'silver.dll').parent.mkdir(parents=True, exist_ok=True)
    (client / 'silver.dll').write_bytes(silver)
    for path, raw in pngs.items():
        target = client / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (out / 'manifest.json').write_text(json.dumps(release, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = dict(passed=True, version=VERSION, before_manifest_sha256=PUBLISHED_MANIFEST,
                  files=len(release['files']), added=sorted(pngs), silver_before_sha256=BASE_SHA,
                  silver_sha256=digest(silver), silver_size=len(silver))
    (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', type=Path, default=ROOT,
                        help=f'folder holding {OUT}/manifest-before.json and assets/global-map-v3')
    parser.add_argument('--silver', type=Path, required=True, help='the published 2026.10.28.2 silver.dll')
    result = build(parser.parse_args().workspace, parser.parse_args().silver)
    print(json.dumps({key: value for key, value in result.items() if key != 'added'}))
