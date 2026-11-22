"""Publish the Survival bot note in the native matchmaking status resources."""

import argparse
from collections.abc import Callable
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen

from tools.publish_ui_modernization_remote import REMOTE


ORIGIN = 'https://185.184.42.88/updates/'
BASELINE = 'fd226bb5ded89aba5f60de985e951f6909d99108b73e491bb7a3bb788239c8a0'
VERSION = '2026.11.19.2'
LABELS = {
    'base/russian.lng': 'Ищем соперника. Если за минуту в «Выживании» никто не найдётся, вступит бот.',
    'base/english.lng': 'Searching. In Survival, a bot joins after one minute without an opponent.',
    'base/german.lng': 'Gegnersuche. Findet sich im Survival-Modus eine Minute lang kein Gegner, tritt ein Bot bei.',
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def release(old: bytes, read_blob: Callable[[str], bytes]) -> tuple[bytes, dict[str, bytes], dict[str, bytes]]:
    if sha(old) != BASELINE:
        raise ValueError('Expected the exact published 2026.11.19.1 manifest')
    manifest = json.loads(old)
    sources = {}
    candidates = {}
    for row in manifest['files']:
        name = row['path']
        if name not in LABELS:
            continue
        source = read_blob(row['sha256'])
        if name in sources or row['seed'] or (sha(source), len(source)) != (row['sha256'], row['size']):
            raise ValueError(f'Unexpected published language resource {name}')
        matches = list(re.finditer(rb'(?m)^bs73=[^\r\n]*(?=\r?$)', source))
        if len(matches) != 1:
            raise ValueError(f'Expected one native waiting status in {name}')
        line = matches[0]
        raw = source[:line.start()] + b'bs73=' + LABELS[name].encode('cp1251') + source[line.end():]
        sources[name] = source
        candidates[name] = raw
        row.update(sha256=sha(raw), size=len(raw))
    if sources.keys() != LABELS.keys():
        raise ValueError('Published manifest is missing a language resource')
    manifest['version'] = VERSION
    new = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return new, sources, candidates


def remote_source(action: str, reviewed_manifest: str) -> str:
    template = REMOTE.split("if __name__=='__main__':", 1)[0]
    template = template.replace('tio-before-ui-modernization-', 'tio-before-survival-wait-')
    template = template.replace("if len(ids)<202:", "if len(ids)<55:").replace('inspected202', 'release')
    return template + f'''
from collections.abc import Callable

BASELINE = {BASELINE!r}
VERSION = {VERSION!r}
PREVIOUS_VERSION = '2026.11.19.1'
LABELS = {LABELS!r}

{inspect.getsource(release)}

def guards():
 return dict(services=services(),
   launchers={{name:state(DOWNLOADS/name) for name in ('TIO-Launcher.exe','launcher-manifest.json')}},
   configuration={{str(path):state(path) for path in CONFIGS if path.exists()}}, game_code=code_states())

def transition(p):
 directory(LIVE)
 directory(LIVE/'blobs')
 old = regular(LIVE/'manifest.json').read_bytes()
 new, sources, candidates = release(old, lambda digest: regular(LIVE/'blobs'/digest).read_bytes())
 if sha(new) != p['reviewed_manifest']:
  raise ValueError('Hosted locales differ from the locally reviewed release')
 # Backup takes flat filenames. The manifest retains the full names.
 saved = {{Path(name).name: raw for name, raw in sources.items()}}
 return old, new, saved, candidates, dict(changed=sorted(candidates),
                      preserved_records=len(json.loads(old)['files']) - len(candidates))

disk = os.statvfs('/')
if disk.f_bavail * disk.f_frsize < 4 * 1024**3 + 30 * 1024**2:
 raise RuntimeError('Insufficient disk space for the publication backup')
if os.geteuid() != 0:
 raise PermissionError('Expected the configured publication user')
print(json.dumps(execute(dict(action={action!r}, reviewed_manifest={reviewed_manifest!r}))))
'''


def fetch(path: str) -> bytes:
    with urlopen(ORIGIN + path, timeout=30) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'publish', 'verify'))
    parser.add_argument('baseline', type=Path, help='Saved prepublication HTTPS manifest')
    args = parser.parse_args()
    new, _, candidates = release(args.baseline.read_bytes(), lambda digest: fetch('blobs/' + digest))
    if args.mode == 'verify':
        if fetch('manifest.json') != new or any(fetch('blobs/' + sha(raw)) != raw for raw in candidates.values()):
            raise RuntimeError('Public manifest or locale blob differs from the reviewed release')
        print(json.dumps(dict(version=VERSION, manifest_sha256=sha(new), https=True, paths=sorted(candidates))))
        return
    source = remote_source('apply' if args.mode == 'publish' else 'inspect', sha(new))
    result = subprocess.run(
        ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
         '-o', 'ConnectTimeout=15', 'root@185.184.42.88', 'python3 -'],
        input=source, encoding='utf-8', capture_output=True, timeout=120,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr else 'Publication SSH failed')
    receipt = json.loads(result.stdout)
    keys = ('operation', 'version', 'backup', 'manifest_sha256', 'health', 'patch_scope')
    print(json.dumps({key: receipt[key] for key in keys if key in receipt}))


if __name__ == '__main__':
    main()
