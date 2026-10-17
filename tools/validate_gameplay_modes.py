"""Validate frozen multiplayer sources locally and in a disposable hosted tree.

Uploads public code and tests only; never reads, copies or edits hosted saves.
The service and its active source tree remain untouched by candidate tests.
"""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import sys

from tools.deploy_gameplay_completion import ROOT,valid_path,validate,source_path
from tools.deploy_stage4_economy import remote

SUITES=('test_shared_wager_arena','test_shared_survival_groups','test_shared_team_arena',
        'test_wagers','test_tactical_marks','test_combat_sight_scatter','test_battle_crash_recovery',
        'test_gameplay_deployment')

REMOTE=r'''
import base64,hashlib,json,pathlib,shutil,subprocess,sys,tempfile
p=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator')
for name,entry in p['files'].items():
 path=root/name
 digest=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
 if digest!=entry['before']:raise RuntimeError('Hosted baseline changed')
with tempfile.TemporaryDirectory(prefix='tio-gameplay-candidate-') as folder:
 stage=pathlib.Path(folder)
 # Copy only runtime/public artifacts, never /var/lib or project player data.
 for directory,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json'),('evidence','*.xml')):
  for source in (root/directory).rglob(pattern):
   target=stage/source.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 for name,entry in p['files'].items():
  target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
  raw=base64.b64decode(entry['content'],validate=True)
  if hashlib.sha256(raw).hexdigest()!=entry['after']:raise ValueError('Candidate checksum mismatch')
  target.write_bytes(raw)
 for name,content in p['test_sources'].items():
  target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
  target.write_bytes(base64.b64decode(content,validate=True))
 script="import sys,unittest;sys.path[:0]=['tests','tools'];r=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames("+repr(p['suites'])+"));sys.exit(not r.wasSuccessful())"
 result=subprocess.run([str(root/'.venv/bin/python'),'-X','utf8','-c',script],cwd=stage,capture_output=True,text=True,timeout=220)
 print(json.dumps(dict(passed=result.returncode==0,exit_code=result.returncode,
  output=(result.stdout+result.stderr)[-16000:],hosted_player_data_copied=False,
  hosted_runtime_modified=False,suites=p['suites'])))
'''


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--folder',required=True,type=Path)
 parser.add_argument('--suite',action='append',help='Explicit bounded test modules; default modes regression')
 parser.add_argument('--native',action='append',help='Explicit native proof tool names; default modes proofs')
 parser.add_argument('--test-artifact',action='append',help='Explicit public JSON/XML fixture used by selected tests')
 parser.add_argument('--test-helper',action='append',help='Explicit repository Python test helper, never installed')
 parser.add_argument('--scope-proof',action='store_true',help='Copy this candidate map-generation source/override as public scope evidence')
 args=parser.parse_args();folder=args.folder.resolve()
 if not folder.is_relative_to(ROOT/'reports/gameplay-completion'):raise ValueError('Expected report folder')
 files=json.loads((folder/'runtime-files.json').read_text(encoding='utf-8'))
 baseline=json.loads((folder/'remote-baseline.json').read_text(encoding='utf-8'))
 entries={}
 for name in files:
  if not valid_path(name):raise ValueError('Unexpected runtime file')
  raw=source_path(folder,name).read_bytes();validate(name,raw)
  entries[name]=dict(before=baseline['files'].get(name,{}).get('sha256'),
    after=hashlib.sha256(raw).hexdigest(),content=base64.b64encode(raw).decode('ascii'))
 hashes={n:e['after'] for n,e in entries.items()}
 suites=tuple(args.suite or SUITES)
 if any(not n.startswith('test_') or not n.replace('_','').isalnum() for n in suites):raise ValueError('Unexpected test module')
 native_tools=tuple(args.native or ('verify_wager_requests_native.py','verify_tactical_marks_native.py'))
 if any(Path(n).name!=n or not n.startswith('verify_') or not n.endswith('.py') for n in native_tools):raise ValueError('Unexpected native tool')
 fixture_sources={}
 for name in args.test_artifact or ():
  p=Path(name)
  client_xml=p.as_posix() in ('reports/dog-encounters/client/animation.xml',
                            'reports/dog-encounters/client/items.xml')
  if p.is_absolute() or '..' in p.parts or (not client_xml and
       (len(p.parts)!=2 or p.parts[0] not in ('config','evidence') or p.suffix not in ('.json','.xml'))):
   raise ValueError('Only explicit public catalog/evidence test artifacts supported')
  raw=source_path(folder,p.as_posix()).read_bytes()
  if len(raw)>4*1024*1024:raise ValueError('Public test artifact too large')
  fixture_sources[p.as_posix()]=raw
 if args.scope_proof:
  if folder.name!='stage8-world':raise ValueError('Expected world scope evidence')
  for suffix in ('source/map_generation.py','source/combat.py',
                 'source/world_completion_before_detroit.py','runtime/tio/map_generation.py'):
   path=folder/suffix
   raw=path.read_bytes();compile(raw,suffix,'exec')
   fixture_sources[path.relative_to(ROOT).as_posix()]=raw
 script="import sys,unittest;sys.path[:0]=['tests','tools'];r=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames("+repr(suites)+"));sys.exit(not r.wasSuccessful())"
 # Child-process crash checks must see the same immutable public config as
 # their parent while later independent gameplay packages are being prepared.
 with tempfile.TemporaryDirectory(prefix='tio-gameplay-local-') as local_folder:
  local_root=Path(local_folder)
  overrides=json.loads((folder/'candidate-overrides.json').read_text()) if (folder/'candidate-overrides.json').exists() else {}
  for directory,patterns in (('tio',('*.py',)),('server',('*.py',)),('tools',('*.py',)),('config',('*.json','*.xml')),('evidence',('*.xml','*.json')),('tests',('*.py',))):
   for pattern in patterns:
    for source in (ROOT/directory).rglob(pattern):
     name=source.relative_to(ROOT).as_posix()
     target=local_root/name;target.parent.mkdir(parents=True,exist_ok=True)
     shutil.copy2(source_path(folder,name) if name in overrides else source,target)
  for name,entry in entries.items():
   target=local_root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(base64.b64decode(entry['content'],validate=True))
  for name,raw in fixture_sources.items():
   target=local_root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
  local=subprocess.run([sys.executable,'-X','utf8','-c',script],cwd=local_root,capture_output=True,text=True,timeout=150)
 native=[]
 if local.returncode==0:
  for name in native_tools:
   result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools'/name)],cwd=ROOT,capture_output=True,text=True,timeout=120)
   native.append(dict(tool=name,passed=result.returncode==0,output=(result.stdout+result.stderr)[-3000:]))
 test_sources={p.relative_to(ROOT).as_posix():base64.b64encode(p.read_bytes()).decode('ascii') for p in (ROOT/'tests').glob('*.py')}
 for name in ('tools/deploy_gameplay_completion.py','tools/deploy_stage4_economy.py','evidence/owned_pet_trial.json'):
  test_sources[name]=base64.b64encode((ROOT/name).read_bytes()).decode('ascii')
 for name,raw in fixture_sources.items():test_sources[name]=base64.b64encode(raw).decode('ascii')
 for name in args.test_helper or ():
  p=Path(name)
  if p.is_absolute() or '..' in p.parts or len(p.parts)!=2 or p.parts[0]!='tools' or p.suffix!='.py':
   raise ValueError('Only explicit tools Python test helpers supported')
  raw=(ROOT/p).read_bytes()
  if len(raw)>1024*1024:raise ValueError('Public test helper too large')
  compile(raw,name,'exec')
  test_sources[p.as_posix()]=base64.b64encode(raw).decode('ascii')
 hosted=dict(passed=False,skipped=True)
 if local.returncode==0 and all(n['passed'] for n in native):
  # The hosted machine has a smaller CPU. Independent modules run in bounded
  # subprocess batches; no long all-suite timeout loses completed evidence.
  batches=[]
  for start in range(0,len(suites),2):
   group=suites[start:start+2]
   result=remote(REMOTE,dict(files=entries,test_sources=test_sources,suites=group))
   batches.append(result)
   (folder/'validation-hosted-batches.json').write_text(json.dumps(batches,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
   if not result['passed']:break
  hosted=dict(passed=all(b['passed'] for b in batches) and len(batches)==(len(suites)+1)//2,batches=batches,suites=suites,hosted_player_data_copied=False,hosted_runtime_modified=False)
 unchanged=all(hashlib.sha256(source_path(folder,n).read_bytes()).hexdigest()==h for n,h in hashes.items())
 report=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),source_sha256=hashes,
  test_artifact_sha256={n:hashlib.sha256(raw).hexdigest() for n,raw in fixture_sources.items()},
  source_unchanged=unchanged,local=dict(passed=local.returncode==0,output=(local.stdout+local.stderr)[-16000:]),
  native=native,hosted_isolated=hosted,passed=local.returncode==0 and all(n['passed'] for n in native) and hosted['passed'] and unchanged,
  graphical_client_acceptance=False)
 (folder/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(dict(passed=report['passed'],local=local.returncode==0,native=[n['passed'] for n in native],hosted_isolated=hosted['passed'],source_unchanged=unchanged)))
 if not report['passed']:raise RuntimeError('Candidate validation failed; see validation report')


if __name__=='__main__':main()
