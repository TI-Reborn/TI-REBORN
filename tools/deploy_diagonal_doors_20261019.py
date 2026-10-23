"""Inspect, validate and deploy the single hosted door module with guarded backups."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/diagonal-doors-20261019'
MODULE='tio/battle_doors.py'
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def remote(code,request=None):
    result=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -'],
        input='request='+repr(request)+'\n'+code,capture_output=True,encoding='utf-8',timeout=300)
    if result.returncode:raise RuntimeError(result.stderr[-4000:])
    return json.loads(result.stdout)

def inspect():
    result=remote('''import base64,hashlib,json,sqlite3,subprocess
from pathlib import Path
p=Path('tio/battle_doors.py');raw=p.read_bytes()
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 state={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('accounts','clans','battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')}
print(json.dumps(dict(sha256=hashlib.sha256(raw).hexdigest(),raw=base64.b64encode(raw).decode(),state=state,
 service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
 sockets=subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())))
''')
    (OUT/'server-inspection.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='raw'}))

def run(mode,maintenance_restart=False):
    inspected=json.loads((OUT/'server-inspection.json').read_text())
    raw=(ROOT/MODULE).read_bytes()
    request=dict(mode=mode,before=inspected['sha256'],after=sha(raw),raw=base64.b64encode(raw).decode(),maintenance_restart=maintenance_restart)
    if mode=='validate':
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as tar:
            tar.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
        request['tests']=base64.b64encode(buf.getvalue()).decode()
    else:
        source=(ROOT/'tools/deploy_game_operations_remote.py').read_text()
        request['deployer']=source.replace('KEEP_TABLES=',"SCOPES['diagonal-doors']=frozenset(('tio/battle_doors.py',))\nKEEP_TABLES=")
    result=remote('''import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
root=Path('/opt/tio-emulator');module='tio/battle_doors.py';sha=lambda b:hashlib.sha256(b).hexdigest()
folder=Path('/root/diagonal-doors-20261019');folder.mkdir(exist_ok=True)
assert sha((root/module).read_bytes())==request['before'],'Hosted baseline changed'
raw=base64.b64decode(request['raw']);assert sha(raw)==request['after']
if request['mode']=='validate':
 stage=Path(tempfile.mkdtemp(prefix='tio-diagonal-doors-check-',dir='/opt'))
 for name in ('server','tio','tools','config','evidence'):shutil.copytree(root/name,stage/name,ignore=shutil.ignore_patterns('__pycache__'))
 (stage/module).write_bytes(raw)
 with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request['tests']))) as tar:tar.extractall(stage,filter='data')
 modules=['test_battle_doors','test_battle_screen_fixes','test_dog_abilities','test_visibility','test_battle_events',
  'test_battle_weapon_regressions.BattleWeaponRegressions.test_closed_door_blocks_shots_after_repeated_open_and_close']
 p=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*modules,'-q'],cwd=stage,
  env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=180)
 result=dict(passed=p.returncode==0,sha256=request['after'],stage=str(stage),log=p.stdout+p.stderr,isolated_database=True)
 (folder/'validation.json').write_text(json.dumps(result));print(json.dumps(result))
else:
 validation=json.loads((folder/'validation.json').read_text());assert validation['passed'] and validation['sha256']==request['after']
 baseline={module:request['before']};manifest={module:dict(before=request['before'],after=request['after'])}
 (folder/'baseline.json').write_text(json.dumps(baseline))
 with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
  for name,data in ((module,raw),('manifest.json',json.dumps(manifest).encode())):
   info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
 sys.argv=['deploy','--archive',str(folder/'patch.tar.gz'),'--sha256',sha((folder/'patch.tar.gz').read_bytes()),
  '--baseline',str(folder/'baseline.json'),'--backup','/root/tio-before-game-operations-diagonal-doors-20261019','--scope','diagonal-doors']
 if request['maintenance_restart']:sys.argv.append('--maintenance-restart')
 exec(compile(request['deployer'],'diagonal-door-scoped-deployment','exec'),{'__name__':'__main__'})
''',request)
    (OUT/('remote-checks.json' if mode=='validate' else 'deployment.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result));assert result['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('inspect','validate','deploy'))
    p.add_argument('--maintenance-restart',action='store_true',help='Use only after explicit permission to disconnect idle clients')
    a=p.parse_args();inspect() if a.mode=='inspect' else run(a.mode,a.maintenance_restart)
