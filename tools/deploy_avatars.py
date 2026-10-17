"""Validate and publish native avatar catalog, assignments and original art."""
import argparse,base64,hashlib,io,json,sys,zipfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote
from deploy.client_avatars import patch
FOLDER=ROOT/'reports/avatars'
MODULES=('test_avatars','test_arena_roster','test_shared_team_arena','test_shared_wager_arena','test_shooting_range','test_battle_crash_recovery')

VALIDATE=r'''
import pathlib,json,sys,hashlib,tempfile,shutil,subprocess,base64,zipfile,io,os
data=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator')
for n,digest in data['expected'].items():assert (hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).exists() else None)==digest,'Remote source changed: '+n
stage=pathlib.Path(tempfile.mkdtemp(prefix='tio-avatars-check-',dir='/root'))
for folder in ('tio','server','tools','config'):
 shutil.copytree(root/folder,stage/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for folder in ('assets',):
 if (root/folder).exists():(stage/folder).symlink_to(root/folder,target_is_directory=True)
(stage/'evidence').mkdir()
for original in (root/'evidence').iterdir():
 (stage/'evidence'/original.name).symlink_to(original,target_is_directory=original.is_dir())
for n,s in data['sources'].items():
 target=stage/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(s,encoding='utf-8')
# This XML is a preparation artifact and is not installed on the runtime host.
# Build the isolated fixture from the actual published, reviewed item catalog.
if not (stage/'config/battle_item_catalog_extension.xml').exists():
 import xml.etree.ElementTree as ET
 live=pathlib.Path('/var/www/tio-client/updates');manifest=json.loads((live/'manifest.json').read_bytes())
 record=next(r for r in manifest['files'] if r['path']=='base/shared config/items.xml')
 ids=set(json.loads((stage/'config/battle_item_catalog_extension.json').read_text())['new_ids'])
 document=ET.fromstring((live/'blobs'/record['sha256']).read_bytes());output=ET.Element(document.tag)
 for node in document:
  if int(node.get('id')) in ids:output.append(node)
 ET.ElementTree(output).write(stage/'config/battle_item_catalog_extension.xml',encoding='utf-8')
with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['tests']))) as z:
 for n in z.namelist():
  assert n.startswith(('tests/','evidence/')) and '..' not in pathlib.PurePosixPath(n).parts
  if (stage/n).is_symlink():(stage/n).unlink()
 z.extractall(stage)
result=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*[n for n in data['modules']]],cwd=stage,text=True,capture_output=True,timeout=75,
 env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')})
report=dict(passed=result.returncode==0,stage=str(stage),output=result.stderr[-12000:],hosted_database_used=False)
print(json.dumps(report))
'''

DEPLOY=r'''
import pathlib,json,sys,hashlib,tempfile,shutil,subprocess,sqlite3,base64,os
from contextlib import closing
data=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator');live=pathlib.Path('/var/www/tio-client/updates')
path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
def sha(raw):return hashlib.sha256(raw).hexdigest()
prior=base64.b64decode(data['before']);after=base64.b64decode(data['after'])
assert (live/'manifest.json').read_bytes()==prior,'Client manifest changed; rebuild from actual release'
old=json.loads(prior);new=json.loads(after);a={r['path']:r for r in old['files']};b={r['path']:r for r in new['files']}
assert set(a)<=set(b) and set(old)-{'files','version'}==set(new)-{'files','version'}
assert all(old[k]==new[k] for k in old if k not in ('files','version'))
allowed=set(data['assets']);assert allowed=={'silver.dll',*set(b)-set(a)}
assert [n for n in a if a[n]!=b[n]]==['silver.dll']
assert b['silver.dll']['seed'] is False
for n,digest in data['expected'].items():assert (sha((root/n).read_bytes()) if (root/n).exists() else None)==digest,'Hosted code changed: '+n
def idle():
 with closing(sqlite3.connect(path)) as db:
  for t in ('battle_checkpoints','battle_settlement_jobs'):assert db.execute('SELECT count(*) FROM '+t).fetchone()[0]==0,'Active battle; defer deployment'
def fingerprint():
 with closing(sqlite3.connect(path)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:sha(repr(sorted(map(repr,db.execute('SELECT * FROM "'+t+'"').fetchall()))).encode()) for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
def atomic(raw,target):
 stage=target.with_name(target.name+'.avatars-new')
 with stage.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 stage.chmod(0o644);stage.replace(target)
for n,h in data['resources'].items():
 row=a[n];assert row['sha256']==h and sha((live/'blobs'/h).read_bytes())==h,'Original weather resource changed: '+n
idle();backup=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-avatars-',dir='/root'));backup.chmod(0o700)
with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(backup/path.name)) as dst:src.backup(dst)
(backup/path.name).chmod(0o600)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml');(backup/'server.toml').chmod(0o600)
shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
(backup/'manifest.json').write_bytes(prior)
shutil.copy2(live/'blobs'/a['silver.dll']['sha256'],backup/'silver.dll')
for n in data['sources']:
 dest=backup/'code'/n;dest.parent.mkdir(parents=True,exist_ok=True)
 if (root/n).exists():shutil.copy2(root/n,dest)
# Immutable asset publication is harmless until the single manifest pointer changes.
for n,encoded in data['assets'].items():
 blob=base64.b64decode(encoded);assert sha(blob)==b[n]['sha256'] and len(blob)==b[n]['size']
 target=live/'blobs'/sha(blob)
 if target.exists():assert target.read_bytes()==blob
 else:atomic(blob,target)
idle();subprocess.run(['systemctl','stop','tio-server'],check=True)
try:
 idle()
 with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(backup/path.name)) as dst:src.backup(dst)
 before=fingerprint()
 for n,text in data['sources'].items():atomic(text.encode(),root/n)
 check=subprocess.run(['runuser','-u','tio','--',str(root/'.venv/bin/python'),'-m','server','--config','/etc/tio-server/server.toml','--check'],cwd=root,text=True,capture_output=True)
 assert check.returncode==0,check.stderr
 assert fingerprint()==before,'Hosted rows changed during update'
 atomic(after,live/'manifest.json')
except BaseException:
 for n in data['sources']:
  if (backup/'code'/n).exists():shutil.copy2(backup/'code'/n,root/n)
  else:(root/n).unlink(missing_ok=True)
 atomic(prior,live/'manifest.json')
 raise
finally:subprocess.run(['systemctl','start','tio-server'],check=True)
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
report=dict(backup=str(backup),service='active',preflight_passed=True,database_rows_preserved=True,
            version=new['version'],client_sha256=b['silver.dll']['sha256'],published_assets=len(allowed),graphical_clients_used=False)
(backup/'receipt.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
'''


