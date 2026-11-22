"""Publish the HD atlases restored to their UV layout (2026.11.17.1 -> 2026.11.17.2).

Replaces exactly seven existing plain-JPEG records under base/models with
assets/registered-atlases-v1 (tools/build_registered_atlases.py):
armor_battlese, armor_combat, armor_combatse, armor_tankse, armor_suicidjack,
armor_fease, armor_santahat. Each built file must derive from the hosted HD
atlas it replaces (combatse: from the restored combat). Every other record,
the news and all other manifest fields stay byte-identical; no code,
configuration, catalog, database or player data is uploaded, and
silver.dll/ti.exe are untouched.

Uses the guarded remote path of tools/publish_combat_se_atlas_20261116.py
(lock, exact manifest, SQLite backup, atomic writes, old blobs kept).

Usage: python tools/publish_registered_atlases_20261117.py {inspect|apply|verify}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_combat_se_atlas_20261116 as guarded  # noqa: E402
from tools.build_registered_atlases import DRIFTED  # noqa: E402
from tools.publish_hd_map_textures_20261114 import package, sha, verify  # noqa: E402

OUT = ROOT/'reports/registered-atlases-20261117'
BUILD = ROOT/'assets/registered-atlases-v1'
PREVIOUS_VERSION, VERSION = '2026.11.17.1', '2026.11.17.2'
MANIFEST_SHA = 'b921a4826bb266c85247a17a36e095bd6c27f7d6c1d10219f772edcc1fe3e7d1'
REMOTE_PACKAGE = '/root/tio-registered-atlases-20261117.zip'


def candidate() -> tuple[bytes, bytes, list[dict], dict[str, bytes]]:
    old = (OUT/'manifest-before.json').read_bytes()
    if sha(old) != MANIFEST_SHA:
        raise ValueError('Inspected hosted manifest changed')
    manifest = json.loads(old)
    if manifest['version'] != PREVIOUS_VERSION:
        raise ValueError('Unexpected previous client version')
    existing = {r['path']: r for r in manifest['files']}
    built = json.loads((BUILD/'registered-atlases.json').read_text(encoding='utf-8'))
    expected = {name: row['output_sha256'] for name, row in built.items() if name in DRIFTED}
    if set(expected) != set(DRIFTED):
        raise ValueError('Unexpected atlas set')
    for name in DRIFTED:
        if existing[f'base/models/{name}.jpg']['sha256'] != built[name]['hd_sha256']:
            raise ValueError(f'{name} was not restored from the hosted HD atlas')
    se = built['armor_combatse']
    if se['source_atlas_sha256'] != built['armor_combat']['output_sha256']:
        raise ValueError('armor_combatse was not derived from the restored armor_combat')
    if existing['base/models/armor_combatse_mask.png']['sha256'] != se['outputs']['armor_combatse_mask.png']:
        raise ValueError('Hosted SE mask differs from the one the SE atlas was built with')
    expected['armor_combatse'] = se['outputs']['armor_combatse.jpg']
    records, payload = [], {}
    for name, digest in sorted(expected.items()):
        path = f'base/models/{name}.jpg'
        raw = (BUILD/f'{name}.jpg').read_bytes()
        if sha(raw) != digest or raw[:2] != b'\xff\xd8' or existing[path]['sha256'] == digest:
            raise ValueError(f'Built atlas changed, is not JPEG or is already published: {path}')
        records.append(dict(path=path, size=len(raw), sha256=digest, seed=existing[path]['seed']))
        payload[path] = raw
    changed = {r['path']: r for r in records}
    manifest['version'] = VERSION
    manifest['files'] = [changed.get(r['path'], r) for r in manifest['files']]
    new = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return old, new, records, payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'apply', 'verify'))
    args = parser.parse_args()
    old, new, records, payload = candidate()
    guarded.PREVIOUS_VERSION, guarded.VERSION, guarded.REMOTE_PACKAGE = PREVIOUS_VERSION, VERSION, REMOTE_PACKAGE
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == 'verify':
        result = dict(version=VERSION, manifest_sha256=sha(new), https=verify(new, records))
    else:
        archive = package(payload)
        local = OUT/'package.zip'
        local.write_bytes(archive)
        sent = subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', str(local), 'tio:' + REMOTE_PACKAGE],
                              capture_output=True, timeout=900)
        if sent.returncode:
            raise RuntimeError('Package upload failed')
        result = guarded.remote(args.mode, old, new, records, sha(archive))
        local.unlink()
    (OUT/f'publication-{args.mode}.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result)[:2000])


if __name__ == '__main__':
    main()
