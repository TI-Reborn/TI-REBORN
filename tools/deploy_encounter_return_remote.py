"""Candidate checks and guarded four-file hosted overlay; never upload a DB."""
from pathlib import Path
from contextlib import closing
import hashlib,json,shutil,sqlite3,subprocess,tarfile,tempfile,time
ROOT=Path('/opt/tio-emulator');DB=Path('/var/lib/tio-server/reservation.sqlite3')
LIVE=Path('/var/www/tio-client/updates/manifest.json')
NAMES={'tio/locations.py','tio/world_encounters.py','tio/battle_rewards.py','tio/arena_service.py'}

def run(*args):return subprocess.check_output(args,text=True,cwd=ROOT).strip()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def extract(archive,target):
    with tarfile.open(archive) as tar:
        assert all(m.isfile() and (target/m.name).resolve().is_relative_to(target) for m in tar.getmembers())
        tar.extractall(target,filter='data')
def rows():
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as db:
        return {n:sorted(repr(row) for row in db.execute('SELECT * FROM "'+n.replace('"','""')+'"'))
                for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def idle():
    assert not run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'),'Players connected'
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('SELECT 1 FROM battle_checkpoints').fetchone(),'Unfinished hosted battle'
        assert not db.execute('SELECT 1 FROM battle_settlement_jobs').fetchone(),'Pending settlement'

def main():
    stage=Path(tempfile.mkdtemp(prefix='tio-encounter-return-stage-',dir='/root'))
    extract('/root/tio-encounter-return-patch.tar.gz',stage)
    manifest=json.loads((stage/'manifest.json').read_text());assert set(manifest)==NAMES
    old=LIVE.read_bytes();assert old==(stage/'previous-client-manifest.json').read_bytes()
    for name,record in manifest.items():
        assert sha(ROOT/name)==record['before'] and sha(stage/name)==record['after'],name
    candidate=Path(tempfile.mkdtemp(prefix='tio-encounter-return-candidate-',dir='/root'))
    shutil.copytree(ROOT,candidate,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.venv','__pycache__','*.pyc'))
    for name in manifest:shutil.copy2(stage/name,candidate/name)
    extract('/root/tio-encounter-return-tests.tar.gz',candidate)
    for pattern in ('test_world_encounters.py','test_forest_encounters.py','test_cities.py'):
        p=subprocess.run([str(ROOT/'.venv/bin/python'),'-m','unittest','discover','-s','tests','-p',pattern,'-v'],cwd=candidate,capture_output=True,text=True)
        print(p.stdout,flush=True);print(p.stderr,flush=True);assert p.returncode==0,'Candidate tests failed'
    idle();assert run('systemctl','is-active','tio-server')=='active'
    backup=Path(tempfile.mkdtemp(prefix='tio-before-encounter-return-',dir='/root'))
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'reservation-live.sqlite3')) as target:
        source.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
    shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
    (backup/'client-manifest.json').write_bytes(old)
    with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
        for folder in ('tio','server','tools','config','evidence'):tar.add(ROOT/folder,arcname=folder)
    idle();assert LIVE.read_bytes()==old
    for name,record in manifest.items():assert sha(ROOT/name)==record['before'],name
    run('systemctl','stop','tio-server');applied=[]
    try:
        with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'reservation.sqlite3')) as target:
            assert not source.execute('SELECT 1 FROM battle_checkpoints').fetchone()
            assert not source.execute('SELECT 1 FROM battle_settlement_jobs').fetchone()
            source.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        before=rows()
        for name in manifest:
            saved=backup/'files'/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,saved)
            applied.append(name);shutil.copy2(stage/name,ROOT/name);(ROOT/name).chmod(0o644)
        check=run('runuser','-u','tio','--',str(ROOT/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check')
        run('systemctl','start','tio-server');time.sleep(1)
        assert run('systemctl','is-active','tio-server')=='active'
        after=rows();assert all(after.get(n)==records for n,records in before.items())
        assert all(not records for n,records in after.items() if n not in before)
        assert LIVE.read_bytes()==old
        report=dict(backup=str(backup),service='active',preflight=check,candidate_tests=32,
                    candidate=str(candidate),existing_tables_unchanged=len(before),client_manifest_unchanged=True,
                    database_uploaded=False,files={n:sha(ROOT/n) for n in manifest})
        (backup/'deployment.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    except BaseException:
        run('systemctl','stop','tio-server')
        for name in applied:shutil.copy2(backup/'files'/name,ROOT/name)
        run('systemctl','start','tio-server');raise

if __name__=='__main__':main()
