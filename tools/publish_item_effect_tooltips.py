"""Publish three verified tooltip assets without restarting the game service.

The default operation prepares a candidate. --publish performs a guarded
manifest swap after a fresh hosted save/code/config backup. Player data is
never uploaded or restored. Native verification must precede publication.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy.client_item_effect_tooltips import BASE_SHA, HOOK, IMAGE_BASE, patch
from deploy.item_effect_descriptions import extend_language, load_descriptions
from tools.deploy_stage4_economy import remote

ORIGIN = 'https://185.184.42.88/updates/'
ASSETS = ('silver.dll', 'base/russian.lng', 'base/english.lng')

PUBLISH = r'''
from contextlib import closing
from pathlib import Path
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tarfile,tempfile

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def atomic(raw, target):
    descriptor, name = tempfile.mkstemp(prefix='.tooltips-', dir=target.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        pending.chmod(0o644)
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)

def service_state():
    return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID',
                                   '-p','ActiveState','-p','NRestarts'], text=True)

payload = json.load(sys.stdin)
live = Path('/var/www/tio-client/updates')
root = Path('/opt/tio-emulator')
assets = {'silver.dll','base/russian.lng','base/english.lng'}
with open('/root/.tio-gameplay-client.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    old = base64.b64decode(payload['before_manifest'], validate=True)
    new = base64.b64decode(payload['after_manifest'], validate=True)
    if (live/'manifest.json').read_bytes() != old:
        raise RuntimeError('Published manifest changed; rebuild candidate')
    before, after = json.loads(old), json.loads(new)
    if set(before) != set(after) or any(before[k] != after[k] for k in before if k not in ('version','files')):
        raise ValueError('Unexpected manifest metadata change')
    if [row['path'] for row in before['files']] != [row['path'] for row in after['files']]:
        raise ValueError('Client file list changed')
    changed = {b['path'] for a,b in zip(before['files'],after['files']) if a != b}
    if changed != assets or set(payload['candidates']) != assets:
        raise ValueError('Expected exactly three tooltip assets')
    if tuple(map(int, after['version'].split('.'))) <= tuple(map(int,before['version'].split('.'))):
        raise ValueError('Client version must increase')
    originals, candidates = {}, {}
    for a,b in zip(before['files'],after['files']):
        if a['path'] not in assets:
            continue
        if set(a) != set(b) or any(a[k] != b[k] for k in a if k not in ('sha256','size')) or b['seed']:
            raise ValueError('Unexpected asset metadata change')
        source = (live/'blobs'/a['sha256']).read_bytes()
        candidate = base64.b64decode(payload['candidates'][a['path']], validate=True)
        if digest(source) != a['sha256'] or len(source) != a['size']:
            raise RuntimeError('Original client blob differs')
        if digest(candidate) != b['sha256'] or len(candidate) != b['size']:
            raise ValueError('Candidate client blob differs')
        originals[a['path']], candidates[a['path']] = source, candidate
    source, candidate = originals['silver.dll'], candidates['silver.dll']
    if digest(source) != payload['base_sha256']:
        raise RuntimeError('Published native client base differs')
    edits = payload['edits']
    if len(edits) != 4 or len(candidate)-len(source) != 0x4000:
        raise ValueError('Unexpected native patch boundary')
    reconstructed = bytearray(source)
    for edit in edits:
        offset = edit['offset']
        prior, following = bytes.fromhex(edit['before']), bytes.fromhex(edit['after'])
        if type(offset) is not int or offset < 0 or len(prior) != len(following) or offset+len(prior) > len(source):
            raise ValueError('Invalid native patch edit')
        if source[offset:offset+len(prior)] != prior:
            raise ValueError('Native patch preimage differs')
        reconstructed[offset:offset+len(prior)] = following
    if bytes(reconstructed) != candidate[:len(source)]:
        raise ValueError('Unrelated native client bytes changed')
    for name in assets-{'silver.dll'}:
        if not candidates[name].startswith(originals[name]):
            raise ValueError('Existing localization was modified')
        lines = candidates[name][len(originals[name]):].decode('cp1251').splitlines()
        if not lines or any(line and not line.startswith('tio_item_effect_') for line in lines):
            raise ValueError('Unexpected localization extension')
    service = service_state()
    if 'ActiveState=active' not in service:
        raise RuntimeError('Hosted game service is not active')
    backup = Path(tempfile.mkdtemp(prefix='tio-before-item-effect-tooltips-',dir='/root'))
    backup.chmod(0o700)
    (backup/'manifest.json').write_bytes(old)
    for name,raw in originals.items():
        target = backup/'client'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    shutil.copy2('/etc/tio-server/server.toml', backup/'server.toml')
    shutil.copy2('/etc/systemd/system/tio-server.service', backup/'tio-server.service')
    with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
        for directory, pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json')):
            for path in sorted((root/directory).rglob(pattern)):
                archive.add(path, arcname=path.relative_to(root).as_posix())
    with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src:
        with closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Hosted save backup failed integrity check')
    if (live/'manifest.json').read_bytes() != old:
        raise RuntimeError('Manifest changed during backup')
    for row in after['files']:
        if row['path'] not in assets:
            continue
        target = live/'blobs'/row['sha256']
        raw = candidates[row['path']]
        if target.exists():
            if target.read_bytes() != raw:
                raise RuntimeError('Existing immutable blob differs')
        else:
            atomic(raw, target)
    atomic(new, live/'manifest.json')
    if service_state() != service:
        raise RuntimeError('Game service changed during asset publication')
    report = dict(version=after['version'], backup=str(backup), changed=sorted(assets),
                  server_restarted=False, database_written=False, service_unchanged=True,
                  manifest_sha256=digest(new), local_player_data_uploaded=False)
    (backup/'publication.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
'''


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(ORIGIN+path, timeout=60) as response:
        return response.read()


def native_edits(before: bytes, after: bytes) -> list[dict]:
    import pefile
    pe = pefile.PE(data=before)
    try:
        section = pe.sections[-1].get_file_offset()
        spans = [(section+8, 4), (section+16, 4),
                 (pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), 4),
                 (pe.get_offset_from_rva(HOOK-IMAGE_BASE), 5)]
        edits = [dict(offset=at, before=before[at:at+size].hex(),
                      after=after[at:at+size].hex()) for at,size in spans]
        restored = bytearray(before)
        for edit in edits:
            at = edit['offset']
            raw = bytes.fromhex(edit['after'])
            restored[at:at+len(raw)] = raw
        if bytes(restored) != after[:len(before)]:
            raise ValueError('Unrelated published client bytes changed')
        return edits
    finally:
        pe.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}\.\d+', args.version):
        raise ValueError('Invalid release version')
    folder = args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'publication.json').exists():
        raise ValueError('Preserve existing publication receipt')
    old = fetch('manifest.json')
    manifest = json.loads(old)
    if tuple(map(int,args.version.split('.'))) <= tuple(map(int,manifest['version'].split('.'))):
        raise ValueError('Version must increase')
    records = {row['path']:row for row in manifest['files']}
    originals = {}
    for name in ASSETS:
        record = records[name]
        raw = fetch('blobs/'+record['sha256'])
        if digest(raw) != record['sha256'] or len(raw) != record['size'] or record['seed']:
            raise ValueError('Published source validation failed')
        originals[name] = raw
    descriptions = load_descriptions(ROOT)
    candidates = {'silver.dll':patch(originals['silver.dll'], ROOT)}
    for language,name in (('ru','base/russian.lng'),('en','base/english.lng')):
        candidates[name] = extend_language(originals[name], language, descriptions[language])
    for name,raw in candidates.items():
        records[name].update(sha256=digest(raw), size=len(raw))
        target = folder/'candidate'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    manifest['version'] = args.version
    new = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (folder/'previous-manifest.json').write_bytes(old)
    (folder/'manifest.json').write_bytes(new)
    edits = native_edits(originals['silver.dll'], candidates['silver.dll'])
    (folder/'edits.json').write_text(json.dumps(edits,indent=2)+'\n')
    if not args.publish:
        print(json.dumps(dict(prepared=True, version=args.version, changed=ASSETS)))
        return
    proof = json.loads((folder/'native-proof.json').read_text(encoding='utf-8'))
    if (proof.get('passed') is not True or proof['cases'] != 60
            or proof['source_sha256'] != BASE_SHA
            or proof['candidate_sha256'] != digest(candidates['silver.dll'])):
        raise ValueError('Native proof does not match the candidate')
    report = remote(PUBLISH, dict(
        before_manifest=base64.b64encode(old).decode(),
        after_manifest=base64.b64encode(new).decode(), base_sha256=BASE_SHA, edits=edits,
        candidates={name:base64.b64encode(raw).decode() for name,raw in candidates.items()},
    ))
    (folder/'publication.json').write_text(json.dumps(report,indent=2)+'\n')
    if fetch('manifest.json') != new:
        raise RuntimeError('Public HTTPS manifest differs after publication')
    for name,raw in candidates.items():
        if fetch('blobs/'+digest(raw)) != raw:
            raise RuntimeError('Public HTTPS asset differs: '+name)
    (folder/'https-proof.json').write_text(json.dumps(dict(
        passed=True, version=args.version, trusted_https=True, changed=ASSETS,
    ),indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
