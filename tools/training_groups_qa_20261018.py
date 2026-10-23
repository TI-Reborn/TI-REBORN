"""Owned, excluded hosted accounts for native group-list acceptance."""
import argparse,json,secrets,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_game_operations_hosted import CREATE,CLEANUP,remote
from tools.verify_training_base_20261018_hosted import PREPARE
OUT=ROOT/'reports/training-groups-20261018';PRIVATE=ROOT/'.secrets/training-groups-20261018.json'

def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','cleanup','launch'));args=p.parse_args()
 if args.mode=='provision':
  assert not PRIVATE.exists();names=['qt'+secrets.token_hex(4)+'a' for _ in range(2)];passwords=[secrets.token_urlsafe(24) for _ in names]
  provision=remote(CREATE,list(zip(names,passwords)));PRIVATE.write_text(json.dumps(dict(names=names,passwords=passwords,provision=provision)))
  r=remote(PREPARE,names);(OUT/'fixture-setup.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
 elif args.mode=='cleanup':
  data=json.loads(PRIVATE.read_text());r=remote(CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False));PRIVATE.unlink()
  (OUT/'fixture-cleanup.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
 else:
  from tools import training_base_gui_20261018 as gui
  gui.PRIVATE=PRIVATE;gui.REPORT=OUT
  gui.SILVER=json.loads((OUT/'baseline.json').read_text())['silver_sha256']
  sys.argv=[sys.argv[0],'launch'];gui.main()
if __name__=='__main__':main()
