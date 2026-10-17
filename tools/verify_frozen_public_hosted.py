"""Verify a frozen release in disposable hosted trees, never hosted saves."""
import argparse,base64,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
from tools.deploy_gameplay_completion import ROOT,valid_path
from tools.deploy_stage4_economy import remote
from tools.validate_gameplay_modes import REMOTE

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--folder',required=True,type=Path)
    parser.add_argument('--suite',action='append',required=True)
    parser.add_argument('--test-source',action='append',default=[])
    parser.add_argument('--test-helper',action='append',default=[])
    parser.add_argument('--test-artifact',action='append',default=[])
    parser.add_argument('--net-manifest',default='candidate-manifest.json')
    parser.add_argument('--frozen-tests',action='store_true')
    args=parser.parse_args();folder=args.folder.resolve()
    if not folder.is_relative_to(ROOT/'reports/gameplay-completion'):raise ValueError('Bounded release required')
    target=folder/'validation.json'
    if target.exists():raise ValueError('Preserve prior validation')
    if Path(args.net_manifest).name!=args.net_manifest:raise ValueError('Plain manifest filename required')
    manifest=json.loads((folder/args.net_manifest).read_text(encoding='utf-8'))
    local=json.loads((folder/'local-integration-validation.json').read_text(encoding='utf-8'))
    baseline=json.loads((folder/'remote-baseline.json').read_text(encoding='utf-8'))
    if not local['passed'] or not local['source_unchanged']:raise ValueError('Frozen local checks required')
    entries={}
    for name,row in manifest['files'].items():
        raw=(folder/row['source']).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if not valid_path(name) or digest!=row['sha256'] or digest!=local['source_sha256'][name]:raise ValueError('Frozen revision changed')
        if baseline['files'][name]['sha256']!=row['before']:raise ValueError('Hosted prerequisite differs: '+name)
        entries[name]=dict(before=row['before'],after=digest,content=base64.b64encode(raw).decode())
    test_root=folder/'tests' if args.frozen_tests else ROOT/'tests'
    tests={'tests/'+p.name:base64.b64encode(p.read_bytes()).decode() for p in test_root.glob('*.py')}
    tests['evidence/owned_pet_trial.json']=base64.b64encode((folder/'runtime/evidence/owned_pet_trial.json').read_bytes()).decode()
    for name in args.test_artifact:
        path=(ROOT/name).resolve()
        if len(Path(name).parts)!=2 or not name.startswith('evidence/') or path.suffix!='.json' or not path.is_relative_to(ROOT/'evidence') or path.is_symlink():raise ValueError('Explicit public evidence JSON required')
        raw=path.read_bytes();json.loads(raw);tests[name]=base64.b64encode(raw).decode()
    if args.frozen_tests:
        for path in (folder/'test-fixtures').rglob('*'):
            if path.is_file():
                if '__pycache__' in path.parts or path.suffix in ('.pyc','.tsx'):continue
                if path.suffix not in ('.py','.json','.xml') or path.is_symlink():raise ValueError('Public fixture format required')
                tests[path.relative_to(folder/'test-fixtures').as_posix()]=base64.b64encode(path.read_bytes()).decode()
        for directory in ('config','evidence'):
            for path in (folder/'runtime'/directory).rglob('*'):
                if path.is_file() and path.suffix in ('.json','.xml'):
                    tests['runtime/'+path.relative_to(folder/'runtime').as_posix()]=base64.b64encode(path.read_bytes()).decode()
    for name in args.test_helper:
        path=ROOT/name
        if len(Path(name).parts)!=2 or not name.startswith('tools/') or path.suffix!='.py':raise ValueError('Explicit public helper required')
        tests[name]=base64.b64encode(path.read_bytes()).decode()
    for name in args.test_source:
        path=ROOT/name
        if not path.resolve().is_relative_to(ROOT/'reports') or path.suffix!='.py':raise ValueError('Explicit frozen report test required')
        raw=path.read_text(encoding='utf-8').replace("RUNTIME = Path(__file__).resolve().parents[1] / 'runtime'","RUNTIME = Path(__file__).resolve().parents[1]")
        raw=raw.replace("HERE/'runtime'","HERE")
        raw=raw.replace("HERE/'runtime/","HERE/'")
        tests['tests/'+path.name]=base64.b64encode(raw.encode()).decode()
    code=REMOTE.replace("str(root/'.venv/bin/python')","str(root/'.venv-web/bin/python')")
    old=" result=subprocess.run([str(root/'.venv-web/bin/python'),'-X','utf8','-c',script],cwd=stage,capture_output=True,text=True,timeout=220)"
    new=""" import os,signal
 process=subprocess.Popen([str(root/'.venv-web/bin/python'),'-X','utf8','-c',script],cwd=stage,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
 try:stdout,stderr=process.communicate(timeout=180)
 except subprocess.TimeoutExpired:
  os.killpg(process.pid,signal.SIGKILL);stdout,stderr=process.communicate(timeout=10);stderr+='\\nBounded isolated batch timed out\\n'
 result=type('Result',(),dict(returncode=process.returncode,stdout=stdout,stderr=stderr))()
 for name,entry in p['files'].items():
  original=root/name
  digest=hashlib.sha256(original.read_bytes()).hexdigest() if original.is_file() else None
  if digest!=entry['before']:raise RuntimeError('Hosted source changed during verification')
"""
    if code.count(old)!=1:raise ValueError('Established verifier boundary changed')
    code=code.replace(old,new);batches=[];counts=[]
    for start in range(0,len(args.suite),2):
        batch=remote(code,dict(files=entries,test_sources=tests,suites=args.suite[start:start+2]))
        count=re.search(r'(?m)^Ran (\d+) tests? in ([0-9.]+)s\s*$',batch['output'])
        batch['passed']=batch['passed'] and count is not None and 'skipped=' not in batch['output']
        batches.append(batch)
        if count:counts.append(int(count[1]))
        (folder/'hosted-integration-batches.json').write_text(json.dumps(batches,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(batch=len(batches),passed=batch['passed'],test_count=int(count[1]) if count else None)),flush=True)
        if not batch['passed']:break
    unchanged=all(hashlib.sha256((folder/'runtime'/n).read_bytes()).hexdigest()==h for n,h in local['source_sha256'].items())
    expected=re.search(r'(?m)^Ran (\d+) tests? in ',local['output'])
    passed=unchanged and len(batches)==(len(args.suite)+1)//2 and all(b['passed'] for b in batches) and expected is not None and sum(counts)==int(expected[1])
    result=dict(passed=passed,source_unchanged=unchanged,source_sha256={n:row['sha256'] for n,row in manifest['files'].items()},local=local,
        hosted_isolated=dict(passed=passed,batches=batches,test_count=sum(counts),hosted_player_data_copied=False,hosted_runtime_modified=False),
        utc=datetime.now(timezone.utc).isoformat(),graphical_client_acceptance=False)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=passed,test_count=sum(counts),source_unchanged=unchanged)))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
