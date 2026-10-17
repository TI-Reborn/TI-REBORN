"""Guarded hosted update: remote DB/code/config/client backups, no local saves."""
from pathlib import Path
from contextlib import closing
import hashlib,json,shutil,sqlite3,subprocess,tarfile,tempfile,time
ROOT=Path('/opt/tio-emulator');DB=Path('/var/lib/tio-server/reservation.sqlite3')
LIVE=Path('/var/www/tio-client/updates')

def run(*args):return subprocess.check_output(args,text=True,cwd=ROOT).strip()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
def rows():
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as db:
        return {name:sorted(repr(row) for row in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'))
                for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def main():
    stage=Path(tempfile.mkdtemp(prefix='tio-reservation-textures-stage-',dir='/root'))
    with tarfile.open('/root/tio-reservation-textures-patch.tar.gz') as tar:
        for member in tar.getmembers():
            if not member.isfile() or not (stage/member.name).resolve().is_relative_to(stage):raise RuntimeError('Unsafe patch path')
        tar.extractall(stage,filter='data')
    manifest=json.loads((stage/'manifest.json').read_text())
    for name,record in manifest.items():
        assert sha(ROOT/name)==record['before'],f'Hosted file changed: {name}'
        assert sha(stage/name)==record['after'],f'Patch file changed: {name}'
    old=(LIVE/'manifest.json').read_bytes()
    assert old==(stage/'client/previous-manifest.json').read_bytes(),'Published client changed'
    assert not run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'),'Players connected; deployment postponed'
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('SELECT 1 FROM battle_checkpoints').fetchone(),'Unfinished hosted battle'
        assert not db.execute('SELECT 1 FROM battle_settlement_jobs').fetchone(),'Pending hosted settlement'
    backup=Path(tempfile.mkdtemp(prefix='tio-before-reservation-textures-',dir='/root'))
    # Make the required consistent remote DB backup before stopping/changing service.
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation-live.sqlite3')) as dst:src.backup(dst)
    shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
    shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
    (backup/'client-manifest.json').write_bytes(old)
    with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
        for folder in ('tio','server','tools','config','evidence'):tar.add(ROOT/folder,arcname=folder)
    run('systemctl','stop','tio-server');applied=[]
    try:
        with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
            assert not src.execute('SELECT 1 FROM battle_checkpoints').fetchone(),'Battle appeared during shutdown'
            src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        before=rows()
        for name in manifest:
            target=ROOT/name;saved=backup/'files'/name
            if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            applied.append(name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/name,target);target.chmod(0o644)
        new=json.loads((stage/'client/manifest.json').read_text())
        for record in new['files']:
            blob=stage/'client/blobs'/record['sha256']
            if not blob.exists():continue
            assert sha(blob)==record['sha256'] and blob.stat().st_size==record['size']
            target=LIVE/'blobs'/record['sha256']
            if target.exists():assert sha(target)==record['sha256']
            else:shutil.copyfile(blob,target);target.chmod(0o644)
        check=run('runuser','-u','tio','--',str(ROOT/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check')
        temporary=LIVE/'manifest-reservation-textures.new';temporary.write_bytes((stage/'client/manifest.json').read_bytes());temporary.chmod(0o644);temporary.replace(LIVE/'manifest.json')
        run('systemctl','start','tio-server');time.sleep(1)
        assert run('systemctl','is-active','tio-server')=='active'
        after=rows();assert all(after.get(name)==records for name,records in before.items()),'Existing hosted player rows changed'
        assert all(not records for name,records in after.items() if name not in before),'Unexpected seeded local data'
        report=dict(backup=str(backup),service='active',preflight=check,client_version=new['version'],existing_tables_unchanged=len(before),
                    files={name:sha(ROOT/name) for name in manifest},client_manifest_sha=sha(LIVE/'manifest.json'))
        (backup/'deployment.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    except BaseException:
        run('systemctl','stop','tio-server')
        for name in applied:
            saved=backup/'files'/name
            if saved.exists():shutil.copy2(saved,ROOT/name)
            else:(ROOT/name).unlink(missing_ok=True)
        temporary=LIVE/'manifest-reservation-rollback.new';temporary.write_bytes(old);temporary.replace(LIVE/'manifest.json')
        run('systemctl','start','tio-server');raise

if __name__=='__main__':main()
