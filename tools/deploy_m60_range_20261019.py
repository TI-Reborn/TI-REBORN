"""Validate and publish the M60-only server/client range with fresh hosted backups."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
from tools.deploy_stage4_economy import remote
from tools.publish_gameplay_xml_client import publisher
WORK=ROOT/'work/m60-range-20261019';OUT=ROOT/'reports/m60-range-20261019'
FILES=('config/weapon_catalog.json','evidence/items_diagnostic.xml')
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def entries():
    return {n:dict(before=sha((WORK/'baseline'/n).read_bytes()),after=sha((WORK/'candidate'/n).read_bytes()),raw=base64.b64encode((WORK/'candidate'/n).read_bytes()).decode()) for n in FILES}


VALIDATE=r'''
import os,shutil,tempfile,subprocess,base64,json,io,tarfile,hashlib
from pathlib import Path
root=Path('/opt/tio-emulator');stage=Path(tempfile.mkdtemp(prefix='tio-m60-range-check-',dir='/opt'))
for name in ('server','tio','tools','config','evidence'):shutil.copytree(root/name,stage/name,ignore=shutil.ignore_patterns('__pycache__'))
for name,row in request['files'].items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==row['before']
 raw=base64.b64decode(row['raw']);assert hashlib.sha256(raw).hexdigest()==row['after'];(stage/name).write_bytes(raw)
with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request['tests'])),mode='r:gz') as t:t.extractall(stage,filter='data')
run=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest','test_area_fire','test_weapon_range','test_weapon_effects','-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=180)
result=dict(passed=run.returncode==0,stage=str(stage),hashes={n:r['after'] for n,r in request['files'].items()},log=run.stdout+run.stderr,isolated_database=True)
print(json.dumps(result))
'''


def validate():
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:gz') as t:t.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
    request=dict(files=entries(),tests=base64.b64encode(buf.getvalue()).decode())
    r=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -'],input='request='+repr(request)+'\n'+VALIDATE,encoding='utf-8',capture_output=True,timeout=240)
    if r.returncode:raise RuntimeError(r.stderr[-1500:])
    result=json.loads(r.stdout);(OUT/'remote-checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));assert result['passed']


def publish():
    checked=json.loads((OUT/'remote-checks.json').read_text());files=entries()
    assert checked['passed'] and checked['hashes']=={n:r['after'] for n,r in files.items()}
    old=(WORK/'manifest-before.json').read_bytes();manifest=json.loads(old)
    assert urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read()==old
    name='base/shared config/items.xml';record=next(x for x in manifest['files'] if x['path']==name)
    raw=(WORK/'client-items-candidate.xml').read_bytes();before=(WORK/'client-items-before.xml').read_bytes();assert sha(before)==record['sha256']
    record.update(sha256=sha(raw),size=len(raw),seed=False);manifest['version']='2026.10.19.2'
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    code=publisher().replace("'base/shared config/skills.xml','base/shared config/zones.xml'","'base/shared config/skills.xml','base/shared config/items.xml','base/shared config/zones.xml'")
    anchor='service=subprocess.check_output'
    validation="""server_files=p['server_files']
if set(server_files)!={'config/weapon_catalog.json','evidence/items_diagnostic.xml'}:raise ValueError('Unexpected server scope')
for path,row in server_files.items():
 current=(root/path).read_bytes();data=base64.b64decode(row['raw'],validate=True)
 if sha(current)!=row['before'] or sha(data)!=row['after']:raise RuntimeError('Server baseline/candidate changed')
 if path.endswith('.json'):
  x=json.loads(current);y=json.loads(data);expected=json.loads(current)
  expected['weapons']['314']['max_range']=12;expected['weapons']['314']['source_fields']['maxRange']='12'
  if y!=expected:raise ValueError('Unrelated server weapon rule changed')
 else:
  x=ET.fromstring(current);y=ET.fromstring(data)
  oldrows={int(n.get('id')):semantic(n) for n in x};newrows={int(n.get('id')):semantic(n) for n in y}
  if oldrows.keys()!=newrows.keys() or [i for i in oldrows if oldrows[i]!=newrows[i]]!=[314]:raise ValueError('Unrelated server item changed')
  expected=ET.fromstring(current);expected.find(\"item[@id='314']/value[@key='maxRange']\").set('val','12')
  if semantic(expected)!=semantic(y):raise ValueError('Unrelated M60 item rule changed')
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as d:
 for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):
  if d.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():raise RuntimeError('Retained battle prevents catalogue release')
if subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip():raise RuntimeError('Connected players prevent catalogue release')
"""
    assert code.count(anchor)==1;code=code.replace(anchor,validation+anchor)
    anchor="target=live/'blobs'/record['sha256']"
    install="""for path,row in server_files.items():
 saved=backup/'server-files'/path;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/path,saved)
 if sha((root/path).read_bytes())!=row['before']:raise RuntimeError('Server changed during backup')
for path,row in server_files.items():atomic(base64.b64decode(row['raw']),root/path)
"""
    assert code.count(anchor)==1;code=code.replace(anchor,install+anchor)
    code=code.replace('report=dict(version=',"report=dict(server_files={n:{k:v for k,v in row.items() if k!='raw'} for n,row in server_files.items()},server_catalogue_hot_read=True,version=")
    r=remote(code,dict(server_files=files,before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),candidate=base64.b64encode(raw).decode(),base_sha256=sha(before),path=name,changed_ids=[314],added_ids=[]))
    (OUT/'publication.json').write_text(json.dumps(r,indent=2));(OUT/'manifest.json').write_bytes(new)
    assert urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read()==new
    assert urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+sha(raw),timeout=30).read()==raw
    (OUT/'https-verification.json').write_text(json.dumps(dict(passed=True,version=manifest['version'],sha256=sha(raw),trusted_https=True),indent=2))
    print(json.dumps(r))


def restart():
    receipt=json.loads((OUT/'publication.json').read_text())
    code=r'''
from pathlib import Path
from contextlib import closing
import hashlib,json,sqlite3,subprocess,time
p=json.load(__import__('sys').stdin);backup=Path(p['backup'])
assert backup.parent==Path('/root') and backup.name.startswith('tio-before-gameplay-xml-client-')
assert not (backup/'before-restart.sqlite3').exists()
assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip()
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'before-restart.sqlite3')) as target:
 for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):assert not source.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone()
 source.backup(target);assert target.execute('pragma integrity_check').fetchone()==('ok',)
 before=source.execute('select count(*) from accounts').fetchone()[0]
for n,row in p['server_files'].items():assert hashlib.sha256((Path('/opt/tio-emulator')/n).read_bytes()).hexdigest()==row['after']
subprocess.run(['systemctl','restart','tio-server'],check=True);time.sleep(2)
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 assert db.execute('pragma integrity_check').fetchone()==('ok',)
 assert db.execute('select count(*) from accounts').fetchone()[0]==before
r=dict(passed=True,service='active',clean_restart=True,reason='Refresh cached battle snapshot rules digest after weapon catalogue change',backup=str(backup/'before-restart.sqlite3'),accounts_preserved=before,database_restored=False)
(backup/'restart.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
'''
    result=remote(code,receipt);(OUT/'restart.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','publish','restart'));args=p.parse_args();globals()[args.mode]()
