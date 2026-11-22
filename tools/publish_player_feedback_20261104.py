"""Publish only reviewed city/shop Silver bytes; reuse guarded atomic publication."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.client_player_feedback import patch, SOURCE_SHA
from tools.publish_ui_modernization_remote import REMOTE as TEMPLATE
from tools.build_launcher_silver_regions import require_compatible

OUT = ROOT / 'reports/player-feedback-20261104'
VERSION = '2026.11.04.1'
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=15', 'root@185.184.42.88']


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'publish', 'verify'))
    args = parser.parse_args()
    old = (OUT/'manifest-before.json').read_bytes()
    manifest = json.loads(old)
    source = (OUT/'source-silver.dll').read_bytes()
    candidate = patch(source)
    assert sha(source) == SOURCE_SHA
    # Launcher adapters (scope fog, grenades, flame, rain, contracts) bind only
    # when their Silver regions are unchanged; never publish one that breaks them.
    require_compatible(candidate)
    record = next(r for r in manifest['files'] if r['path'] == 'silver.dll')
    assert record['sha256'] == SOURCE_SHA and record['size'] == len(source)
    record.update(sha256=sha(candidate), size=len(candidate))
    previous = manifest['version']; manifest['version'] = VERSION
    new = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode()
    (OUT/'candidate-silver.dll').write_bytes(candidate)
    (OUT/'manifest-after.json').write_bytes(new)
    if args.mode == 'verify':
        with urllib.request.urlopen('https://185.184.42.88/updates/manifest.json', timeout=30) as response:
            assert response.read() == new
        with urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+sha(candidate), timeout=30) as response:
            assert response.read() == candidate
        print(json.dumps(dict(passed=True, https=True, version=VERSION, silver_sha256=sha(candidate))))
        return
    changes = []
    start = None
    for i, (before, after) in enumerate(zip(source, candidate)):
        if before != after and start is None:
            start = i
        if before == after and start is not None:
            changes.append((start, source[start:i].hex(), candidate[start:i].hex())); start = None
    if start is not None:
        changes.append((start, source[start:].hex(), candidate[start:].hex()))
    assert len(candidate) == len(source) and sum(len(bytes.fromhex(c[1])) for c in changes) <= 4096
    payload = dict(action='apply' if args.mode == 'publish' else 'inspect',
                   updates={'silver.dll': dict(sha256=sha(candidate), bytes=len(candidate),
                                               blob=base64.b64encode(candidate).decode())},
                   before_manifest=base64.b64encode(old).decode(),
                   after_manifest=base64.b64encode(new).decode(), after_manifest_sha256=sha(new))
    # Override historical release identities, retaining the publisher's backups,
    # exclusive lock, baseline checks, immutable blobs and atomic manifest commit.
    script = TEMPLATE.split("if __name__=='__main__':")[0].replace('6330', str(len(manifest['files'])))
    script = script.replace('if len(ids)<202:', 'if len(ids)<55:')
    script += f'''
import os
disk=os.statvfs('/')
assert disk.f_bavail*disk.f_frsize >= 4*1024**3+36*1024**2, 'Publication disk headroom insufficient'

MANIFEST_SHA={sha(old)!r}
PREVIOUS_VERSION={previous!r}
VERSION={VERSION!r}
SOURCES={{'silver.dll': ({SOURCE_SHA!r}, {len(source)})}}
PATCHES={changes!r}
def preserved_native(name, source, candidate):
 expected=bytearray(source)
 assert len(source)==len(candidate)
 for offset,before,after in PATCHES:
  before=bytes.fromhex(before);after=bytes.fromhex(after)
  assert source[offset:offset+len(before)]==before and len(before)==len(after)
  expected[offset:offset+len(before)]=after
 assert bytes(expected)==candidate, 'Unreviewed native byte changed'
def guards():
 return dict(services=services(),
  launchers={{name:state(DOWNLOADS/name) for name in ('TIO-Launcher.exe','launcher-manifest.json')}},
  configuration={{str(path):state(path) for path in CONFIGS if path.exists()}},game_code=code_states())
print(json.dumps(execute(json.load(sys.stdin))))
'''
    result = subprocess.run(SSH+['python3 -c '+shlex.quote(script)], input=json.dumps(payload),
                            capture_output=True, text=True, encoding='utf-8', timeout=180)
    (OUT/(args.mode+'-diagnostics.txt')).write_text(result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Guarded publication failed; see private/local diagnostics')
    report = json.loads(result.stdout)
    (OUT/(args.mode+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('guards',)}))


if __name__ == '__main__':
    main()
