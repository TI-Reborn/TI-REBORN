"""Validate against live code, back up live saves, publish a scoped avatar update."""
import argparse
import base64
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote
from tools.deploy_avatar_types import VALIDATE, DEPLOY
from deploy.client_generated_avatars import patch
FOLDER=ROOT/'reports/generated-avatars-20261013'
MODULES=('test_avatars','test_arena_roster','test_shared_team_arena','test_shared_wager_arena','test_shooting_range','test_battle_crash_recovery')


def inputs():
    inspected=json.loads((FOLDER/'inspection.json').read_text(encoding='utf-8'))
    return dict(expected={n:r['sha256'] for n,r in inspected['sources'].items()},
                sources={n:(FOLDER/'server-candidate'/n).read_text(encoding='utf-8') for n in inspected['sources']},resources={})


def validate():
    payload=inputs();buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('tests/__init__.py','')
        for p in (ROOT/'tests').glob('*.py'):archive.write(p,'tests/'+p.name)
        for n in ('special_items_native.json','battle_item_native.json','battle_move_native.json','move_request_native.json'):
            archive.write(ROOT/'evidence'/n,'evidence/'+n)
    payload.update(tests=base64.b64encode(buffer.getvalue()).decode(),modules=MODULES)
    code=VALIDATE.split('result=subprocess.run(')[0]+r'''
worker=stage/'run_tests.py'
worker.write_text("import subprocess,json,pathlib,os,time\n"+
 "start=time.monotonic()\n"+
 "r=subprocess.run("+repr([str(root/'.venv/bin/python'),'-m','unittest',*data['modules']])+",cwd="+repr(str(stage))+",text=True,capture_output=True,timeout=300,env={**os.environ,'PYTHONPATH':"+repr(str(stage)+':'+str(stage/'tests'))+"})\n"+
 "pathlib.Path("+repr(str(stage/'test-result.json'))+").write_text(json.dumps(dict(passed=r.returncode==0,stage="+repr(str(stage))+",output=r.stderr[-15000:],hosted_database_used=False,elapsed_seconds=time.monotonic()-start)))\n")
subprocess.Popen([str(root/'.venv/bin/python'),str(worker)],cwd=stage,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
print(json.dumps(dict(pending=True,stage=str(stage))))
'''
    result=remote(code,payload)
    (FOLDER/'pending-tests.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


def check():
    pending=json.loads((FOLDER/'pending-tests.json').read_text())
    result=remote(r'''
import json,sys,pathlib,time
d=json.load(sys.stdin);stage=pathlib.Path(d['stage']);p=stage/'test-result.json'
if p.exists():print(p.read_text())
else:
 running=False
 for process in pathlib.Path('/proc').iterdir():
  if not process.name.isdigit():continue
  try:
   args=(process/'cmdline').read_bytes().split(b'\0')
   if str(stage/'run_tests.py').encode() in args:running=True
  except (FileNotFoundError,PermissionError,ProcessLookupError):pass
 print(json.dumps(dict(pending=True,elapsed_seconds=time.time()-stage.stat().st_mtime)) if running else json.dumps(dict(passed=False,stage=str(stage),output='Validation worker stopped without a result (including test timeout)',hosted_database_used=False)))
''',pending)
    if not result.get('pending'):
        (FOLDER/'remote-tests.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


def deploy():
    assert json.loads((FOLDER/'remote-tests.json').read_text())['passed']
    proof=json.loads((FOLDER/'client-native.json').read_text());assert proof['passed']
    payload=inputs()
    assets={p.relative_to(FOLDER/'client').as_posix():p.read_bytes() for p in (FOLDER/'client').rglob('*') if p.is_file()}
    assert assets['silver.dll']==patch((FOLDER/'silver-source.dll').read_bytes())
    assert hashlib.sha256(assets['silver.dll']).hexdigest()==proof['candidate_sha256']
    before=(FOLDER/'previous-manifest.json').read_bytes();manifest=json.loads(before)
    catalog=json.loads(payload['sources']['config/avatars.json'])
    for row in catalog['avatars']:
        raw=base64.b64decode(row['jpeg_b64'])
        if row['asset'] in assets:assert assets[row['asset']]==raw
        else:assert next(r['sha256'] for r in manifest['files'] if r['path']==row['asset'])==hashlib.sha256(raw).hexdigest()
    for n,blob in assets.items():
        record=dict(path=n,size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),seed=False)
        row=next((r for r in manifest['files'] if r['path']==n),None)
        if n=='silver.dll':assert row is not None;row.update(record)
        else:assert row is None;manifest['files'].append(record)
    manifest['version']='2026.10.13.2'
    manifest['news']='Добавлены 6 новых бесплатных аватаров: ветеран, разведчик, рейнджер, медик, боевой пёс и шахтёр. Выбор доступен в Галерея → Обычные. Сохранённые аватары остаются доступны.'
    after=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (FOLDER/'manifest.json').write_bytes(after)
    payload.update(before=base64.b64encode(before).decode(),after=base64.b64encode(after).decode(),
                   assets={n:base64.b64encode(b).decode() for n,b in assets.items()})
    code=DEPLOY.replace("{'files','version'}","{'files','version','news'}").replace("('files','version')","('files','version','news')")
    code=code.replace("atomic(after,live/'manifest.json')","assert (live/'manifest.json').read_bytes()==prior,'Manifest changed before publication'\n atomic(after,live/'manifest.json')")
    code=code.replace('tio-before-avatar-types-','tio-before-generated-avatars-')
    result=remote(code,payload)
    (FOLDER/'deployment.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


def verify():
    manifest=(FOLDER/'manifest.json').read_bytes();origin='https://185.184.42.88/updates/'
    with urllib.request.urlopen(origin+'manifest.json',timeout=30) as response:assert response.read()==manifest
    names={'silver.dll',*[p.relative_to(FOLDER/'client').as_posix() for p in (FOLDER/'client').rglob('*') if p.is_file()]}
    checked={}
    for row in json.loads(manifest)['files']:
        if row['path'] not in names:continue
        with urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=30) as response:blob=response.read()
        assert len(blob)==row['size'] and hashlib.sha256(blob).hexdigest()==row['sha256']
        checked[row['path']]=row['sha256']
    result=remote(r'''
import json,hashlib,pathlib,sqlite3,subprocess,struct
from contextlib import closing
from tio.avatars import catalog,encode_catalog,image_packet,snapshot
data=json.load(__import__('sys').stdin)
for n,h in data['expected'].items():assert hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest()==h
records=list(struct.iter_unpack('<BIII',encode_catalog()[6:]))
assert [r[1] for r in records if r[0]==0]==list(range(10007,10013))
assert all(r[2]==0 for r in records)
for i in catalog():assert image_packet(i)[8:10]==b'\xff\xd8'
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 owners=[r[0] for r in db.execute('SELECT DISTINCT account FROM owned_pets')]
 counts={n:db.execute('SELECT count(*) FROM '+n).fetchone()[0] for n in ('accounts','battle_checkpoints','battle_settlement_jobs')}
for owner in owners:assert snapshot('/var/lib/tio-server/reservation.sqlite3',owner)[:2]==b'\xfc\1'
print(json.dumps(dict(passed=True,service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
 counts=counts,ordinary_avatars=6,catalog_images=12,owner_snapshots_checked=len(owners),integrity='ok',
 hosted_fixtures_created=False,graphical_clients_used=False)))
''',dict(expected={n:hashlib.sha256(s.encode('utf-8')).hexdigest() for n,s in inputs()['sources'].items()}))
    result.update(trusted_https=True,verified_files=checked)
    (FOLDER/'hosted-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('validate','check','deploy','verify'))
    globals()[parser.parse_args().command]()
