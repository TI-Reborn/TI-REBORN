"""Publish IBM Plex Sans Condensed with native letter metrics (client 2026.11.20.3 -> .4).

Changes exactly: the silver.dll record (deploy/client_ui_font_metrics.py applied to the
published 2026.11.20.2 Silver) and new base/ui-hd/fonts/plexc-*.png atlases plus the
IBM Plex OFL licence, appended. News, every other record and all other manifest
fields stay byte-identical; no server code, configuration or player data is touched.
The launcher's native adapters are checked against the candidate before anything
is sent (tools.build_launcher_silver_regions.require_compatible).

The remote step locks client publication, checks the live manifest is exactly the
inspected one, backs up SQLite (online backup + integrity) and the previous manifest,
writes blobs atomically, then swaps the manifest atomically.

Usage: python tools/publish_ui_fonts_plex_20261120.py {inspect|apply|verify}
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.client_ui_font_metrics import ASSET_MANIFEST, SOURCE_SHA, load_assets, patch  # noqa: E402
from tools.build_launcher_silver_regions import require_compatible  # noqa: E402

OUT = ROOT / 'reports/ui-fonts-plex-20261120'
PREVIOUS_VERSION, VERSION = '2026.11.20.3', '2026.11.20.4'
MANIFEST_SHA = '0d1fc66bea3617f499b7cab0a7c8cdbade3e40dd379880e0de1db0bbd41f7b00'
EXPECTED_ASSETS = 37
REMOTE_PACKAGE = '/root/tio-ui-fonts-plex-20261120.zip'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'tio']
ORIGINS = ('https://ti-reborn.com/updates/', 'https://185.184.42.88/updates/')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch(url: str, verify_tls: bool = True) -> bytes:
    context = ssl.create_default_context()
    if not verify_tls:  # the bare IP has no public certificate; content is pinned by hash instead
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    with urllib.request.urlopen(url, timeout=60, context=context) as response:
        return response.read()


def candidate() -> tuple[bytes, bytes, list[dict], dict[str, bytes]]:
    before = OUT / 'manifest-before.json'
    if not before.exists():
        before.write_bytes(fetch(ORIGINS[1] + 'manifest.json', verify_tls=False))
    old = before.read_bytes()
    if sha(old) != MANIFEST_SHA:
        raise ValueError('Inspected hosted manifest changed')
    manifest = json.loads(old)
    if manifest['version'] != PREVIOUS_VERSION:
        raise ValueError('Unexpected previous client version')
    source = (OUT / 'source-silver.dll').read_bytes()
    silver = next(r for r in manifest['files'] if r['path'] == 'silver.dll')
    if sha(source) != SOURCE_SHA or silver['sha256'] != SOURCE_SHA or silver['size'] != len(source):
        raise ValueError('Hosted Silver differs from the patch source')
    built = patch(source)
    # Launcher adapters (scope fog, grenades, flame, rain, contracts) bind only when
    # their Silver regions are unchanged; never publish one that breaks them.
    require_compatible(built)
    payload = {'silver.dll': built}
    records = [dict(path='silver.dll', size=len(built), sha256=sha(built), seed=False)]
    existing = {r['path'] for r in manifest['files']}
    assets = load_assets(ASSET_MANIFEST)['assets']
    if len(assets) != EXPECTED_ASSETS:
        raise ValueError('Unexpected font asset set')
    for asset in assets:
        if asset['path'] in existing:
            raise ValueError(f'Font asset already published: {asset["path"]}')
        raw = (ASSET_MANIFEST.parent / asset['path']).read_bytes()
        records.append(dict(path=asset['path'], size=len(raw), sha256=sha(raw), seed=False))
        payload[asset['path']] = raw
    changed = {r['path']: r for r in records}
    manifest['version'] = VERSION
    # The replaced Silver record keeps its position; new font files are appended.
    manifest['files'] = [changed.pop(r['path'], r) for r in manifest['files']] + list(changed.values())
    new = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return old, new, records, payload


def package(payload: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as archive:
        for name in sorted(payload):
            archive.writestr(zipfile.ZipInfo(name, (2026, 11, 20, 0, 0, 0)), payload[name])
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
changed={r['path']:r for r in b['files'] if before_records.get(r['path'])!=r}
assert len(changed)==p['count'] and 'silver.dll' in changed and before_records['silver.dll']['sha256']==p['source_silver']
for name,r in changed.items():
 q=PurePosixPath(name)
 assert '..' not in q.parts and not q.is_absolute() and set(r)=={'path','size','sha256','seed'} and r['seed'] is False
 assert name=='silver.dll' or name not in before_records and (
  name.startswith('base/ui-hd/fonts/plexc-') and q.suffix=='.png' or name=='base/ui-hd/licenses/IBMPlexSans-OFL.txt'),'Only Silver and Plex font files may change'
raw_package=PACKAGE.read_bytes();assert sha(raw_package)==p['package_sha256']
blobs={}
with zipfile.ZipFile(PACKAGE) as z:
 assert sorted(z.namelist())==sorted(changed)
 for name,r in changed.items():
  raw=z.read(name);assert sha(raw)==r['sha256'] and len(raw)==r['size']
  assert not name.endswith('.png') or raw[:8]==b'\x89PNG\r\n\x1a\n'
  assert name!='silver.dll' or raw[:2]==b'MZ'
  blobs[r['sha256']]=raw

def protected():
 with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=15)) as db:
  assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
  return {t:dict(rows=db.execute('SELECT count(*) FROM '+t).fetchone()[0]) for t in ('accounts','characters','wallets','warehouse_items','clans')}
def service():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState'],text=True).split()
def atomic(target,raw,mode=0o644):
 fd,name=tempfile.mkstemp(prefix='.ui-fonts-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as s:s.write(raw);s.flush();os.fsync(s.fileno())
  os.chmod(name,mode);os.replace(name,target)
 except BaseException:
  if os.path.exists(name):os.unlink(name)
  raise
 d=os.open(target.parent,os.O_RDONLY);os.fsync(d);os.close(d)

assert (LIVE/'manifest.json').read_bytes()==old,'Hosted manifest changed since inspection'
assert (LIVE/'blobs'/p['source_silver']).exists(),'Previous Silver blob must stay available for rollback'
before=dict(service=service(),tables=protected())
existing=sum((LIVE/'blobs'/h).exists() for h in blobs)
if p['action']=='inspect':
 print(json.dumps(dict(passed=True,operation='inspect',remote_mutations=0,changed_records=len(changed),new_blobs=len(blobs)-existing,
  existing_blobs=existing,package_bytes=len(raw_package),before=before)));raise SystemExit
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert (LIVE/'manifest.json').read_bytes()==old
os.umask(0o077)
folder=Path(tempfile.mkdtemp(prefix='tio-before-ui-fonts-plex-',dir='/root'))
with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=15)) as src,closing(sqlite3.connect(folder/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
(folder/'previous-manifest.json').write_bytes(old)
(folder/'receipt.json').write_text(json.dumps(dict(created_utc=datetime.now(timezone.utc).isoformat(),sqlite_integrity='ok',
 previous_manifest_sha256=sha(old),next_manifest_sha256=sha(new),previous_silver=p['source_silver'],before=before),indent=2))
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
print(json.dumps(dict(passed=True,operation='apply',backup=str(folder),blobs_written=written,changed_records=len(changed),
 manifest_sha256=sha(new),version=p['version'],before=before,after=after)))
'''


def remote(action: str, old: bytes, new: bytes, records: list[dict], package_sha: str) -> dict:
    payload = dict(action=action, package=REMOTE_PACKAGE, package_sha256=package_sha,
                   before_manifest=base64.b64encode(old).decode(), after_manifest=base64.b64encode(new).decode(),
                   before_sha256=sha(old), after_sha256=sha(new), previous_version=PREVIOUS_VERSION,
                   version=VERSION, count=len(records), source_silver=SOURCE_SHA)
    script = 'PAYLOAD=' + repr(base64.b64encode(json.dumps(payload).encode()).decode()) + '\n' + REMOTE
    result = subprocess.run(SSH + ['python3 -'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=900)
    if result.returncode:
        raise RuntimeError('Remote ' + action + ' failed: ' + (result.stderr.strip().splitlines() or ['?'])[-1])
    return json.loads(result.stdout)


def verify(new: bytes, records: list[dict]) -> dict:
    checks = {}
    for index, origin in enumerate(ORIGINS):
        try:
            raw = fetch(origin + 'manifest.json', verify_tls=index == 0)
        except Exception as error:  # an unreachable origin is reported, not hidden
            checks[origin] = dict(error=type(error).__name__)
            continue
        ok = raw == new
        blobs = sum(sha(fetch(origin + 'blobs/' + r['sha256'], verify_tls=index == 0)) == r['sha256']
                    for r in records) if ok else 0
        checks[origin] = dict(manifest_exact=ok, blobs_verified=blobs, blobs_expected=len(records))
    if not any(c.get('manifest_exact') and c['blobs_verified'] == c['blobs_expected'] for c in checks.values()):
        raise RuntimeError(f'HTTPS verification failed: {checks}')
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'apply', 'verify'))
    args = parser.parse_args()
    old, new, records, payload = candidate()
    (OUT / 'manifest-after.json').write_bytes(new)
    if args.mode == 'verify':
        result = dict(version=VERSION, manifest_sha256=sha(new), https=verify(new, records))
    else:
        archive = package(payload)
        local = OUT / 'package.zip'
        local.write_bytes(archive)
        sent = subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', str(local), 'tio:' + REMOTE_PACKAGE],
                              capture_output=True, timeout=900)
        if sent.returncode:
            raise RuntimeError('Package upload failed')
        result = remote(args.mode, old, new, records, sha(archive))
        local.unlink()
    (OUT / f'publication-{args.mode}.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result)[:2000])


if __name__ == '__main__':
    main()
