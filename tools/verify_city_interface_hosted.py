"""Run city operations against disposable hosted saves and private fixtures."""
from datetime import datetime,timezone
import base64,hashlib,json,re
from pathlib import Path
from tools.deploy_stage4_economy import remote
from tools.validate_gameplay_modes import REMOTE

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-completion/stage9-city'


def main():
    target=FOLDER/'hosted-isolated-validation-v2.json'
    if target.exists():raise ValueError('Preserve prior verification')
    manifest=json.loads((FOLDER/'candidate-manifest.json').read_text(encoding='utf-8'))
    baseline=json.loads((FOLDER/'remote-baseline.json').read_text(encoding='utf-8'))
    local=json.loads((FOLDER/'local-validation.json').read_text(encoding='utf-8'));entries={}
    for name,row in manifest['files'].items():
        raw=(FOLDER/row['source']).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=row['sha256'] or digest!=local['source_sha256'][name] or row['before']!=baseline['files'][name]['sha256']:raise ValueError('Frozen candidate/base differs')
        entries[name]=dict(before=row['before'],after=digest,content=base64.b64encode(raw).decode())
    tests={p.relative_to(ROOT).as_posix():base64.b64encode(p.read_bytes()).decode() for p in (ROOT/'tests').glob('*.py')}
    fixture='evidence/owned_pet_trial.json';raw=(ROOT/fixture).read_bytes()
    if hashlib.sha256(raw).hexdigest()!='6d927313a2f3693b13f9d2bfea068e6589c6e28f1ecdbc16e1cc8e7792246a74':raise ValueError('Public onboarding test fixture changed')
    tests[fixture]=base64.b64encode(raw).decode()
    code=REMOTE.replace("str(root/'.venv/bin/python')","str(root/'.venv-web/bin/python')")
    marker=' print(json.dumps(dict(passed=result.returncode==0'
    if code.count(marker)!=1:raise ValueError('Isolated output boundary changed')
    after=""" for name,entry in p['files'].items():
  path=root/name
  digest=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
  if digest!=entry['before']:raise RuntimeError('Public sources changed during verification')
"""
    result=remote(code.replace(marker,after+marker),dict(files=entries,test_sources=tests,suites=['test_city_operations','test_bank_gateway']))
    unchanged=all(hashlib.sha256((FOLDER/r['source']).read_bytes()).hexdigest()==r['sha256'] for r in manifest['files'].values())
    output=result['output'];match=re.search(r'(?m)^Ran (\d+) tests in [0-9.]+s\s*$',output)
    result.update(utc=datetime.now(timezone.utc).isoformat(),source_unchanged=unchanged,source_sha256=local['source_sha256'],flask_runtime_required=True,
        passed=result['passed'] and unchanged and bool(match and int(match[1])==33) and 'skipped=' not in output)
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if result['passed']:
        (FOLDER/'validation.json').write_text(json.dumps(dict(passed=True,source_unchanged=True,source_sha256=local['source_sha256'],local=local,hosted_isolated=result,graphical_client_acceptance=False),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],source_unchanged=unchanged,output=output[-2500:])))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
