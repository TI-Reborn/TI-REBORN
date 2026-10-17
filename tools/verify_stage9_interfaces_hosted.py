"""Run the reviewed interface suites on hosted CPU, using disposable saves."""
from datetime import datetime,timezone
import base64
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.validate_gameplay_modes import REMOTE

FOLDER=ROOT/'reports/gameplay-completion/stage9-interfaces-revision2'


def main():
    target=FOLDER/'hosted-isolated-validation.json'
    if target.exists():raise ValueError('Preserve the prior hosted verification')
    local=json.loads((FOLDER/'local-validation.json').read_text(encoding='utf-8'))
    manifest=json.loads((FOLDER/'candidate-manifest.json').read_text(encoding='utf-8'))
    baseline=json.loads((FOLDER/'remote-baseline.json').read_text(encoding='utf-8'))
    if not local['passed'] or not local['source_unchanged']:raise ValueError('Frozen local validation is required')
    entries={}
    for name,row in manifest['files'].items():
        raw=(FOLDER/row['source']).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=row['sha256'] or digest!=local['source_sha256'][name]:raise ValueError('Validated candidate changed')
        if baseline['files'][name]['sha256']!=row['before']:raise ValueError('Fresh hosted baseline differs')
        entries[name]=dict(before=row['before'],after=digest,content=base64.b64encode(raw).decode('ascii'))
    tests={p.relative_to(ROOT).as_posix():base64.b64encode(p.read_bytes()).decode('ascii') for p in (ROOT/'tests').glob('*.py')}
    for name,digest in local['public_test_fixture_sha256'].items():
        raw=(ROOT/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Verified test fixture changed')
        tests[name]=base64.b64encode(raw).decode('ascii')
    old="str(root/'.venv/bin/python')"
    if REMOTE.count(old)!=1:raise ValueError('Established isolated test boundary changed')
    code=REMOTE.replace(old,"str(root/'.venv-web/bin/python')")
    marker=' print(json.dumps(dict(passed=result.returncode==0'
    if code.count(marker)!=1:raise ValueError('Established result boundary changed')
    guard=""" for name,entry in p['files'].items():
  original=root/name
  digest=hashlib.sha256(original.read_bytes()).hexdigest() if original.is_file() else None
  if digest!=entry['before']:raise RuntimeError('Hosted source changed during isolated verification')
"""
    code=code.replace(marker,guard+marker)
    # The first all-suite attempt returned only the established helper's opaque
    # error. Preserve that observation; its stderr and exact cause were not
    # retained, so do not report it as a proven test or timeout failure.
    observation=FOLDER/'hosted-first-attempt.json'
    if not observation.exists():
        observation.write_text(json.dumps(dict(passed=False,
            observation='Established SSH helper returned RuntimeError without a report',
            exact_remote_cause='unavailable',hosted_runtime_modified=False,
            test_results_recovered=False),indent=2)+'\n',encoding='utf-8')
    # Bound each independent module pair and terminate the whole disposable
    # test process group on timeout. No service process belongs to that group.
    old=" result=subprocess.run([str(root/'.venv-web/bin/python'),'-X','utf8','-c',script],cwd=stage,capture_output=True,text=True,timeout=220)"
    new=""" import os,signal
 process=subprocess.Popen([str(root/'.venv-web/bin/python'),'-X','utf8','-c',script],cwd=stage,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
 try:
  stdout,stderr=process.communicate(timeout=180)
 except subprocess.TimeoutExpired:
  os.killpg(process.pid,signal.SIGKILL)
  stdout,stderr=process.communicate(timeout=10)
  stderr+='\\nIsolated module batch exceeded 180 seconds\\n'
 result=type('Result',(),dict(returncode=process.returncode,stdout=stdout,stderr=stderr))()
"""
    if code.count(old)!=1:raise ValueError('Isolated test process boundary changed')
    code=code.replace(old,new)
    batches=[]
    suites=local['suites']
    evidence=FOLDER/'hosted-validation-batches.json'
    if evidence.exists():raise ValueError('Preserve prior bounded evidence')
    for start in range(0,len(suites),2):
        row=remote(code,dict(files=entries,test_sources=tests,suites=suites[start:start+2]))
        row['passed']=row['passed'] and 'skipped=' not in row.get('output','')
        batches.append(row)
        evidence.write_text(json.dumps(batches,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(batch=len(batches),passed=row['passed'],suites=row['suites'])),flush=True)
        if not row['passed']:break
    outputs=[b['output'] for b in batches]
    counts=[re.search(r'(?m)^Ran (\d+) tests? in ([0-9.]+)s\s*$',o) for o in outputs]
    count=sum(int(m[1]) for m in counts if m)
    elapsed=sum(float(m[2]) for m in counts if m)
    passed=(len(batches)==(len(suites)+1)//2 and all(b['passed'] for b in batches)
            and all(counts) and count==144)
    output='\n'.join(outputs)+f'\nAggregated bounded module verification:\nRan {count} tests in {elapsed:.3f}s\n\n'+('OK' if passed else 'FAILED')+'\n'
    result=dict(passed=passed,exit_code=0 if passed else 1,output=output,
        batches=batches,suites=suites,test_count=count,aggregation='independent module pairs',
        hosted_player_data_copied=False,hosted_runtime_modified=False)
    unchanged=all(hashlib.sha256((FOLDER/manifest['files'][n]['source']).read_bytes()).hexdigest()==h for n,h in local['source_sha256'].items())
    if 'skipped=' in result.get('output',''):result['passed']=False
    result.update(utc=datetime.now(timezone.utc).isoformat(),source_unchanged=unchanged,
                  source_sha256=local['source_sha256'],flask_runtime_required=True,
                  passed=result['passed'] and unchanged)
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if result['passed']:
        final=dict(passed=True,source_unchanged=unchanged,source_sha256=local['source_sha256'],
            local=local,hosted_isolated=result,graphical_client_acceptance=False)
        validation=FOLDER/'validation.json'
        if validation.exists():raise ValueError('Preserve previous combined validation')
        validation.write_text(json.dumps(final,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__=='__main__':sys.exit(main())
