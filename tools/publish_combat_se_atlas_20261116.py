"""Publish the Heavy Combat SE atlas rebuilt on its mesh layout (2026.11.15.5 -> 2026.11.16.1).

Replaces exactly two existing client records, base/models/armor_combatse.jpg
and armor_combatse_mask.png (tools/build_combat_se_atlas.py). Every other
record, the news and all other manifest fields stay byte-identical. No code,
configuration, catalog, database or player data is uploaded; silver.dll and
ti.exe are untouched, so launcher native adapters are unaffected.

Same guarded remote path as tools/publish_hd_map_textures_20261114.py:
publication lock, exact inspected manifest, SQLite online backup with
integrity check, previous manifest backup, atomic blob and manifest writes,
service and protected table counts compared before and after.
Old blobs stay in place, so restoring the backed-up manifest rolls back.

Usage: python tools/publish_combat_se_atlas_20261116.py {inspect|apply|verify}
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_combat_se_atlas import SE_ATLAS, SE_MASK  # noqa: E402
from tools.publish_hd_map_textures_20261114 import SSH, package, sha, verify  # noqa: E402

OUT = ROOT/'reports/combat-se-atlas-20261116'
BUILD = ROOT/'work/combat-se-atlas-20261116/out'
PREVIOUS_VERSION, VERSION = '2026.11.15.5', '2026.11.16.1'
MANIFEST_SHA = 'ee5f1dd9120b3c33a4db7fe3e73af73efe0bb2d687011b141d1aba2ee1e3f885'
SOURCE_ATLAS_SHA = '28432bb300423cd234625d636e3d1b4b0db0ba9c977691776164debc169bc4fd'
REPLACED = {'base/models/' + SE_ATLAS: SE_ATLAS, 'base/models/' + SE_MASK: SE_MASK}
REMOTE_PACKAGE = '/root/tio-combat-se-atlas-20261116.zip'


def candidate() -> tuple[bytes, bytes, list[dict], dict[str, bytes]]:
    old = (OUT/'manifest-before.json').read_bytes()
    if sha(old) != MANIFEST_SHA:
        raise ValueError('Inspected hosted manifest changed')
    manifest = json.loads(old)
    if manifest['version'] != PREVIOUS_VERSION:
        raise ValueError('Unexpected previous client version')
    existing = {r['path']: r for r in manifest['files']}
    built = json.loads((BUILD/'combat-se-atlas.json').read_text(encoding='utf-8'))
    source = existing['base/models/armor_combat.jpg']
    if built['source_atlas_sha256'] != SOURCE_ATLAS_SHA or source['sha256'] != SOURCE_ATLAS_SHA:
        raise ValueError('The SE atlas was not derived from the hosted armor_combat.jpg')
    if existing['base/models/armor_combat_mask.png']['sha256'] != built['source_mask_sha256']:
        raise ValueError('The SE mask was not copied from the hosted armor_combat_mask.png')
    records, payload = [], {}
    for path, name in REPLACED.items():
        raw = (BUILD/name).read_bytes()
        if sha(raw) != built['outputs'][name] or path not in existing:
            raise ValueError(f'Built file changed or record missing: {path}')
        if name.endswith('.jpg') and raw[:2] != b'\xff\xd8':
            raise ValueError('SE atlas must stay a plain JPEG like the record it replaces')
        if name.endswith('.png') and raw[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('SE mask must stay a PNG')
        if existing[path]['sha256'] == sha(raw):
            raise ValueError(f'Record already published: {path}')
        records.append(dict(path=path, size=len(raw), sha256=sha(raw), seed=existing[path]['seed']))
        payload[path] = raw
    changed = {r['path']: r for r in records}
    manifest['version'] = VERSION
    manifest['files'] = [changed.get(r['path'], r) for r in manifest['files']]
    new = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return old, new, records, payload


REMOTE = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import base64,fcntl,hashlib,json,os,sqlite3,subprocess,tempfile,zipfile
p=json.loads(base64.b64decode(PAYLOAD))
LIVE=Path('/var/www/tio-client/updates');PACKAGE=Path(p['package']);DB=Path('/var/lib/tio-server/reservation.sqlite3')
sha=lambda b:hashlib.sha256(b).hexdigest()
old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
assert sha(old)==p['before_sha256'] and sha(new)==p['after_sha256']
a,b=json.loads(old),json.loads(new)
assert a['version']==p['previous_version'] and b['version']==p['version']
assert set(a)==set(b) and all(a[k]==b[k] for k in a if k not in ('version','files'))
assert [r['path'] for r in a['files']]==[r['path'] for r in b['files']],'Record set and order must stay'
changed={y['path']:y for x,y in zip(a['files'],b['files']) if x!=y}
assert sorted(changed)==sorted(p['paths']),'Only the SE atlas records may change'
for x in a['files']:
 if x['path'] in changed:assert set(x)==set(changed[x['path']]) and x['seed']==changed[x['path']]['seed']
raw_package=PACKAGE.read_bytes();assert sha(raw_package)==p['package_sha256']
blobs={}
with zipfile.ZipFile(PACKAGE) as z:
 assert sorted(z.namelist())==sorted(changed)
 for name,r in changed.items():
  raw=z.read(name);assert sha(raw)==r['sha256'] and len(raw)==r['size'];blobs[r['sha256']]=raw

def protected():
 with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=15)) as db:
  assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
  return {t:dict(rows=db.execute('SELECT count(*) FROM '+t).fetchone()[0]) for t in ('accounts','characters','wallets','warehouse_items','clans')}
def service():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState'],text=True).split()
def atomic(target,raw,mode=0o644):
 fd,name=tempfile.mkstemp(prefix='.combat-se-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as s:s.write(raw);s.flush();os.fsync(s.fileno())
  os.chmod(name,mode);os.replace(name,target)
 except BaseException:
  if os.path.exists(name):os.unlink(name)
  raise
 d=os.open(target.parent,os.O_RDONLY);os.fsync(d);os.close(d)

assert (LIVE/'manifest.json').read_bytes()==old,'Hosted manifest changed since inspection'
for x in a['files']:
 if x['path'] in changed:assert (LIVE/'blobs'/x['sha256']).is_file(),'Previous blob must stay for rollback'
before=dict(service=service(),tables=protected())
existing=sum((LIVE/'blobs'/h).exists() for h in blobs)
if p['action']=='inspect':
 print(json.dumps(dict(passed=True,operation='inspect',remote_mutations=0,changed_records=len(changed),new_blobs=len(blobs)-existing,
  existing_blobs=existing,package_bytes=len(raw_package),before=before)));PACKAGE.unlink();raise SystemExit
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert (LIVE/'manifest.json').read_bytes()==old
os.umask(0o077)
folder=Path(tempfile.mkdtemp(prefix='tio-before-combat-se-atlas-',dir='/root'))
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
print(json.dumps(dict(passed=True,operation='apply',backup=str(folder),blobs_written=written,changed_records=len(changed),
 manifest_sha256=sha(new),version=p['version'],before=before,after=after)))
'''


def remote(action: str, old: bytes, new: bytes, records: list[dict], package_sha: str) -> dict:
    payload = dict(action=action, package=REMOTE_PACKAGE, package_sha256=package_sha,
                   before_manifest=base64.b64encode(old).decode(), after_manifest=base64.b64encode(new).decode(),
                   before_sha256=sha(old), after_sha256=sha(new), previous_version=PREVIOUS_VERSION,
                   version=VERSION, paths=[r['path'] for r in records])
    script = 'PAYLOAD=' + repr(base64.b64encode(json.dumps(payload).encode()).decode()) + '\n' + REMOTE
    result = subprocess.run(SSH + ['python3 -'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=900)
    if result.returncode:
        raise RuntimeError('Remote ' + action + ' failed: ' + (result.stderr.strip().splitlines() or ['?'])[-1])
    return json.loads(result.stdout)


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
        sent = subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', str(local), 'tio:' + REMOTE_PACKAGE],
                              capture_output=True, timeout=900)
        if sent.returncode:
            raise RuntimeError('Package upload failed')
        result = remote(args.mode, old, new, records, sha(archive))
        local.unlink()
    (OUT/f'publication-{args.mode}.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result)[:2000])


if __name__ == '__main__':
    main()