def inputs():
    expected=json.loads((FOLDER/'source-hashes.json').read_text())
    sources={}
    for n in expected:
        candidate=FOLDER/'server-candidate'/n
        if not candidate.exists():
            candidate.parent.mkdir(parents=True,exist_ok=True);candidate.write_bytes((ROOT/n).read_bytes())
        sources[n]=candidate.read_text(encoding='utf-8')
    return dict(expected=expected,sources=sources,resources=json.loads((FOLDER/'resource-proof.json').read_text())['original_dependencies'])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('validate','check','deploy','verify'));args=parser.parse_args()
    payload=inputs()
    if args.command=='validate':
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('tests/__init__.py','')
            for p in (ROOT/'tests').glob('*.py'):z.write(p,'tests/'+p.name)
            for name in ('special_items_native.json','battle_item_native.json','battle_move_native.json','move_request_native.json'):
                z.write(ROOT/'evidence'/name,'evidence/'+name)
        payload.update(tests=base64.b64encode(buffer.getvalue()).decode(),modules=MODULES)
        code=VALIDATE.split('result=subprocess.run(')[0]+r"""
worker=stage/'run_tests.py'
worker.write_text("import subprocess,json,pathlib,os\n"+
 "r=subprocess.run("+repr([str(root/'.venv/bin/python'),'-m','unittest',*data['modules']])+",cwd="+repr(str(stage))+",text=True,capture_output=True,timeout=300,env={**os.environ,'PYTHONPATH':"+repr(str(stage)+':'+str(stage/'tests'))+"})\n"+
 "pathlib.Path("+repr(str(stage/'test-result.json'))+").write_text(json.dumps(dict(passed=r.returncode==0,stage="+repr(str(stage))+",output=r.stderr[-15000:],hosted_database_used=False)))\n")
subprocess.Popen([str(root/'.venv/bin/python'),str(worker)],cwd=stage,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
print(json.dumps(dict(pending=True,stage=str(stage))))
"""
        result=remote(code,payload);(FOLDER/'pending-tests.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    elif args.command=='check':
        pending=json.loads((FOLDER/'pending-tests.json').read_text())
        result=remote("import json,sys,pathlib;d=json.load(sys.stdin);p=pathlib.Path(d['stage'])/'test-result.json';print(p.read_text() if p.exists() else json.dumps({'pending':True}))",pending)
        name='pending-check.json' if result.get('pending') else 'remote-tests.json'
        (FOLDER/name).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    elif args.command=='deploy':
        assert json.loads((FOLDER/'remote-tests.json').read_text())['passed']
        proof=json.loads((FOLDER/'client-native.json').read_text());assert proof['passed']
        assets={p.relative_to(FOLDER/'client').as_posix():p.read_bytes() for p in (FOLDER/'client').rglob('*') if p.is_file()}
        assert assets['silver.dll']==patch((FOLDER/'silver-source.dll').read_bytes())
        catalog=json.loads(payload['sources']['config/avatars.json'])
        for row in catalog['avatars']:assert assets[row['asset']]==base64.b64decode(row['jpeg_b64'])
        assert hashlib.sha256(assets['silver.dll']).hexdigest()==proof['candidate_sha256']
        before=(FOLDER/'previous-manifest.json').read_bytes();manifest=json.loads(before)
        for n,blob in assets.items():
            record=dict(path=n,size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),seed=False)
            row=next((r for r in manifest['files'] if r['path']==n),None)
            if n=='silver.dll':assert row is not None;row.update(record)
            else:assert row is None;manifest['files'].append(record)
        manifest['version']='2026.10.12.3'
        after=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();(FOLDER/'manifest.json').write_bytes(after)
        payload.update(before=base64.b64encode(before).decode(),after=base64.b64encode(after).decode(),assets={n:base64.b64encode(b).decode() for n,b in assets.items()})
        result=remote(DEPLOY,payload);(FOLDER/'deployment.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    else:
        expected=(FOLDER/'manifest.json').read_bytes();origin='https://185.184.42.88/updates/'
        with urllib.request.urlopen(origin+'manifest.json',timeout=30) as r:assert r.read()==expected
        names={'silver.dll',*[p.relative_to(FOLDER/'client').as_posix() for p in (FOLDER/'client').rglob('*') if p.is_file()]}
        checked={}
        for row in json.loads(expected)['files']:
            if row['path'] not in names:continue
            with urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=30) as r:blob=r.read()
            assert len(blob)==row['size'] and hashlib.sha256(blob).hexdigest()==row['sha256']
            checked[row['path']]=row['sha256']
        result=dict(passed=True,trusted_https=True,verified_files=checked)
        (FOLDER/'https-verification.json').write_text(json.dumps(result,indent=2));print('Verified public HTTPS manifest and '+str(len(checked))+' release files')


if __name__=='__main__':main()
