"""Publish the men's combat helmets without head poke-through (2026.11.16.1 -> 2026.11.16.2).

Replaces exactly the nine existing man_armor_combat_{light,medium,heavy}_head
(+ _0/_25) mesh records built by tools/helmet_head_clearance.py. Only vertex
positions differ from the hosted files; sizes, topology, UVs, normals, weights
and rigs are identical. Every other record, the news and all other manifest
fields stay byte-identical; no code, configuration, catalog, database or
player data is uploaded, and silver.dll/ti.exe are untouched.

Uses the guarded remote path of tools/publish_combat_se_atlas_20261116.py
(lock, exact manifest, SQLite backup, atomic writes, old blobs kept).

Usage: python tools/publish_combat_helmet_clearance_20261116.py {inspect|apply|verify}
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
from tools.helmet_head_clearance import HELMETS  # noqa: E402
from tools.mdjx_mesh import read  # noqa: E402
from tools.publish_hd_map_textures_20261114 import package, sha, verify  # noqa: E402

OUT = ROOT/'reports/combat-helmet-clearance-20261116'
BUILD = ROOT/'work/combat-se-atlas-20261116/helmets'
PREVIOUS_VERSION, VERSION = '2026.11.16.1', '2026.11.16.2'
MANIFEST_SHA = '87ca75812b3902e36ec2e8be25581b2bd26049f12735cdfd1a396ab57cac9342'
REMOTE_PACKAGE = '/root/tio-combat-helmet-clearance-20261116.zip'


def candidate() -> tuple[bytes, bytes, list[dict], dict[str, bytes]]:
    old = (OUT/'manifest-before.json').read_bytes()
    if sha(old) != MANIFEST_SHA:
        raise ValueError('Inspected hosted manifest changed')
    manifest = json.loads(old)
    if manifest['version'] != PREVIOUS_VERSION:
        raise ValueError('Unexpected previous client version')
    existing = {r['path']: r for r in manifest['files']}
    built = {r['path']: r for r in json.loads((BUILD/'helmets.json').read_text(encoding='utf-8'))}
    expected = {f'base/models/{name}.mdjx' for name in HELMETS}
    if set(built) != expected:
        raise ValueError('Unexpected helmet set')
    records, payload = [], {}
    for path in sorted(expected):
        row, hosted = built[path], existing[path]
        raw = (BUILD/Path(path).name).read_bytes()
        if sha(raw) != row['sha256'] or hosted['sha256'] != row['source_sha256'] or len(raw) != hosted['size']:
            raise ValueError(f'Built mesh does not derive from the hosted one: {path}')
        read(BUILD/Path(path).name)  # must still parse under the native layout checks
        records.append(dict(path=path, size=len(raw), sha256=sha(raw), seed=hosted['seed']))
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
