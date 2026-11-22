"""Publish the "new interface" HD map sheets as new client files only.

Adds the reviewed base/hd/setting/<rel>.hd records to the hosted client
manifest (2026.11.14.3 -> 2026.11.14.4). Every existing record, the news and
all other manifest fields stay byte-identical; no code, configuration,
database or player data is uploaded. Launchers before 0.1.48 never read these
files; 0.1.48 loads them only in the "new" interface (NativeHdMapTextures).

The remote step locks client publication, checks the live manifest is exactly
the inspected one, backs up SQLite (online backup + integrity) and the previous
manifest, writes blobs atomically, then swaps the manifest atomically.

Usage: python tools/publish_hd_map_textures_20261114.py {inspect|apply|verify}
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.request
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_hd_map_textures import HD2_CHUNK, HD2_SUFFIX, PILOT_SHEETS, PNG_IHDR_END, hd_path  # noqa: E402

OUT = ROOT/'reports/hd-map-textures-20261114'
BUILD = ROOT/'work/hd-map-textures-20261114/out'
PREVIOUS_VERSION, VERSION = '2026.11.14.3', '2026.11.14.4'
MANIFEST_SHA = '04dcb1c9bb2492958cf8e85ce8d0fc56666ac15f990e3f0e48a97ace6bf0fde8'
EXPECTED_FILES = 159
EXPECTED_CHANGES = None  # changed .hd records (added or replaced); None for the first release
EXPECTED_PATHS: set[str] | None = None
DOUBLE_DENSITY_SHEETS = frozenset(PILOT_SHEETS)
REMOTE_PACKAGE = '/root/tio-hd-map-textures-20261114.zip'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'tio']
ORIGINS = ('https://ti-reborn.com/updates/', 'https://185.184.42.88/updates/')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate() -> tuple[bytes, bytes, list[dict], dict[str, bytes]]:
    old = (OUT/'manifest-before.json').read_bytes()
    if sha(old) != MANIFEST_SHA:
        raise ValueError('Inspected hosted manifest changed')
    manifest = json.loads(old)
    if manifest['version'] != PREVIOUS_VERSION:
        raise ValueError('Unexpected previous client version')
    existing = {r['path']: r for r in manifest['files']}
    built = json.loads((BUILD/'hd-map-textures.json').read_text(encoding='utf-8'))
    built_paths = {r['path'] for r in built}
    if (len(built) != EXPECTED_FILES or len(built_paths) != EXPECTED_FILES
            or EXPECTED_PATHS is not None and built_paths != EXPECTED_PATHS):
        raise ValueError('Unexpected HD sheet set')
    records, payload = [], {}
    for row in sorted(built, key=lambda r: r['path']):
        path = row['path']
        output_scale = 2 if path.endswith(HD2_SUFFIX) else 1
        if path != hd_path(row['source'], output_scale=output_scale) or (
            output_scale == 2 and row['source'] not in DOUBLE_DENSITY_SHEETS
        ):
            raise ValueError(f'Unexpected HD path {path}')
        if existing.get(path, {}).get('sha256') == row['sha256']:
            continue  # already published unchanged
        source = existing.get(row['source'])
        if source is None or source['sha256'] != row['source_sha256']:
            raise ValueError(f'Hosted source sheet differs from the composed one: {row["source"]}')
        raw = (BUILD/path).read_bytes()
        if sha(raw) != row['sha256'] or len(raw) != row['bytes'] or raw[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'Built file changed: {path}')
        if (raw[PNG_IHDR_END:PNG_IHDR_END + 8] == bytes(4) + HD2_CHUNK) != (output_scale == 2):
            raise ValueError(f'Unexpected HD density marker: {path}')
        with Image.open(io.BytesIO(raw)) as image:
            if list(image.size) != row['size'] or image.mode != 'RGBA':
                raise ValueError(f'Unexpected image geometry: {path}')
        records.append(dict(path=path, size=len(raw), sha256=sha(raw), seed=False))
        payload[path] = raw
    if EXPECTED_CHANGES is not None and len(records) != EXPECTED_CHANGES:
        raise ValueError(f'Expected {EXPECTED_CHANGES} changed HD records, found {len(records)}')
    changed = {r['path']: r for r in records}
    manifest['version'] = VERSION
    # Replaced records keep their position; new ones are appended.
    manifest['files'] = [changed.pop(r['path'], r) for r in manifest['files']] + list(changed.values())
    new = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return old, new, records, payload


def package(payload: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as archive:
        for name in sorted(payload):
            info = zipfile.ZipInfo(name, (2026, 11, 14, 0, 0, 0))
            archive.writestr(info, payload[name])
    return stream.getvalue()


REMOTE = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
import base64,fcntl,hashlib,json,os,sqlite3,subprocess,tempfile,zipfile
p=json.loads(base64.b64decode(PAYLOAD))
LIVE=Path('/var/www/tio-client/updates');PACKAGE=Path(p['package']);DB=Path('/var/lib/tio-server/reservation.sqlite3')
sha=lambda b:hashlib.sha256(b).hexdigest()
old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
assert sha(old)==p['before_sha256'] and sha(new)==p['after_sha256']
a,b=json.loads(old),json.loads(new)
assert a['version']==p['previous_version'] and b['version']==p['version']
assert set(a)==set(b) and all(a[k]==b[k] for k in a if k not in ('version','files'))
old_paths=[r['path'] for r in a['files']];new_paths=[r['path'] for r in b['files']]
assert new_paths[:len(old_paths)]==old_paths and len(set(new_paths))==len(new_paths),'Record order must stay; new records are appended'
before_records={r['path']:r for r in a['files']}
added={r['path']:r for r in b['files'] if before_records.get(r['path'])!=r}
assert len(added)==p['count']
for name,r in added.items():
 q=PurePosixPath(name)
 assert name.startswith('base/hd/setting/') and q.suffix=='.hd' and '..' not in q.parts and not q.is_absolute(),'Only HD map records may change'
 assert set(r)=={'path','size','sha256','seed'} and r['seed'] is False
raw_package=PACKAGE.read_bytes();assert sha(raw_package)==p['package_sha256']
blobs={}
with zipfile.ZipFile(PACKAGE) as z:
 assert sorted(z.namelist())==sorted(added)
 for name,r in added.items():
  raw=z.read(name);assert sha(raw)==r['sha256'] and len(raw)==r['size'] and raw[:8]==b'\x89PNG\r\n\x1a\n';blobs[r['sha256']]=raw

def protected():
 with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=15)) as db:
  assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
  return {t:dict(rows=db.execute('SELECT count(*) FROM '+t).fetchone()[0]) for t in ('accounts','characters','wallets','warehouse_items','clans')}
def service():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState'],text=True).split()
def atomic(target,raw,mode=0o644):
 fd,name=tempfile.mkstemp(prefix='.hd-maps-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as s:s.write(raw);s.flush();os.fsync(s.fileno())
  os.chmod(name,mode);os.replace(name,target)
 except BaseException:
  if os.path.exists(name):os.unlink(name)
  raise
 d=os.open(target.parent,os.O_RDONLY);os.fsync(d);os.close(d)

assert (LIVE/'manifest.json').read_bytes()==old,'Hosted manifest changed since inspection'
before=dict(service=service(),tables=protected())
existing=sum((LIVE/'blobs'/h).exists() for h in blobs)
if p['action']=='inspect':
 print(json.dumps(dict(passed=True,operation='inspect',remote_mutations=0,new_records=len(added),new_blobs=len(blobs)-existing,
  existing_blobs=existing,package_bytes=len(raw_package),before=before)));raise SystemExit
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert (LIVE/'manifest.json').read_bytes()==old
os.umask(0o077)
folder=Path(tempfile.mkdtemp(prefix='tio-before-hd-map-textures-',dir='/root'))
with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=15)) as src,closing(sqlite3.connect(folder/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
(folder/'previous-manifest.json').write_bytes(old)
(folder/'receipt.json').write_text(json.dumps(dict(created_utc=datetime.now(timezone.utc).isoformat(),sqlite_integrity='ok',
 previous_manifest_sha256=sha(old),next_manifest_sha256=sha(new),before=before),indent=2))
written=0
for h,raw in blobs.items():
 target=LIVE/'blobs'/h
 if target.exists():assert sha(target.read_bytes())==h;continue
 atomic(target,raw);written+=1
for h in blobs:assert sha((LIVE/'blobs'/h).read_bytes())==h
assert (LIVE/'manifest.json').read_bytes()==old,'Hosted manifest changed during publication'
atomic(LIVE/'manifest.json',new)
assert (LIVE/'manifest.json').read_bytes()==new
after=dict(service=service(),tables=protected())
assert after==before,'Hosted service or protected tables changed during publication'
PACKAGE.unlink()
print(json.dumps(dict(passed=True,operation='apply',backup=str(folder),blobs_written=written,new_records=len(added),
 manifest_sha256=sha(new),version=p['version'],before=before,after=after)))
'''


def remote(action: str, old: bytes, new: bytes, records: list[dict], package_sha: str) -> dict:
    payload = dict(action=action, package=REMOTE_PACKAGE, package_sha256=package_sha,
                   before_manifest=base64.b64encode(old).decode(), after_manifest=base64.b64encode(new).decode(),
                   before_sha256=sha(old), after_sha256=sha(new), previous_version=PREVIOUS_VERSION,
                   version=VERSION, count=len(records))
    script = 'PAYLOAD=' + repr(base64.b64encode(json.dumps(payload).encode()).decode()) + '\n' + REMOTE
    result = subprocess.run(SSH + ['python3 -'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=900)
    if result.returncode:
        raise RuntimeError('Remote ' + action + ' failed: ' + (result.stderr.strip().splitlines() or ['?'])[-1])
    return json.loads(result.stdout)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60, context=ssl.create_default_context()) as response:
        return response.read()


def verify(new: bytes, records: list[dict]) -> dict:
    checks = {}
    for origin in ORIGINS:
        try:
            raw = fetch(origin + 'manifest.json')
        except Exception as error:  # an origin without a public certificate is reported, not hidden
            checks[origin] = dict(error=type(error).__name__)
            continue
        ok = raw == new
        blobs = sum(sha(fetch(origin + 'blobs/' + r['sha256'])) == r['sha256'] for r in records) if ok else 0
        checks[origin] = dict(manifest_exact=ok, blobs_verified=blobs, blobs_expected=len(records))
    if not any(c.get('manifest_exact') and c['blobs_verified'] == c['blobs_expected'] for c in checks.values()):
        raise RuntimeError(f'HTTPS verification failed: {checks}')
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'apply', 'verify'))
    args = parser.parse_args()
    old, new, records, payload = candidate()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == 'verify':
        result = dict(version=VERSION, manifest_sha256=sha(new), https=verify(new, records))
    else:
        archive = package(payload)
        local = OUT/'package.zip'
        local.write_bytes(archive)
        sent = subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', str(local), 'tio:' + REMOTE_PACKAGE], capture_output=True, timeout=900)
        if sent.returncode:
            raise RuntimeError('Package upload failed')
        result = remote(args.mode, old, new, records, sha(archive))
        local.unlink()
    (OUT/f'publication-{args.mode}.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result)[:2000])


if __name__ == '__main__':
    main()
