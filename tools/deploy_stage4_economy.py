"""Guarded code-only economy deployment; never uploads or restores player data."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/stage4-economy'
ALLOWED = {'tio/wallets.py', 'tio/battle_rewards.py', 'tio/reward_policy.py',
           'tio/ranks.py', 'tio/level_progression.py', 'config/level_progression.json',
           'server/team_arena.py', 'tools/loopback_exchange.py'}
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=15', 'root@185.184.42.88']
INSPECT = r'''
from pathlib import Path
import hashlib,json,sys
p=json.load(sys.stdin);root=Path('/opt/tio-emulator')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
print(json.dumps({n:{'sha256':sha(root/n),'source':(root/n).read_text() if (root/n).is_file() else None} for n in p['files']}))
'''
DEPLOY = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,time
os.umask(0o077)
p=json.load(sys.stdin);root=Path('/opt/tio-emulator');dbpath=Path('/var/lib/tio-server/reservation.sqlite3')
allowed={'tio/wallets.py','tio/battle_rewards.py','tio/reward_policy.py','tio/ranks.py','tio/level_progression.py','config/level_progression.json','server/team_arena.py','tools/loopback_exchange.py'}
if not p['files'] or not set(p['files'])<=allowed:raise ValueError('Unexpected economy files')
lock=open('/root/.tio-stage4-economy.lock','a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def run(*args):return subprocess.run(args,cwd=root,text=True,capture_output=True,check=True,timeout=60).stdout.strip()
def state(name):return run('systemctl','show',name,'-p','MainPID','-p','ActiveState','-p','NRestarts','-p','ExecMainStatus')
def fingerprint(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Database integrity failed')
        out={}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            rows=sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'))
            out[name]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
        return out
def idle_rows():
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
        for name in ('battle_checkpoints','battle_settlement_jobs'):
            if db.execute('SELECT count(*) FROM '+name).fetchone()[0]:raise RuntimeError('Unfinished battle state; deployment postponed')
def idle():
    if run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'):
        raise RuntimeError('Active game connections; deployment postponed')
    idle_rows()
def atomic(raw,target):
    old=target.stat() if target.exists() else None
    descriptor,name=tempfile.mkstemp(prefix='.'+target.name+'.stage4-',dir=target.parent)
    pending=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        pending.chmod(old.st_mode & 0o777 if old else 0o644)
        if old:os.chown(pending,old.st_uid,old.st_gid)
        pending.replace(target)
    finally:pending.unlink(missing_ok=True)
complete=Path(p['complete_backup'])
if complete.parent!=Path('/root') or not complete.name.startswith('tio-before-site-backups-'):raise ValueError('Invalid private backup path')
for name,expected in p['complete_backup_files'].items():
    if Path(name).name!=name or sha(complete/name)!=expected:raise RuntimeError('Complete pre-update backup changed')
for name,expected in p['guards'].items():
    if sha(Path(name))!=expected:raise RuntimeError('Hosted operational/client guard changed')
candidate={}
for name,entry in p['files'].items():
    if sha(root/name)!=entry['before']:raise RuntimeError('Remote source changed: '+name)
    raw=base64.b64decode(entry['content'],validate=True)
    if hashlib.sha256(raw).hexdigest()!=entry['after']:raise RuntimeError('Candidate checksum mismatch')
    if name.endswith('.py'):compile(raw,name,'exec')
    else:json.loads(raw)
    candidate[name]=raw
if run('systemctl','is-active','tio-server')!='active':raise RuntimeError('Game service not active')
idle()
other_services={n:state(n) for n in ('tio-game-api','tio-portal')}
backup=Path(tempfile.mkdtemp(prefix='tio-before-stage4-economy-',dir='/root'))
for name in candidate:
    old=root/name
    if old.exists():
        saved=backup/'files'/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,saved)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
idle()
applied=[]
restarted=False
try:
    run('systemctl','stop','tio-server')
    # Close the gap between the last socket check and stop. A battle created
    # in that interval must keep its original rules/configuration digest.
    idle_rows()
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'reservation.sqlite3')) as destination:
        source.backup(destination)
    before=fingerprint(dbpath)
    if fingerprint(backup/'reservation.sqlite3')!=before:raise RuntimeError('Stopped database snapshot mismatch')
    for name,raw in sorted(candidate.items()):
        if sha(root/name)!=p['files'][name]['before']:raise RuntimeError('Remote source changed while preparing')
        applied.append(name);atomic(raw,root/name)
    preflight=run('runuser','-u','tio','--',str(root/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check')
    if fingerprint(dbpath)!=before:raise RuntimeError('Database changed during preflight')
    restarted=True
    run('systemctl','start','tio-server')
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        try:
            active=run('systemctl','is-active','tio-server')
            listeners=run('ss','-Hltn','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
            if active=='active' and all(':'+str(port) in listeners for port in (28512,28513,29512,29513)):break
        except subprocess.CalledProcessError:pass
        time.sleep(.2)
    else:raise RuntimeError('Hosted listeners failed to become ready')
    after=fingerprint(dbpath)
    if any(after.get(n)!=entry for n,entry in before.items()):raise RuntimeError('Existing hosted tables changed across restart')
    if any(entry['rows'] for n,entry in after.items() if n not in before):raise RuntimeError('Unexpected player rows after restart')
    if {n:state(n) for n in other_services}!=other_services:raise RuntimeError('Portal/API identity changed')
    if any(sha(Path(n))!=value for n,value in p['guards'].items()):raise RuntimeError('Operational/client guard changed')
    parity=all(sha(root/n)==p['files'][n]['after'] for n in candidate)
    if not parity:raise RuntimeError('Installed source parity failed')
    result=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),backup=str(backup),complete_backup=str(complete),
        service='active',preflight=preflight,accounts_preserved=before['accounts']['rows'],wallets_preserved=before['wallets']['rows'],
        all_existing_tables_unchanged=len(before),tables_before=before,tables_after=after,
        source_parity=parity,source_sha256={n:sha(root/n) for n in candidate},
        service_state=state('tio-server'),other_services_unchanged=other_services,
        local_player_data_uploaded=False,database_restored=False)
    (backup/'deployment.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
except BaseException as failure:
    if restarted:
        try:idle()
        except BaseException:
            # Retain the checked candidate under new live battle state. A
            # second restart with the old config digest could quarantine it.
            attention=dict(deployment_complete=False,status='attention',backup=str(backup),
                rollback_deferred=True,reason='New active game/battle state prevents safe code rollback',
                service_state=state('tio-server'),failure_type=type(failure).__name__,
                database_restored=False,local_player_data_uploaded=False)
            (backup/'deployment-attention.json').write_text(json.dumps(attention,indent=2)+'\n')
            print(json.dumps(attention));sys.exit(0)
    run('systemctl','stop','tio-server')
    if restarted:
        try:idle_rows()
        except BaseException:
            run('systemctl','start','tio-server')
            attention=dict(deployment_complete=False,status='attention',backup=str(backup),
                rollback_deferred=True,reason='New stopped battle state prevents safe code rollback',
                service_state=state('tio-server'),failure_type=type(failure).__name__,
                database_restored=False,local_player_data_uploaded=False)
            (backup/'deployment-attention.json').write_text(json.dumps(attention,indent=2)+'\n')
            print(json.dumps(attention));sys.exit(0)
    for name in reversed(applied):
        saved=backup/'files'/name
        if saved.exists():atomic(saved.read_bytes(),root/name)
        else:(root/name).unlink(missing_ok=True)
    run('systemctl','start','tio-server')
    raise
'''


def remote(code, payload):
    result = subprocess.run(SSH+['python3 -c '+shlex.quote(code)], input=json.dumps(payload),
                            text=True, encoding='utf-8', capture_output=True, timeout=240)
    if result.returncode:
        # Remote source/config and native payloads must not escape into diagnostics.
        raise RuntimeError('Economy deployment helper failed; inspect private remote rollback journal')
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','deploy'))
    parser.add_argument('--files',nargs='+')
    args=parser.parse_args()
    path=FOLDER/'deployment-manifest.json'
    if args.action=='prepare':
        files=sorted(set(args.files or ()))
        if not files or not set(files)<=ALLOWED:parser.error('Select only reviewed economy runtime/config files')
        if path.exists():parser.error('Prepared manifest already exists')
        baseline=json.loads((FOLDER/'remote-baseline.json').read_text(encoding='utf-8'))
        complete=json.loads((FOLDER/'pre-update-backup.json').read_text(encoding='utf-8'))
        actual=remote(INSPECT,{'files':files})
        entries={}
        for name in files:
            if actual[name]['source'] is None:raise RuntimeError('Expected hosted source missing')
            saved=FOLDER/'deployment-remote-before'/name;saved.parent.mkdir(parents=True,exist_ok=True)
            saved.write_text(actual[name]['source'],encoding='utf-8',newline='')
            raw=(ROOT/name).read_bytes()
            after=hashlib.sha256(raw).hexdigest()
            if actual[name]['sha256']==after:raise RuntimeError('Unchanged file selected: '+name)
            entries[name]={'before':actual[name]['sha256'],'after':after}
        data={'files':entries,'guards':baseline['guards'],'complete_backup':complete['backup'],
              'complete_backup_files':{n:entry['sha256'] for n,entry in complete['files'].items()}}
        path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'prepared_files':files,'complete_backup':complete['backup']}))
    else:
        target=FOLDER/'deployment.json'
        if target.exists():parser.error('Deployment already recorded')
        data=json.loads(path.read_text(encoding='utf-8'))
        for name,entry in data['files'].items():
            raw=(ROOT/name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['after']:raise RuntimeError('Local candidate changed: '+name)
            entry['content']=base64.b64encode(raw).decode('ascii')
        report=remote(DEPLOY,data)
        target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        if report.get('status')=='attention':
            print(json.dumps(report))
            raise RuntimeError('Candidate retained to preserve new active battle state; see deployment report')
        print(json.dumps({n:report[n] for n in ('timestamp_utc','backup','service','accounts_preserved','wallets_preserved','all_existing_tables_unchanged','source_parity')}))


if __name__=='__main__':main()
