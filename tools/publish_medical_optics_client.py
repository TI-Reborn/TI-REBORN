"""Publish medical XML and two NVG text rows; keep launcher/DLL unchanged."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.medical_optics_assets import patch_health_metadata, patch_night_vision_language, replacements
from tools.deploy_stage4_economy import remote

ORIGIN = 'https://185.184.42.88/updates/'
ASSETS = ('base/shared config/items.xml', 'base/russian.lng', 'base/english.lng')
NATIVE_SHA = '28f33ff6a920182eeb7a81b9d3c30853081f3f52c7d505da15b54de97c01b2ad'
PREVIOUS = '2026.10.24.1'
VERSION = '2026.10.24.2'

PUBLISH = r'''
from contextlib import closing
from pathlib import Path
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def atomic(raw, target):
    descriptor,name = tempfile.mkstemp(prefix='.medical-optics-',dir=target.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor,'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        pending.chmod(0o644)
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)

def service():
    return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID',
                                   '-p','NRestarts','-p','ActiveState'],text=True)

payload = json.load(sys.stdin)
live = Path('/var/www/tio-client/updates')
assets = {'base/shared config/items.xml','base/russian.lng','base/english.lng'}
with open('/root/.tio-gameplay-client.lock','a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    old = base64.b64decode(payload['before_manifest'],validate=True)
    new = base64.b64decode(payload['after_manifest'],validate=True)
    if (live/'manifest.json').read_bytes() != old:
        raise RuntimeError('Published manifest changed before release')
    a,b = json.loads(old),json.loads(new)
    if a['version'] != '2026.10.24.1' or b['version'] != '2026.10.24.2':
        raise ValueError('Unexpected release versions')
    if set(a) != set(b) or any(a[k] != b[k] for k in a if k not in ('version','files')):
        raise ValueError('Unrelated manifest metadata changed')
    if [r['path'] for r in a['files']] != [r['path'] for r in b['files']]:
        raise ValueError('Client file list changed')
    if {y['path'] for x,y in zip(a['files'],b['files']) if x != y} != assets:
        raise ValueError('Unexpected client asset changes')
    if set(payload['candidates']) != assets or set(payload['edits']) != assets:
        raise ValueError('Unexpected candidate scope')
    native = next(r for r in a['files'] if r['path'] == 'silver.dll')
    if native['sha256'] != payload['native_sha256']:
        raise ValueError('Published native adapter changed')
    for name,expected in payload['server_guards'].items():
        if '..' in Path(name).parts or not name.startswith(('tio/','config/')):
            raise ValueError('Unsafe runtime guard path')
        if sha((Path('/opt/tio-emulator')/name).read_bytes()) != expected:
            raise RuntimeError('Install verified server rules before client publication')
    sources,candidates = {},{}
    for x,y in zip(a['files'],b['files']):
        name = x['path']
        if name not in assets:
            continue
        if set(x) != set(y) or any(x[k] != y[k] for k in x if k not in ('sha256','size')):
            raise ValueError('Unexpected asset metadata change')
        source = (live/'blobs'/x['sha256']).read_bytes()
        candidate = base64.b64decode(payload['candidates'][name],validate=True)
        if sha(source) != x['sha256'] or len(source) != x['size']:
            raise RuntimeError('Published source blob differs')
        if sha(candidate) != y['sha256'] or len(candidate) != y['size']:
            raise ValueError('Candidate blob differs')
        edits = payload['edits'][name]
        if len(edits) != (1 if name.endswith('.xml') else 2):
            raise ValueError('Unexpected replacement count')
        restored = source
        for edit in edits:
            before,after = bytes.fromhex(edit['before']),bytes.fromhex(edit['after'])
            if not before or max(len(before),len(after)) > 8192 or restored.count(before) != 1:
                raise ValueError('Replacement is not uniquely bounded')
            if name.endswith('.xml'):
                if not before.startswith(b'<item ') or b'id="20"' not in before:
                    raise ValueError('Unexpected XML replacement')
            elif not before.startswith(b'tio_item_effect_5002_'):
                raise ValueError('Unexpected localization replacement')
            restored = restored.replace(before,after,1)
        if restored != candidate:
            raise ValueError('Unrelated client bytes changed')
        sources[name],candidates[name] = source,candidate
    state = service()
    if 'ActiveState=active' not in state:
        raise RuntimeError('Game service is not active')
    backup = Path(tempfile.mkdtemp(prefix='tio-before-medical-optics-client-',dir='/root'))
    backup.chmod(0o700)
    (backup/'manifest.json').write_bytes(old)
    for name,raw in sources.items():
        target = backup/'client'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
    for name in payload['server_guards']:
        target = backup/'runtime'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(Path('/opt/tio-emulator')/name,target)
    with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src:
        with closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Fresh player backup failed integrity check')
    if (live/'manifest.json').read_bytes() != old:
        raise RuntimeError('Manifest changed during backup')
    for row in b['files']:
        if row['path'] not in assets:
            continue
        target = live/'blobs'/row['sha256']
        raw = candidates[row['path']]
        if target.exists():
            if target.read_bytes() != raw:
                raise RuntimeError('Existing immutable blob differs')
        else:
            atomic(raw,target)
    atomic(new,live/'manifest.json')
    if service() != state:
        raise RuntimeError('Game service changed during asset publication')
    report = dict(passed=True,version=b['version'],backup=str(backup),changed=sorted(assets),
                  server_restarted=False,database_written=False,native_dll_unchanged=True,
                  manifest_sha256=sha(new),player_data_uploaded=False)
    (backup/'publication.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
'''


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(ORIGIN+path, timeout=60) as response:
        return response.read()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    folder = args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'client-publication.json').exists():
        raise ValueError('Preserve the existing publication receipt')
    old = fetch('manifest.json')
    manifest = json.loads(old)
    if manifest['version'] != PREVIOUS:
        raise ValueError('Published version changed; review the new baseline')
    rows = {row['path']:row for row in manifest['files']}
    if rows['silver.dll']['sha256'] != NATIVE_SHA:
        raise ValueError('Published native tooltip adapter differs')
    candidates, edits = {}, {}
    for name in ASSETS:
        row = rows[name]
        before = fetch('blobs/'+row['sha256'])
        if sha(before) != row['sha256'] or len(before) != row['size']:
            raise ValueError('Invalid source resource')
        xml = name.endswith('.xml')
        if xml:
            after = patch_health_metadata(before)
        else:
            language = 'ru' if name.endswith('russian.lng') else 'en'
            after = patch_night_vision_language(before, language, ROOT)
        edits[name] = replacements(before, after, xml=xml)
        candidates[name] = after
        row.update(sha256=sha(after), size=len(after))
        target = folder/'client-candidate'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(after)
    manifest['version'] = VERSION
    new = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (folder/'client-before-manifest.json').write_bytes(old)
    (folder/'client-manifest.json').write_bytes(new)
    (folder/'client-edits.json').write_text(json.dumps(edits,indent=2)+'\n')
    if not args.publish:
        print(json.dumps(dict(prepared=True,version=VERSION,native_dll_unchanged=True)))
        return
    installed = json.loads((folder/'installed.json').read_text())
    if installed.get('passed') is not True or installed['scope'] != 'medical-optics':
        raise ValueError('Verified server deployment receipt required')
    guards = {name:row['after'] for name,row in
              json.loads((folder/'patch-manifest.json').read_text()).items()}
    report = remote(PUBLISH, dict(
        before_manifest=base64.b64encode(old).decode(),
        after_manifest=base64.b64encode(new).decode(), native_sha256=NATIVE_SHA,
        candidates={name:base64.b64encode(raw).decode() for name,raw in candidates.items()},
        edits=edits, server_guards=guards,
    ))
    (folder/'client-publication.json').write_text(json.dumps(report,indent=2)+'\n')
    if fetch('manifest.json') != new:
        raise RuntimeError('Public HTTPS manifest differs')
    for name,raw in candidates.items():
        if fetch('blobs/'+sha(raw)) != raw:
            raise RuntimeError('Public HTTPS blob differs: '+name)
    (folder/'client-https-proof.json').write_text(json.dumps(dict(
        passed=True,version=VERSION,trusted_https=True,changed=ASSETS,
    ),indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
