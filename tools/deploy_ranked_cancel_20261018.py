"""Validate the scoped native crest upload against actual hosted sources."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/ranked-cancel-20261018';WORK=ROOT/'work/ranked-cancel-20261018'
REMOTE=r'''
import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
root=Path('/opt/tio-emulator');sha=lambda b:hashlib.sha256(b).hexdigest()
folder=Path('/root/ranked-cancel-qa-pool-20261018');folder.mkdir(exist_ok=True)
baseline={}
for name,entry in request['files'].items():
 assert (sha((root/name).read_bytes()) if (root/name).is_file() else None)==entry['before']
 assert sha(base64.b64decode(entry['raw']))==entry['after'];baseline[name]=entry['before']
(folder/'baseline.json').write_text(json.dumps(baseline))
if request['mode']=='validate':
 stage=Path(tempfile.mkdtemp(prefix='tio-ranked-cancel-check-',dir='/opt'))
 for n in ('server','tio','tools','config','evidence'):shutil.copytree(root/n,stage/n,ignore=shutil.ignore_patterns('__pycache__'))
 for name,entry in request['files'].items():(stage/name).write_bytes(base64.b64decode(entry['raw']))
 with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request['tests']))) as tar:tar.extractall(stage,filter='data')
 run=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*request['modules'],'-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=360)
 result=dict(passed=run.returncode==0,hashes={n:v['after'] for n,v in request['files'].items()},stage=str(stage),log=run.stdout+run.stderr,isolated_database=True)
 (folder/'validation.json').write_text(json.dumps(result));print(json.dumps(result))
else:
 validation=json.loads((folder/'validation.json').read_text());assert validation['passed'] and validation['hashes']=={n:v['after'] for n,v in request['files'].items()}
 manifest={n:dict(before=v['before'],after=v['after']) for n,v in request['files'].items()}
 with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
  for n,raw in [(n,base64.b64decode(v['raw'])) for n,v in request['files'].items()]+[('manifest.json',json.dumps(manifest).encode())]:
   entry=tarfile.TarInfo(n);entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
 sys.argv=['deployer','--archive',str(folder/'patch.tar.gz'),'--sha256',sha((folder/'patch.tar.gz').read_bytes()),'--baseline',str(folder/'baseline.json'),'--backup','/root/tio-before-game-operations-ranked-cancel-qa-pool-20261018','--scope','ranked-cancel']
 if request['maintenance_restart']:sys.argv.append('--maintenance-restart')
 exec(compile(request['deployer'],'ranked-cancel-scoped-deployer','exec'),{'__name__':'__main__'})
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));p.add_argument('--maintenance-restart',action='store_true');args=p.parse_args()
 review=json.loads((OUT/'server-review.json').read_text());files={n:dict(before=v['before'],after=v['after'],raw=base64.b64encode((WORK/'candidate'/n).read_bytes()).decode()) for n,v in review.items()}
 request=dict(mode=args.mode,files=files,maintenance_restart=args.maintenance_restart,deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text())
 if args.mode=='validate':
  buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w:gz') as tar:
   tar.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)

  request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules=['test_ranked_cancel','test_ranked.RankedServerTests','test_ranked.RankedWireTests','test_ranked_squads','test_arena_gears','test_team_ranked','test_battle_crash_recovery'])
 r=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=360)
 if r.returncode:raise RuntimeError(r.stderr[-1800:])
 value=json.loads(r.stdout);(OUT/('remote-checks.json' if args.mode=='validate' else 'deployment.json')).write_text(json.dumps(value,indent=2));print(json.dumps({k:v for k,v in value.items() if k!='log'}))
if __name__=='__main__':main()
