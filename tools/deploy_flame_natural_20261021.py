"""Deploy only plume sampling; prove the existing damage functions unchanged."""
import argparse,ast,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
from tools.deploy_awp_scope_20261019 import REMOTE
WORK=ROOT/'work/flame-natural-20261021';OUT=ROOT/'reports/flame-natural-20261021'
NAME='tio/flamethrower.py';BASE='29bba9fb1834a649e54f9502fc386e27b6394d1f72518b815cbceaa0e41d0fec'
def main(mode):
 before=(WORK/'baseline/flamethrower.py').read_bytes();raw=(ROOT/NAME).read_bytes();assert hashlib.sha256(before).hexdigest()==BASE
 def function(body,name):return ast.dump(next(n for n in ast.parse(body).body if isinstance(n,ast.FunctionDef) and n.name==name))
 assert all(function(before,n)==function(raw,n) for n in ('cells','victims'))
 files={NAME:dict(before=BASE,after=hashlib.sha256(raw).hexdigest(),raw=base64.b64encode(raw).decode())}
 deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text(encoding='utf-8')
 deployer=deployer.replace('KEEP_TABLES=',"SCOPES['flame-natural']=frozenset(('tio/flamethrower.py',))\nKEEP_TABLES=")
 request=dict(mode=mode,files=files,deployer=deployer)
 if mode=='validate':
  buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w:gz') as archive:
   archive.add(ROOT/'tests',arcname='tests',filter=lambda m:None if '__pycache__' in Path(m.name).parts else m)
   for n in ('evidence/special_items_native.json','evidence/battle_item_native.json'):archive.add(ROOT/n,arcname=n)
  request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules=['test_flamethrower','test_area_fire','test_special_items','test_shared_special_items','test_floor_fire','test_battle_events','test_visibility','test_battle_crash_recovery','test_ranked','test_weapon_proficiency'])
 source=REMOTE.replace('awp-scope-20261019','flame-natural-20261021').replace('awp-scope','flame-natural').replace('timeout=240','timeout=360')
 run=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+source,capture_output=True,encoding='utf-8',timeout=420)
 if run.returncode:raise RuntimeError(run.stderr[-2500:])
 result=json.loads(run.stdout);assert result['passed'];result['damage_function_ast_unchanged']=True
 (OUT/('remote-checks.json' if mode=='validate' else 'deployment.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
