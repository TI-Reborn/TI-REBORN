"""Validate inspected hosting candidate, then back up and deploy only scope files."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.prepare_awp_scope_20261019 import sha
WORK=ROOT/'work/sniper-rifles-20261019';OUT=ROOT/'reports/sniper-rifles-20261019'
FILES=tuple(json.loads((OUT/'server-review.json').read_text()))
from tools.inspect_training_base_20261018 import SSH
from tools.deploy_stage4_economy import remote
from tools.publish_gameplay_xml_client import publisher

REMOTE=r'''
import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
root=Path('/opt/tio-emulator');sha=lambda b:hashlib.sha256(b).hexdigest()
folder=Path('/root/sniper-rifles-20261019');folder.mkdir(exist_ok=True)
baseline={}
for name,entry in request['files'].items():
 assert (sha((root/name).read_bytes()) if (root/name).is_file() else None)==entry['before'],name
 assert sha(base64.b64decode(entry['raw']))==entry['after'];baseline[name]=entry['before']
(folder/'baseline.json').write_text(json.dumps(baseline))
if request['mode']=='validate':
 stage=Path(tempfile.mkdtemp(prefix='tio-sniper-rifles-check-',dir='/opt'))
 for n in ('server','tio','tools','config','evidence'):shutil.copytree(root/n,stage/n,ignore=shutil.ignore_patterns('__pycache__'))
 for name,entry in request['files'].items():(stage/name).write_bytes(base64.b64decode(entry['raw']))
 with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request['tests']))) as tar:tar.extractall(stage,filter='data')
 run=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*request['modules'],'-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=240)
 result=dict(passed=run.returncode==0,hashes={n:v['after'] for n,v in request['files'].items()},stage=str(stage),log=run.stdout+run.stderr,isolated_database=True)
 (folder/'validation.json').write_text(json.dumps(result));print(json.dumps(result))
else:
 validation=json.loads((folder/'validation.json').read_text());assert validation['passed'] and validation['hashes']=={n:v['after'] for n,v in request['files'].items()}
 manifest={n:dict(before=v['before'],after=v['after']) for n,v in request['files'].items()}
 with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
  for n,raw in [(n,base64.b64decode(v['raw'])) for n,v in request['files'].items()]+[('manifest.json',json.dumps(manifest).encode())]:
   entry=tarfile.TarInfo(n);entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
 sys.argv=['deployer','--archive',str(folder/'patch.tar.gz'),'--sha256',sha((folder/'patch.tar.gz').read_bytes()),'--baseline',str(folder/'baseline.json'),'--backup','/root/tio-before-game-operations-sniper-rifles-20261019','--scope','sniper-rifles']
 if request.get('maintenance_restart'):sys.argv.append('--maintenance-restart')
 exec(compile(request['deployer'],'sniper-rifles-scoped-deployer','exec'),{'__name__':'__main__'})
'''

def run(mode):
    review=json.loads((OUT/'server-review.json').read_text())
    files={n:dict(**review[n],raw=base64.b64encode((WORK/'candidate'/n).read_bytes()).decode()) for n in FILES}
    deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text(encoding='utf-8')
    anchor='KEEP_TABLES='
    deployer=deployer.replace(anchor,'SCOPES[\'sniper-rifles\']=frozenset('+repr(FILES)+')\n'+anchor)
    request=dict(mode=mode,files=files,deployer=deployer,maintenance_restart='--maintenance-restart' in sys.argv)
    if mode=='validate':
        import unittest
        sys.path.insert(0,str(ROOT/'tests'))
        loader=unittest.TestLoader()
        item_tests=[t.id() for suite in loader.loadTestsFromName('test_battle_item_effects') for t in suite
            if not t.id().endswith('.test_catalog_extension_ids_checked_against_installed_and_server_catalogs')]
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as t:
            t.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
            for name in ('config/battle_item_catalog_extension.xml','evidence/battle_item_native.json'):t.add(ROOT/name,arcname=name)
        request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules=[
            'test_sniper_scope','test_weapon_effects','test_skills_fixture',*item_tests,
            'test_battle_item_visuals','test_visibility','test_battle_events'])
    r=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=300)
    if r.returncode:raise RuntimeError(r.stderr[-4000:])
    result=json.loads(r.stdout)
    (OUT/('remote-checks.json' if mode=='validate' else 'deployment.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result));assert result['passed']

def publish():
    assert json.loads((OUT/'deployment.json').read_text())['passed']
    old=(WORK/'manifest-before.json').read_bytes();manifest=json.loads(old)
    raw=(WORK/'client-items-candidate.xml').read_bytes()
    row=next(r for r in manifest['files'] if r['path']=='base/shared config/items.xml')
    before=row['sha256'];row.update(sha256=sha(raw),size=len(raw),seed=False)
    manifest['version']='2026.10.19.5';new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    result=remote(publisher().replace("'base/shared config/skills.xml','base/shared config/zones.xml'","'base/shared config/skills.xml','base/shared config/items.xml','base/shared config/zones.xml'"),dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),
        candidate=base64.b64encode(raw).decode(),base_sha256=before,path=row['path'],changed_ids=[],added_ids=[5013]))
    (OUT/'publication.json').write_text(json.dumps(result,indent=2));(OUT/'manifest.json').write_bytes(new)
    origin='https://185.184.42.88/updates/'
    assert urllib.request.urlopen(origin+'manifest.json',timeout=30).read()==new
    assert urllib.request.urlopen(origin+'blobs/'+sha(raw),timeout=30).read()==raw
    (OUT/'https-verification.json').write_text(json.dumps(dict(passed=True,trusted_https=True,version=manifest['version'],sha256=sha(raw)),indent=2))
    print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy','publish'));p.add_argument('--maintenance-restart',action='store_true');args=p.parse_args()
    publish() if args.mode=='publish' else run(args.mode)
