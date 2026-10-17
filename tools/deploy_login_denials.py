"""Inspect and deploy exactly six authentication files; never upload save data."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/login-incident'
FILES = ('server/auth_errors.py', 'server/accounts.py', 'server/login_guard.py',
         'server/multi.py', 'tio/protocol/login.py', 'tools/loopback_exchange.py')
GUARDS = ('/etc/tio-server/server.toml', '/var/www/tio-client/downloads/TIO-Launcher.exe',
          '/var/www/tio-client/updates/manifest.json')
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=15', 'root@185.184.42.88']

INSPECT = r'''
import hashlib,json,pathlib,sys
p=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
print(json.dumps({'files':{n:{'sha256':sha(root/n),'source':(root/n).read_text() if (root/n).is_file() else None} for n in p['files']},'guards':{n:sha(pathlib.Path(n)) for n in p['guards']}}))
'''

DEPLOY = r'''
from contextlib import closing
from pathlib import Path
import base64,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,time
os.umask(0o077)
p=json.load(sys.stdin);root=Path('/opt/tio-emulator');dbpath=Path('/var/lib/tio-server/reservation.sqlite3')
allowed={'server/auth_errors.py','server/accounts.py','server/login_guard.py','server/multi.py','tio/protocol/login.py','tools/loopback_exchange.py'}
if set(p['files'])!=allowed:raise ValueError('Unexpected authentication patch files')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def run(*args):return subprocess.run(args,cwd=root,text=True,capture_output=True,check=True,timeout=60).stdout.strip()
def fingerprints(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('Database integrity failed')
        result={}
        for (name,) in db.execute("select name from sqlite_master where type='table' order by name"):
            rows=sorted(repr(tuple(r)) for r in db.execute('select * from "'+name.replace('"','""')+'"'))
            result[name]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
        return result
def idle():
    if run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'):
        raise RuntimeError('Active game connections: deployment postponed')
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
        for name in ('battle_checkpoints','battle_settlement_jobs'):
            if db.execute('select count(*) from '+name).fetchone()[0]:raise RuntimeError('Unfinished battle state: deployment postponed')
def atomic(source,target):
    previous=target.stat() if target.exists() else None
    pending=target.with_name(target.name+'.login-denials-pending')
    with pending.open('xb') as out:out.write(source.read_bytes());out.flush();os.fsync(out.fileno())
    pending.chmod(0o644)
    if previous:os.chown(pending,previous.st_uid,previous.st_gid)
    pending.replace(target)
complete=Path(p['complete_backup'])
if complete.parent!=Path('/root') or not complete.name.startswith('tio-before-site-backups-'):raise ValueError('Unexpected complete backup path')
for name,expected in p['complete_backup_files'].items():
    if sha(complete/name)!=expected:raise RuntimeError('Complete backup missing or changed')
for name,entry in p['files'].items():
    if sha(root/name)!=entry['before']:raise RuntimeError('Remote source changed: '+name)
for name,expected in p['guards'].items():
    if sha(Path(name))!=expected:raise RuntimeError('Remote configuration/client changed: '+name)
if run('systemctl','is-active','tio-server')!='active':raise RuntimeError('Service is not active')
idle()
stage=Path(tempfile.mkdtemp(prefix='tio-login-denials-stage-',dir='/root'))
backup=Path(tempfile.mkdtemp(prefix='tio-before-login-denials-',dir='/root'))
for name,entry in p['files'].items():
    raw=base64.b64decode(entry['content'],validate=True)
    if hashlib.sha256(raw).hexdigest()!=entry['after']:raise RuntimeError('Candidate hash mismatch')
    compile(raw,name,'exec')
    target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    if (root/name).exists():
        saved=backup/'files'/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,saved)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
idle();run('systemctl','stop','tio-server')
applied=[]
try:
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dest:source.backup(dest)
    before=fingerprints(dbpath)
    for name in sorted(p['files']):
        atomic(stage/name,root/name);applied.append(name)
    check=run('runuser','-u','tio','--',str(root/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check')
    if fingerprints(dbpath)!=before:raise RuntimeError('Database changed while service stopped')
    run('systemctl','start','tio-server')
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            active=run('systemctl','is-active','tio-server')
            listeners=run('ss','-Hltn','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
            if active=='active' and all(':'+str(port) in listeners for port in (28512,28513,29512,29513)):break
        except subprocess.CalledProcessError:pass
        time.sleep(.2)
    else:raise RuntimeError('Hosted listeners failed to become ready')
    after=fingerprints(dbpath)
    report={'backup':str(backup),'complete_backup':str(complete),'service':'active','preflight':check,
            'database_unchanged_before_restart':True,'tables_preserved_before_restart':len(before),
            'accounts_before':before['accounts']['rows'],'accounts_after':after['accounts']['rows'],
            'changed_tables_after_start':[n for n in before if before[n]!=after.get(n)],
            'source_parity':all(sha(root/n)==entry['after'] for n,entry in p['files'].items()),
            'source_sha256':{n:sha(root/n) for n in p['files']},
            'service_state':run('systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ExecMainStatus')}
    if not report['source_parity'] or before['accounts']!=after['accounts']:raise RuntimeError('Post-start preservation check failed')
    (backup/'deployment.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
except BaseException:
    run('systemctl','stop','tio-server')
    for name in applied:
        saved=backup/'files'/name
        if saved.exists():atomic(saved,root/name)
        else:(root/name).unlink(missing_ok=True)
    run('systemctl','start','tio-server')
    raise
'''

def remote(code, payload):
    result = subprocess.run(SSH+['python3 -c '+shlex.quote(code)],
                            input=json.dumps(payload), text=True, encoding='utf-8',
                            capture_output=True, check=True, timeout=180)
    return json.loads(result.stdout)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','deploy'))
    args=parser.parse_args()
    manifest_path=FOLDER/'login-denials-manifest.json'
    if args.action=='prepare':
        if manifest_path.exists():parser.error('Prepared manifest already exists')
        actual=remote(INSPECT,{'files':FILES,'guards':GUARDS})
        entries={}
        for name in FILES:
            entry=actual['files'][name]
            if entry['source'] is not None:
                target=FOLDER/'remote-before'/name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(entry['source'],encoding='utf-8',newline='')
            raw=(ROOT/name).read_bytes()
            entries[name]={'before':entry['sha256'],'after':hashlib.sha256(raw).hexdigest()}
        manifest_path.write_text(json.dumps({'files':entries,'guards':actual['guards']},indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'prepared_files':len(entries),'baseline_saved':True}))
    else:
        if (FOLDER/'login-denials-deployment.json').exists():parser.error('Deployment already recorded')
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        complete=json.loads((FOLDER/'pre-update-backup.json').read_text(encoding='utf-8'))
        for name,entry in manifest['files'].items():
            raw=(ROOT/name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['after']:raise RuntimeError('Local candidate changed: '+name)
            entry['content']=base64.b64encode(raw).decode('ascii')
        manifest['complete_backup']=complete['backup']
        manifest['complete_backup_files']={n:v['sha256'] for n,v in complete['files'].items()}
        report=remote(DEPLOY,manifest)
        (FOLDER/'login-denials-deployment.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))

if __name__=='__main__':main()
