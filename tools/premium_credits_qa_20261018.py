"""Two excluded hosted accounts; real client premium purchase and isolated TLS peer."""
import argparse,json,secrets,sys,time,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools import clan_icons_hosted_20261018 as q
from tio.protocol.asset_count import decode_asset_count
OUT=ROOT/'reports/premium-credits-20261018';PRIVATE=ROOT/'.secrets/premium-credits-20261018.json'
STATE=r'''
import json,sqlite3,time
from tio.rating_visibility import QA_LOGIN,excluded
assert all(QA_LOGIN.fullmatch(n) for n in request)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=[]
 for name in request:
  wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(name,)).fetchone()
  table=db.execute("SELECT 1 FROM sqlite_master WHERE name='premium_accounts'").fetchone()
  premium=db.execute('SELECT kind,expires FROM premium_accounts WHERE account=?',(name,)).fetchone() if table else None
  ledger=db.execute('SELECT offer,gold,credits FROM premium_purchases WHERE account=? ORDER BY id',(name,)).fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE name='premium_purchases'").fetchone() else []
  rows.append(dict(wallet=wallet,premium=premium,ledger=ledger,excluded=excluded(db,name)))
 print(json.dumps(dict(accounts=rows,now=int(time.time()))))
'''
def state():return q.remote(STATE,json.loads(PRIVATE.read_text())['names'])
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','launch','state','watch','cleanup'));args=p.parse_args()
 if args.mode=='provision':
  if PRIVATE.exists():data=json.loads(PRIVATE.read_text())
  else:
   prefix='qt'+secrets.token_hex(4)
   data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
   data['provision']=q.remote(q.CREATE,list(zip(data['names'],data['passwords'])));PRIVATE.write_text(json.dumps(data))
  code="""import sqlite3,json
from tio.locations import LocationStore,center
from tio.rating_visibility import QA_LOGIN,excluded
from tio.wallets import WalletStore
path='/var/lib/tio-server/reservation.sqlite3';LocationStore(path)
for name in request:
 assert QA_LOGIN.fullmatch(name)
 WalletStore(path).ensure(name)
with sqlite3.connect(path) as db:
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  LocationStore._save(db,name,3,*center(3))
print(json.dumps(dict(only_own_fixtures=True)))
"""
  q.remote(code,data['names']);v=state();assert all(r['wallet']==[3000,0] and r['excluded'] for r in v['accounts']);(OUT/'fixture-provisioning.json').write_text(json.dumps(v,indent=2));print(json.dumps(v))
 elif args.mode=='launch':
  from tools import clan_icons_gui_20261018 as gui
  gui.REPORT=OUT;gui.PRIVATE=PRIVATE;gui.SILVER='0678f9b242142142178ab0c4c804e778b0369004dc2a8f3f8459fe1adacb4c6b';sys.argv=[sys.argv[0],'launch'];gui.main()
 elif args.mode=='state':print(json.dumps(state()))
 elif args.mode=='cleanup':
  data=json.loads(PRIVATE.read_text());v=q.remote(q.CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False));(OUT/'fixture-cleanup.json').write_text(json.dumps(v,indent=2));PRIVATE.unlink();print(json.dumps(v))
 elif args.mode=='watch':
  data=json.loads(PRIVATE.read_text());clients=q.Clients(data);peer=clients.connect(1);events=[];print(json.dumps(dict(second_account_connected=True)),flush=True)
  try:
   for line in sys.stdin:
    op=line.strip()
    if op=='stop':break
    if op=='buy':
     peer.send(b'\xc8\x3a'+struct.pack('<II',3,1500));peer.send(b'\x70');fence=False;found=False
     for _ in range(2048):
      row=peer.receive();fence|=row==b'\x9e'
      if row[:2]==b'\xc8\x39':
       assets=decode_asset_count(row);found|=assets.credits==1500 and assets.gold==0 and bool(assets.optional_raw and assets.optional_raw[1]==3)
      if fence and found:break
     assert found and fence
    v=state();events.append(dict(op=op,state=v));print(json.dumps(v),flush=True)
  finally:clients.close();(OUT/'second-account-verification.json').write_text(json.dumps(events,indent=2))
if __name__=='__main__':main()
