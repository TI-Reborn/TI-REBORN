"""Validate the one-file list fix against current hosting, then back up/deploy."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/training-groups-20261018';WORK=ROOT/'work/training-groups-20261018'
REMOTE=r'''
import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
root=Path('/opt/tio-emulator');name='server/training_arena.py';sha=lambda b:hashlib.sha256(b).hexdigest()
current=(root/name).read_bytes();assert sha(current)==request['before']
candidate=base64.b64decode(request['candidate']);assert sha(candidate)==request['after']
folder=Path('/root/training-groups-20261018');folder.mkdir(exist_ok=True)
baseline={name:sha(current)};(folder/'baseline.json').write_text(json.dumps(baseline))
if request['mode']=='validate':
 stage=Path(tempfile.mkdtemp(prefix='tio-training-groups-check-',dir='/opt'))
 for n in ('server','tio','tools','config','evidence'):shutil.copytree(root/n,stage/n,ignore=shutil.ignore_patterns('__pycache__'))
 (stage/name).write_bytes(candidate)
 with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request['tests']))) as tar:tar.extractall(stage,filter='data')
 run=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*request['modules'],'-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=240)
 result=dict(passed=run.returncode==0,candidate_sha256=request['after'],stage=str(stage),log=run.stdout+run.stderr,isolated_database=True)
 (folder/'validation.json').write_text(json.dumps(result));print(json.dumps(result))
else:
 validation=json.loads((folder/'validation.json').read_text());assert validation['passed'] and validation['candidate_sha256']==request['after']
 manifest={name:dict(before=sha(current),after=sha(candidate))}
 with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
  for n,raw in [(name,candidate),('manifest.json',json.dumps(manifest).encode())]:
   entry=tarfile.TarInfo(n);entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
 sys.argv=['deployer','--archive',str(folder/'patch.tar.gz'),'--sha256',sha((folder/'patch.tar.gz').read_bytes()),'--baseline',str(folder/'baseline.json'),'--backup','/root/tio-before-game-operations-training-groups-20261018','--scope','training-counter']
 if request.get('maintenance_restart'):sys.argv.append('--maintenance-restart')
 exec(compile(request['deployer'],'training-scoped-deployer','exec'),{'__name__':'__main__'})
'''

def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));p.add_argument('--maintenance-restart',action='store_true');args=p.parse_args()
 candidate=(WORK/'candidate/server/training_arena.py').read_bytes()
 request=dict(mode=args.mode,before=json.loads((OUT/'baseline.json').read_text())['source_hashes']['server/training_arena.py'],after=hashlib.sha256(candidate).hexdigest(),candidate=base64.b64encode(candidate).decode(),deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text(),maintenance_restart=args.maintenance_restart)
 if args.mode=='validate':
  buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w:gz') as tar:
   tar.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
   tar.add(ROOT/'work/training-base-20261018/candidate/tests/test_training_on_demand.py',arcname='tests/test_training_on_demand.py')
  request['tests']=base64.b64encode(buf.getvalue()).decode()
  request['modules']=['test_training_group_list','test_training_arena','test_training_on_demand','test_assault_interface_integration','test_assault_location_admission','test_assault_public','test_clan_warfare_protocol']
 r=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=300)
 if r.returncode:raise RuntimeError(r.stderr[-2400:])
 value=json.loads(r.stdout);(OUT/('remote-checks.json' if args.mode=='validate' else 'deployment.json')).write_text(json.dumps(value,indent=2));print(json.dumps(value))
if __name__=='__main__':main()
