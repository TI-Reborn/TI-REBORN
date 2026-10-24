"""Validate/deploy only the reviewed flame files over the inspected live base."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
from tools.deploy_awp_scope_20261019 import REMOTE
WORK=ROOT/'work/flamethrower-implementation-20261021'
OUT=ROOT/'reports/flamethrower-implementation-20261021'
FILES=('tio/combat.py','tio/flamethrower.py','tio/protocol/flame_stream.py','server/battle_events.py')
MODULES=('test_flamethrower','test_area_fire','test_special_items','test_shared_special_items',
         'test_floor_fire','test_battle_events','test_visibility',
         'test_battle_crash_recovery','test_ranked','test_weapon_proficiency')
def main(mode):
 files={}
 for n in FILES:
  if n!='tio/combat.py':
   p=WORK/'candidate'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
  before=WORK/'baseline'/n;raw=(WORK/'candidate'/n).read_bytes()
  files[n]=dict(before=hashlib.sha256(before.read_bytes()).hexdigest() if before.exists() else None,
                after=hashlib.sha256(raw).hexdigest(),raw=base64.b64encode(raw).decode())
 deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text(encoding='utf-8')
 deployer=deployer.replace('KEEP_TABLES=',"SCOPES['flame-stream']=frozenset("+repr(FILES)+")\nKEEP_TABLES=")
 request=dict(mode=mode,files=files,deployer=deployer)
 if mode=='validate':
  buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w:gz') as a:
   a.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
   for n in ('evidence/special_items_native.json','evidence/battle_item_native.json'):a.add(ROOT/n,arcname=n)
  request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules=MODULES)
 source=REMOTE.replace('awp-scope-20261019','flame-stream-20261021').replace('awp-scope','flame-stream')
 # Long regression batches are isolated; no hosted player database is opened.
 source=source.replace('timeout=240','timeout=360')
 r=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+source,capture_output=True,encoding='utf-8',timeout=420)
 if r.returncode:raise RuntimeError(r.stderr[-4000:])
 result=json.loads(r.stdout);(OUT/('remote-checks.json' if mode=='validate' else 'deployment.json')).write_text(json.dumps(result,indent=2))
 print(json.dumps(result));assert result['passed']
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
