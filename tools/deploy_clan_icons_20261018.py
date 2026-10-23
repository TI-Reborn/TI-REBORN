"""Validate the scoped native crest upload against actual hosted sources."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/clan-icons-20261018';WORK=ROOT/'work/clan-icons-20261018'
REMOTE=r'''
import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
root=Path('/opt/tio-emulator');sha=lambda b:hashlib.sha256(b).hexdigest()
folder=Path('/root/clan-icons-20261018');folder.mkdir(exist_ok=True)
baseline={}
for name,entry in request['files'].items():
 assert sha((root/name).read_bytes())==entry['before']
 assert sha(base64.b64decode(entry['raw']))==entry['after'];baseline[name]=entry['before']
(folder/'baseline.json').write_text(json.dumps(baseline))
if request['mode']=='validate':
 stage=Path(tempfile.mkdtemp(prefix='tio-clan-icons-check-',dir='/opt'))
 for n in ('server','tio','tools','config','evidence'):shutil.copytree(root/n,stage/n,ignore=shutil.ignore_patterns('__pycache__'))
 for name,entry in request['files'].items():(stage/name).write_bytes(base64.b64decode(entry['raw']))
 with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request['tests']))) as tar:tar.extractall(stage,filter='data')
 runner="""
import json,sys,unittest
loader=unittest.TestLoader();suite=unittest.TestSuite(loader.loadTestsFromName(n) for n in MODULES)
class Results(unittest.TextTestResult):
 def addFailure(self,t,e):super().addFailure(t,e)
result=unittest.TextTestRunner(verbosity=0,resultclass=Results).run(suite)
print(json.dumps(dict(tests=result.testsRun,failed=sorted(t.id() for t,e in result.failures+result.errors),skipped=[dict(test=t.id(),reason=r) for t,r in result.skipped])))
"""
 def check(modules):
  run=subprocess.run([str(root/'.venv/bin/python'),'-c','MODULES='+repr(modules)+'\n'+runner],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=240)
  assert run.returncode==0,run.stderr[-1000:]
  return json.loads(run.stdout),run.stderr
 # Control run uses unchanged hosted code and exactly the same test resources.
 for name in request['files']:shutil.copyfile(root/name,stage/name)
 control,control_log=check([n for n in request['modules'] if n!='test_clan_icon_upload'])
 for name,entry in request['files'].items():(stage/name).write_bytes(base64.b64decode(entry['raw']))
 candidate,candidate_log=check(request['modules'])
 introduced=set(candidate['failed'])-set(control['failed'])
 result=dict(passed=not introduced and candidate['tests']==control['tests']+4,hashes={n:v['after'] for n,v in request['files'].items()},stage=str(stage),control=control,candidate=candidate,new_failures=sorted(introduced),log=candidate_log,isolated_database=True)
 (folder/'validation.json').write_text(json.dumps(result));print(json.dumps(result))
else:
 validation=json.loads((folder/'validation.json').read_text());assert validation['passed'] and validation['hashes']=={n:v['after'] for n,v in request['files'].items()}
 manifest={n:dict(before=v['before'],after=v['after']) for n,v in request['files'].items()}
 with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
  for n,raw in [(n,base64.b64decode(v['raw'])) for n,v in request['files'].items()]+[('manifest.json',json.dumps(manifest).encode())]:
   entry=tarfile.TarInfo(n);entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
 sys.argv=['deployer','--archive',str(folder/'patch.tar.gz'),'--sha256',sha((folder/'patch.tar.gz').read_bytes()),'--baseline',str(folder/'baseline.json'),'--backup','/root/tio-before-game-operations-clan-icons-20261018','--scope','clan-icons']
 if request['maintenance_restart']:sys.argv.append('--maintenance-restart')
 exec(compile(request['deployer'],'clan-icons-scoped-deployer','exec'),{'__name__':'__main__'})
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));p.add_argument('--maintenance-restart',action='store_true');args=p.parse_args()
 review=json.loads((OUT/'server-review.json').read_text());files={n:dict(before=v['before'],after=v['after'],raw=base64.b64encode((WORK/'candidate'/n).read_bytes()).decode()) for n,v in review.items()}
 request=dict(mode=args.mode,files=files,maintenance_restart=args.maintenance_restart,deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text())
 if args.mode=='validate':
  buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w:gz') as tar:
   tar.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
   tar.add(ROOT/'evidence/clan_crest_native.json',arcname='evidence/clan_crest_native.json')
  request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules=['test_clan_icon_upload','test_clan_crests','test_clans','test_clan_benefits','test_alliance_crests','test_clan_gameplay','test_clan_benefits_integration','test_shop_clan_benefits','test_clan_crest_gateway','test_clan_rating_crests','test_assault_interface_integration'])
 r=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=300)
 if r.returncode:raise RuntimeError(r.stderr[-1800:])
 value=json.loads(r.stdout);(OUT/('remote-checks.json' if args.mode=='validate' else 'deployment.json')).write_text(json.dumps(value,indent=2));print(json.dumps({k:v for k,v in value.items() if k!='log'}))
if __name__=='__main__':main()
