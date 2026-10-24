"""Reuse the audited two-account clan fixture workflow for roster QA."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import clan_icons_hosted_20261018 as q
q.OUT=ROOT/'reports/clan-crest-projections-20261018';q.PRIVATE=ROOT/'.secrets/clan-crest-projections-20261018.json'
if __name__=='__main__':
 mode=sys.argv[1]
 if mode=='provision':

  if not q.PRIVATE.exists():q.provision()
  data=json.loads(q.PRIVATE.read_text());clients=q.Clients(data)
  try:
   clients.connect(0);clients.command(0,q.encode_upload((ROOT/'reports/clan-icons-20261018/clan-normalized.bmp').read_bytes()))
   current=q.state(data);assert current['crest']>0 and current['wallets'][0]==2000
   (q.OUT/'fixture-icon.json').write_text(json.dumps(current,indent=2));print(json.dumps(current))
  finally:clients.close()
  code="""import json,sqlite3
from tio.locations import LocationStore,center
from tio.rating_visibility import QA_LOGIN,excluded
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  LocationStore._save(db,name,19,*center(19))
print(json.dumps(dict(own_accounts_moved_to_training=True)))
"""
  print(json.dumps(q.remote(code,data['names'])))
 elif mode=='cleanup':q.cleanup()
 elif mode=='launch':
  from tools import clan_icons_gui_20261018 as gui
  gui.PRIVATE=q.PRIVATE;gui.REPORT=q.OUT;sys.argv=[sys.argv[0],'launch'];gui.main()
