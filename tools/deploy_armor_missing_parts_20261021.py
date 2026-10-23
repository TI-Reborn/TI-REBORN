"""Use the existing backed-up catalog transaction with an exact semantic patch."""
import argparse,ast,base64,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.armor_missing_parts_20261021 import OUT,patch,validate
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
tree=ast.parse((ROOT/'tools/armor_fit_live_catalog_20261021.py').read_text())
CODE=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CODE' for t in n.targets))).replace('tio-before-armor-catalog-','tio-before-armor-hands-')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('inspect','deploy'));mode=p.parse_args().mode
 if mode=='inspect':
  assert not (OUT/'hosted-items-before.xml').exists()
  r=remote(CODE,dict(mode='inspect'));raw=base64.b64decode(r.pop('xml'));(OUT/'hosted-items-before.xml').write_bytes(raw);(OUT/'hosted-inspect.json').write_text(json.dumps(r,indent=2))
  s=remote(STATE,{});private=json.loads((ROOT/'.secrets/armor-missing-parts-20261021.json').read_text());s['protected']=private['provision']['protected_before'];s['accounts']=private['provision']['accounts_before'];s['protected_source']='Exact fingerprint captured immediately before creating these QA owners';(OUT/'hosted-before.json').write_text(json.dumps(s,indent=2));print(json.dumps(r))
 else:
  assert not (OUT/'deployment.json').exists();before=(OUT/'hosted-items-before.xml').read_bytes();after=patch(before);validate(before,after)
  r=remote(CODE,dict(mode='stage',before=base64.b64encode(before).decode(),after=base64.b64encode(after).decode()));(OUT/'hosted-items-fixed.xml').write_bytes(after);(OUT/'deployment.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
