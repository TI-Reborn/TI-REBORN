"""Validate/deploy exact inspected native Assault4 string ABI correction."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH,REPORT,WORK
REMOTE=r'''
import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
root=Path('/opt/tio-emulator');name=request['name'];sha=lambda b:hashlib.sha256(b).hexdigest()
current=(root/name).read_bytes();assert sha(current)==request['before']
candidate=base64.b64decode(request['candidate']);assert sha(candidate)==request['after']
folder=Path('/root/training-'+request['component']+'-20261018');folder.mkdir(exist_ok=True)
baseline={name:sha(current)};(folder/'baseline.json').write_text(json.dumps(baseline))
if request['mode']=='validate':
 stage=Path(tempfile.mkdtemp(prefix='tio-training-strings-check-',dir='/opt'))
 for n in ('server','tio','tools','config','evidence'):shutil.copytree(root/n,stage/n,ignore=shutil.ignore_patterns('__pycache__'))
 (stage/name).write_bytes(candidate)
 with tarfile.open('/root/tests.tar.gz') as tar:tar.extractall(stage,filter='data')
 if request['component']=='counter':shutil.copyfile('/root/training-counter-tests.py',stage/'tests/test_training_arena.py')
 run=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*request['modules'],'-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=220)
 result=dict(passed=run.returncode==0,candidate_sha256=request['after'],stage=str(stage),log=run.stdout+run.stderr,isolated_database=True)
 (folder/'validation.json').write_text(json.dumps(result))
 print(json.dumps(result))
else:
 validation=json.loads((folder/'validation.json').read_text());assert validation['passed'] and validation['candidate_sha256']==request['after']
 manifest={name:dict(before=sha(current),after=sha(candidate))}
 with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
  for n,raw in [(name,candidate),('manifest.json',json.dumps(manifest).encode())]:
   entry=tarfile.TarInfo(n);entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
 sys.argv=['deployer','--archive',str(folder/'patch.tar.gz'),'--sha256',sha((folder/'patch.tar.gz').read_bytes()),'--baseline',str(folder/'baseline.json'),'--backup','/root/tio-before-game-operations-training-'+request['component']+'-20261018','--scope','training-'+request['component']]
 exec(compile(request['deployer'],'training-scoped-deployer','exec'),{'__name__':'__main__'})
'''
def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));p.add_argument('--component',choices=('strings','counter'),default='strings');args=p.parse_args()
    name='tio/protocol/assault.py' if args.component=='strings' else 'server/training_arena.py';raw=(WORK/'candidate'/name).read_bytes()
    before=(hashlib.sha256((WORK/'baseline'/name).read_bytes()).hexdigest() if args.component=='strings' else json.loads((REPORT/'patch-manifest.json').read_text())[name]['after'])
    modules=['test_training_arena','test_training_on_demand','test_world_runtime','test_assault_interface_integration','test_assault_location_admission','test_assault_public','test_clan_warfare_protocol']
    request=dict(mode=args.mode,component=args.component,name=name,before=before,after=hashlib.sha256(raw).hexdigest(),candidate=base64.b64encode(raw).decode(),deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text(),modules=modules)
    if args.component=='counter':request['modules']=[m+'.test_deadline_normal_pvp_settles_once_no_territory_or_weekly_awards' for m in ('test_training_arena.TrainingArenaTests','test_training_on_demand.OnDemandTests')]
    result=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=300)
    if result.returncode:raise RuntimeError(result.stderr[-2400:])
    value=json.loads(result.stdout);(REPORT/(args.component+('-remote-checks.json' if args.mode=='validate' else '-deployment.json'))).write_text(json.dumps(value,indent=2));print(json.dumps(value))
if __name__=='__main__':main()
