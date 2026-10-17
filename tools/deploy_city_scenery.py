"""Scoped server-only TrueSkill whole-map update; preserve all hosted player rows."""
import base64,io,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote
from tools.deploy_throwable_effects import VALIDATE
FOLDER=ROOT/'reports/city-scenery'
NAMES=('config/battle_map_profiles.json','config/arena_fragments.json')

DEPLOY=r'''
import pathlib,json,sys,hashlib,sqlite3,subprocess,tempfile,shutil,os
from contextlib import closing
d=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator');live=pathlib.Path('/var/www/tio-client/updates');path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
sha=lambda b:hashlib.sha256(b).hexdigest()
for n,h in d['expected'].items():
 p=root/n;assert (sha(p.read_bytes()) if p.exists() else None)==h,'Hosted source changed: '+n
assert (live/'manifest.json').read_text()==d['manifest'],'Client release changed'
m=json.loads(d['manifest'])
for n,h in d['resources'].items():
 row=next(r for r in m['files'] if r['path']==n)
 assert row['sha256']==h and sha((live/'blobs'/h).read_bytes())==h,'Original client dependency changed: '+n
def idle():
 with closing(sqlite3.connect(path)) as db:
  for t in ('battle_checkpoints','battle_settlement_jobs'):assert db.execute('SELECT count(*) FROM '+t).fetchone()[0]==0,'Active battles; defer update'
def fingerprint():
 with closing(sqlite3.connect(path)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:sha(repr(sorted(map(repr,db.execute('SELECT * FROM "'+t+'"').fetchall()))).encode()) for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def backup_db():
 with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(backup/path.name)) as dst:src.backup(dst)
 (backup/path.name).chmod(0o600)
idle();backup=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-city-scenery-',dir='/root'));backup.chmod(0o700)
backup_db();shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml');(backup/'server.toml').chmod(0o600)
shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
shutil.copy2(live/'manifest.json',backup/'manifest.json')
for n in d['sources']:
 if (root/n).exists():
  dest=backup/'code'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,dest)
idle();subprocess.run(['systemctl','stop','tio-server'],check=True)
try:
 idle();backup_db();before=fingerprint()
 for n,text in d['sources'].items():
  target=root/n;stage=target.with_name(target.name+'.contest-new')
  with stage.open('w',encoding='utf-8') as f:f.write(text);f.flush();os.fsync(f.fileno())
  stage.chmod(0o644);stage.replace(target)
 check=subprocess.run(['runuser','-u','tio','--',str(root/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check'],cwd=root,text=True,capture_output=True)
 assert check.returncode==0,check.stderr
 assert fingerprint()==before,'Hosted saves changed during update'
except BaseException:
 for n,h in d['expected'].items():
  if h is None:
   if (root/n).exists():(root/n).unlink()
  else:shutil.copy2(backup/'code'/n,root/n)
 raise
finally:subprocess.run(['systemctl','start','tio-server'],check=True)
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
result=dict(backup=str(backup),service='active',database_rows_preserved=True,preflight_passed=True,
 sources={n:sha((root/n).read_bytes()) for n in d['sources']},client_release_unchanged=True,graphical_clients_used=False)
(backup/'receipt.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
'''


def payload():
    old=json.loads((FOLDER/'inspection.json').read_text(encoding='utf-8'))
    return dict(expected={n:old['sources'][n]['sha256'] if n in old['sources'] else None for n in NAMES},
        sources={n:((FOLDER/'server-candidate'/n) if (FOLDER/'server-candidate'/n).exists() else ROOT/n).read_text(encoding='utf-8') for n in NAMES},manifest=old['manifest'],
        resources=json.loads((FOLDER/'resource-proof.json').read_text())['original_dependencies'])


if __name__=='__main__':
    data=payload()
    if sys.argv[1]=='validate':
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('tests/__init__.py','')
            for p in (ROOT/'tests').glob('*.py'):z.write(p,'tests/'+p.name)
        data.update(tests=base64.b64encode(buf.getvalue()).decode(),modules=['test_city_scenery','test_map_generation','test_arena_map','test_cities','test_city_ground_brushes','test_contest_maps'])
        code=VALIDATE.replace("assert hashlib.sha256((root/n).read_bytes()).hexdigest()==digest", "assert (hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).exists() else None)==digest")
        # Hosted PBKDF2 fixture creation is slower than this workstation.
        # Start the isolated suite without tying its duration to SSH's timeout.
        code=code.split('result=subprocess.run(')[0]+r'''
worker=stage/'run_tests.py'
worker.write_text("import subprocess,json,pathlib,os\n"+
 "r=subprocess.run("+repr([str(root/'.venv/bin/python'),'-m','unittest',*data['modules']])+",cwd="+repr(str(stage))+",text=True,capture_output=True,timeout=300,env={**os.environ,'PYTHONPATH':"+repr(str(stage)+':'+str(stage/'tests'))+"})\n"+
 "pathlib.Path("+repr(str(stage/'test-result.json'))+").write_text(json.dumps(dict(passed=r.returncode==0,stage="+repr(str(stage))+",output=r.stderr[-15000:],hosted_database_used=False)))\n")
subprocess.Popen([str(root/'.venv/bin/python'),str(worker)],cwd=stage,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
print(json.dumps(dict(pending=True,stage=str(stage))))
'''
        result=remote(code,data);name='pending-tests.json'
    elif sys.argv[1]=='check':
        pending=json.loads((FOLDER/'pending-tests.json').read_text())
        result=remote("import json,sys,pathlib;d=json.load(sys.stdin);p=pathlib.Path(d['stage'])/'test-result.json';print(p.read_text() if p.exists() else json.dumps({'pending':True}))",pending)
        name='pending-check.json' if result.get('pending') else 'remote-tests.json'
    else:
        assert sys.argv[1]=='deploy'
        assert json.loads((FOLDER/'remote-tests.json').read_text())['passed']
        assert json.loads((FOLDER/'native.json').read_text())['passed']
        result=remote(DEPLOY,data);name='deployment.json'
    (FOLDER/name).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
