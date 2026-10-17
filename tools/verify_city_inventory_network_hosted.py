"""Exercise the observed city33 fix in a disposable hosted network server."""
import base64,hashlib,json
from pathlib import Path
from tools.deploy_gameplay_completion import ROOT
from tools.deploy_stage4_economy import remote

CODE=r'''
import base64,hashlib,json,pathlib,shutil,subprocess,sys,tempfile
p=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator');name='tools/loopback_exchange.py'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
if sha(root/name)!=p['before']:raise RuntimeError('Actual prerequisite changed')
with tempfile.TemporaryDirectory(prefix='tio-city33-network-') as directory:
 stage=pathlib.Path(directory)
 for folder,patterns in (('tio',('*.py',)),('server',('*.py',)),('tools',('*.py',)),('config',('*.json',)),('evidence',('*.xml',))):
  for pattern in patterns:
   for source in (root/folder).rglob(pattern):
    target=stage/source.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 for name,record in p['sources'].items():
  raw=base64.b64decode(record['content'],validate=True)
  if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('Public source checksum mismatch')
  target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 done=subprocess.run([str(root/'.venv/bin/python'),'-X','utf8','verify_city33_network.py','--runtime',str(stage),'--expect','fixed','--output',str(stage/'network.json')],cwd=stage,capture_output=True,text=True,timeout=120)
 if done.returncode:raise RuntimeError('Disposable network regression failed')
 result=json.loads((stage/'network.json').read_text())
 if not result['passed'] or not result['source_unchanged'] or result['runtime_source_sha256']!=p['after']:raise RuntimeError('Exact network proof required')
 if sha(root/'tools/loopback_exchange.py')!=p['before']:raise RuntimeError('Actual runtime changed during isolated verification')
 result.update(hosted_isolated=True,hosted_runtime_modified=False,hosted_player_data_copied=False)
 print(json.dumps(result))
'''
def main():
    folder=ROOT/'reports/gameplay-completion/stage12-city-item-fix';target=folder/'hosted-network-acceptance.json'
    if target.exists():raise ValueError('Preserve previous proof')
    row=json.loads((folder/'candidate-manifest.json').read_text())['files']['tools/loopback_exchange.py'];sources={}
    for name,path in [('tools/loopback_exchange.py',folder/row['source']),('verify_city33_network.py',ROOT/'reports/gameplay-followup/stage12-city33-regression/verify_city33_network.py'),('evidence/owned_pet_trial.json',folder/'runtime/evidence/owned_pet_trial.json')]:
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if name=='verify_city33_network.py' and digest!='0c255bdc1ec700edd5eb4e49336d4fc8db938809638fc5c0777ba2c214d7e9da':raise ValueError('Reviewed regression changed')
        sources[name]=dict(content=base64.b64encode(raw).decode(),sha256=digest)
    if sources['tools/loopback_exchange.py']['sha256']!=row['sha256']:raise ValueError('Reviewed candidate changed')
    report=remote(CODE,dict(before=row['before'],after=row['sha256'],sources=sources))
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(passed=report['passed'],accounts=len(report['cases']),hosted_runtime_modified=False)))
if __name__=='__main__':main()
