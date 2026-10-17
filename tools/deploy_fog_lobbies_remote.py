"""Run on the known hosting target with the narrowly scoped patch archive."""
from pathlib import Path
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

ROOT=Path('/opt/tio-emulator')
DB=Path('/var/lib/tio-server/reservation.sqlite3')

def command(*args): return subprocess.run(args,check=True,capture_output=True,text=True,cwd=ROOT).stdout.strip()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
def rows(path):
    with closing(sqlite3.connect(f'file:{path}?mode=ro',uri=True)) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {n:sorted(repr(r) for r in db.execute('SELECT * FROM "'+n.replace('"','""')+'"')) for n in names}

def main():
    archive=Path('/root/tio-fog-lobbies-patch.tar.gz')
    stage=Path(tempfile.mkdtemp(prefix='tio-fog-lobbies-stage-',dir='/root'))
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not (stage/member.name).resolve().is_relative_to(stage):
                raise RuntimeError('Unsafe patch member')
        tar.extractall(stage,filter='data')
    manifest=json.loads((stage/'manifest.json').read_text())
    for name,hashes in manifest.items():
        assert sha(ROOT/name)==hashes['before'],f'Remote changed: {name}'
        assert sha(stage/name)==hashes['after'],f'Patch changed: {name}'
    connections=command('ss','-Htn','state','established','( sport = :28512 or sport = :28513 )')
    if connections: raise RuntimeError('Active gameplay connections; update postponed')
    backup=Path(tempfile.mkdtemp(prefix='tio-before-fog-lobbies-',dir='/root'))
    command('systemctl','stop','tio-server')
    applied=[]
    try:
        with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as src, closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
            src.backup(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        before=rows(DB)
        shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
        shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
        with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
            for folder in ('tio','config','tools','server'):
                tar.add(ROOT/folder,arcname=folder)
        for name in manifest:
            old=ROOT/name
            if old.exists():
                target=backup/'files'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,target)
            applied.append(name)
            old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/name,old);old.chmod(0o644)
        check=command('runuser','-u','tio','--',str(ROOT/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check')
        command('systemctl','start','tio-server')
        assert command('systemctl','is-active','tio-server')=='active'
        after=rows(DB)
        assert all(after.get(name)==records for name,records in before.items()),'Existing rows changed during deployment'
        assert all(not records for name,records in after.items() if name not in before),'Unexpected seeded player data'
        report={'backup':str(backup),'preflight':check,'service':'active','all_existing_tables_unchanged':len(before),
                'files':{n:sha(ROOT/n) for n in manifest}}
        (backup/'deployment.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    except BaseException:
        command('systemctl','stop','tio-server')
        for name in applied:
            saved=backup/'files'/name
            if saved.exists():shutil.copy2(saved,ROOT/name)
            else:(ROOT/name).unlink(missing_ok=True)
        command('systemctl','start','tio-server')
        raise

if __name__=='__main__': main()
