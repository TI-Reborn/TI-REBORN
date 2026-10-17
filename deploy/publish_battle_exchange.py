"""Publish the checked client blob, then atomically switch the launcher manifest.

No game service restart; back up hosted DB/config and prior client before publish.
"""
from contextlib import closing
import hashlib,json,shutil,sqlite3,tempfile
from pathlib import Path


def main():
    stage=Path('/root/tio-battle-exchange-20260929');live=Path('/var/www/tio-client/updates')
    old_raw=(live/'manifest.json').read_bytes()
    assert old_raw==(stage/'previous-manifest.json').read_bytes(),'Published manifest changed'
    old=json.loads(old_raw);new=json.loads((stage/'manifest.json').read_bytes())
    assert old['version']=='2026.09.29.2' and new['version']=='2026.09.29.3'
    assert len(old['files'])==len(new['files'])
    changed=[]
    for a,b in zip(old['files'],new['files']):
        assert a['path']==b['path']
        if a!=b:changed.append(b['path'])
    assert changed==['silver.dll']
    previous=next(r for r in old['files'] if r['path']=='silver.dll')
    record=next(r for r in new['files'] if r['path']=='silver.dll')
    assert not record['seed']
    blob=stage/'blobs'/record['sha256'];raw=blob.read_bytes()
    assert len(raw)==record['size'] and hashlib.sha256(raw).hexdigest()==record['sha256']
    backup=Path(tempfile.mkdtemp(prefix='tio-before-battle-exchange-client-',dir='/root'))
    shutil.copy2(live/'manifest.json',backup/'manifest.json')
    shutil.copy2(live/'blobs'/previous['sha256'],backup/'silver.dll')
    shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
    with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
        src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    target=live/'blobs'/record['sha256']
    if target.exists():assert target.read_bytes()==raw
    else:
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.kit-',delete=False) as f:f.write(raw);pending=Path(f.name)
        pending.chmod(0o644);pending.replace(target)
    with tempfile.NamedTemporaryFile(dir=live,prefix='.kit-manifest-',delete=False) as f:
        f.write((stage/'manifest.json').read_bytes());pending=Path(f.name)
    pending.chmod(0o644);pending.replace(live/'manifest.json')
    report={'version':new['version'],'backup':str(backup),'changed':changed,'sha256':record['sha256'],'server_restarted':False,'database_written':False}
    (backup/'publication.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
