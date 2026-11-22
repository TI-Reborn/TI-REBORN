"""Publish Enter and P90 together through the existing guarded publisher."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.client_exchange_enter import patch, SOURCE_SHA
from tools.publish_ui_modernization_remote import REMOTE, verify_https
from tools.build_launcher_silver_regions import require_compatible

WORK = ROOT / 'work/gameplay-20261117'
OUT = ROOT / 'reports/gameplay-20261117'
VERSION = '2026.11.17.1'
CFG_SHA = 'a8707e565e728fd3f06783f7eb90ce692a8d4fc7bf54e0e966e82133c264f631'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidates():
    silver = (WORK / 'source-silver.dll').read_bytes()
    cfg = (WORK / 'source-items.cfg').read_bytes()
    assert sha(silver) == SOURCE_SHA and sha(cfg) == CFG_SHA
    start = cfg.index(b'Section 306: P90')
    end = cfg.index(b'Section ', start + 1)
    section = cfg[start:end]
    assert section.count(b'actionPoints=5') == 1
    changed_cfg = cfg[:start] + section.replace(b'actionPoints=5', b'actionPoints=4') + cfg[end:]
    changed_silver = patch(silver)
    require_compatible(changed_silver)
    return {'silver.dll': (silver, changed_silver), 'base/items.cfg': (cfg, changed_cfg)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'publish', 'verify'))
    args = parser.parse_args()
    pairs = candidates()
    old = (WORK / 'manifest-before.json').read_bytes()
    manifest = json.loads(old)
    previous = manifest['version']
    updates = {}
    patches = {}
    for name, (source, changed) in pairs.items():
        record = next(r for r in manifest['files'] if r['path'] == name)
        assert (record['sha256'], record['size']) == (sha(source), len(source))
        assert len(source) == len(changed)
        patches[name] = [(i, a, b) for i, (a, b) in enumerate(zip(source, changed)) if a != b]
        assert 0 < len(patches[name]) < 4096
        record.update(sha256=sha(changed), size=len(changed))
        updates[name] = dict(sha256=sha(changed), bytes=len(changed), blob=base64.b64encode(changed).decode())
        target = WORK / 'client-candidate' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(changed)
    manifest['version'] = VERSION
    new = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    (WORK / 'manifest-after.json').write_bytes(new)
    payload = dict(action='apply' if args.mode == 'publish' else 'inspect', updates=updates,
                   before_manifest=base64.b64encode(old).decode(),
                   after_manifest=base64.b64encode(new).decode(), after_manifest_sha256=sha(new))
    if args.mode == 'verify':
        result = verify_https(payload)
        result['version'] = VERSION
    else:
        script = REMOTE.split("if __name__=='__main__':")[0]
        script = script.replace('6330', str(len(manifest['files'])))
        script = script.replace("set(updates) not in ({'silver.dll'},{'silver.dll','ti.exe'})", "set(updates) != {'silver.dll','base/items.cfg'}")
        script = script.replace('if len(ids)<202:', 'if len(ids)<55:')
        old_backup = "for name,source in sources.items():(folder/name).write_bytes(source)"
        assert script.count(old_backup) == 1
        script = script.replace(old_backup, "for name,source in sources.items():\n  (folder/name).parent.mkdir(parents=True,exist_ok=True);(folder/name).write_bytes(source)")
        script += f"""
import os
disk=os.statvfs('/')
assert disk.f_bavail*disk.f_frsize >= 4*1024**3+36*1024**2, 'Publication disk headroom insufficient'
MANIFEST_SHA={sha(old)!r}
PREVIOUS_VERSION={previous!r}
VERSION={VERSION!r}
SOURCES={ {n:(sha(a),len(a)) for n,(a,b) in pairs.items()}!r}
CANDIDATES={ {n:(sha(b),len(b)) for n,(a,b) in pairs.items()}!r}
PATCHES={patches!r}
def identity(name,raw,expected_sha,expected_bytes):
 assert name in CANDIDATES and (expected_sha,expected_bytes)==CANDIDATES[name]
 assert (sha(raw),len(raw))==CANDIDATES[name]
def preserved_native(name,source,candidate):
 expected=bytearray(source)
 for offset,before,after in PATCHES[name]:
  assert expected[offset]==before
  expected[offset]=after
 assert bytes(expected)==candidate
def guards():
 return dict(services=services(),
  launchers={{name:state(DOWNLOADS/name) for name in ('TIO-Launcher.exe','launcher-manifest.json')}},
  configuration={{str(path):state(path) for path in CONFIGS if path.exists()}},game_code=code_states())
print(json.dumps(execute(json.load(sys.stdin))))
"""
        command = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
                   '-o', 'ConnectTimeout=15', 'root@185.184.42.88', 'python3 -c '+shlex.quote(script)]
        run = subprocess.run(command, input=json.dumps(payload), capture_output=True, encoding='utf-8', timeout=180)
        (OUT / ('client-'+args.mode+'-diagnostics.txt')).write_text(run.stderr, encoding='utf-8')
        if run.returncode:
            raise RuntimeError('Guarded publication failed; see diagnostics')
        result = json.loads(run.stdout)
    (OUT / ('client-'+args.mode+'.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'guards'}))


if __name__ == '__main__':
    main()
