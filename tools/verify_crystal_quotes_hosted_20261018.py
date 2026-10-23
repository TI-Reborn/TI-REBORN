"""Two excluded accounts; real public crystal quote/sale consistency."""
import argparse,json,secrets,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
saved=list(sys.path)
from tools.verify_game_operations_hosted import CREATE,CLEANUP,remote
sys.path[:]=saved
from tools.verify_area_fire_hosted_20261018 import Network
sys.path[:]=saved
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.item_list import decode_item_list
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
OUT=ROOT/'reports/crystal-quotes-20261018'
PRIVATE=ROOT/'.secrets/crystal-quotes-20261018.json'

PREPARE=r'''
import json,sqlite3
from dataclasses import replace
from pathlib import Path
from tio.rating_visibility import QA_LOGIN,excluded
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.locations import LocationStore,center
from tio.level_progression import FLOORS
from tio.crystal_market import CrystalMarket
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
path='/var/lib/tio-server/reservation.sqlite3'
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3],'0x8c4a07':115,'0x8c4ab1':115}))
for name in request:
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:assert excluded(db,name)
 items=(ItemRecord(91001,301,bytes(2),1,1,16,(350,350,350),bytes(4),None,bytes(3)),ItemRecord(91002,3,bytes(2),60,0,0,(1,1,1),bytes(4),None,bytes(3)))
 OwnedPetStore(path).ensure(name,raw,encode_item_list(1,items),human=True)
 SquadStore(path).assign(name,1,1)
 CrystalMarket(path)
 with sqlite3.connect(path) as db:
  LocationStore._save(db,name,2,*center(2))
  db.execute('INSERT INTO crystal_wallets VALUES (?,50000)',(name,))
print(json.dumps(dict(owned_fixtures_only=True,ranking_excluded=True,town=2)))
'''

def load():return json.loads(PRIVATE.read_text(encoding='utf-8'))
def provision():
 assert not PRIVATE.exists()
 prefix='qt'+secrets.token_hex(4);data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
 data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])));PRIVATE.write_text(json.dumps(data),encoding='utf-8')
 report=remote(PREPARE,data['names']);(OUT/'fixture-provisioning.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

STATE=r'''
import json,sqlite3
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 prizes={r['id']:r for r in json.load(open('config/achievements.json'))['records']}
 bonuses=[]
 for name in request:
  total=0
  for identity,position in db.execute('SELECT id,position FROM achievement_prizes WHERE account=? AND delivered=1',(name,)):
   row=prizes[identity];choices=list(row['prizes'])
   if row.get('temporary_credits'):choices.append(dict(kind='credits',value=row['temporary_credits']))
   prize=choices[position]
   if prize['kind']=='credits':total+=prize['value']
  bonuses.append(total)
 print(json.dumps(dict(bonuses=bonuses,market=db.execute('SELECT rate,updated FROM crystal_market WHERE id=1').fetchone(),history=db.execute('SELECT id,observed,rate FROM crystal_quote_history ORDER BY id').fetchall(),sales=db.execute('SELECT id,amount,credits,rate,sold FROM crystal_sales WHERE account IN (?,?) ORDER BY id',request).fetchall(),other_sales=db.execute('SELECT count(*),coalesce(max(id),0),coalesce(sum(amount),0) FROM crystal_sales WHERE account NOT IN (?,?)',request).fetchone(),wallets=[db.execute('SELECT credits FROM wallets WHERE account=?',(n,)).fetchone()[0] for n in request],crystals=[db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(n,)).fetchone()[0] for n in request])))
'''

RESTORE=r'''
import sqlite3,json
names=request['names'];before=request['before'];after=request['after']
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3',timeout=15) as db:
 db.execute('BEGIN IMMEDIATE')
 assert list(db.execute('SELECT rate,updated FROM crystal_market WHERE id=1').fetchone())==after['market'],'Market moved; do not overwrite live activity'
 assert [list(r) for r in db.execute('SELECT id,observed,rate FROM crystal_quote_history ORDER BY id')]==after['history'],'History moved; do not overwrite live activity'
 assert list(db.execute('SELECT count(*),coalesce(max(id),0),coalesce(sum(amount),0) FROM crystal_sales WHERE account NOT IN (?,?)',names).fetchone())==before['other_sales'],'Another player traded; do not restore shared state'
 own=list(db.execute('SELECT id,amount,credits,rate,sold FROM crystal_sales WHERE account IN (?,?) ORDER BY id',names))
 assert [list(r) for r in own]==after['sales'] and len(own)==2 and sum(r[1] for r in own)==100000
 # Remove only the economic effect of the two artificial QA sales. All
 # existing market samples are restored byte-for-byte; no database restore.
 db.execute('UPDATE crystal_market SET rate=?,updated=? WHERE id=1',before['market'])
 db.execute('DELETE FROM crystal_quote_history')
 db.executemany('INSERT INTO crystal_quote_history(id,observed,rate) VALUES (?,?,?)',before['history'])
 assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
print(json.dumps(dict(passed=True,own_sales_only=True,concurrent_activity_guard=True,previous_quote_history_preserved=True)))
'''

def run():
 data=load();net=Network(data);report=dict(passed=False,graphical_clients=False,public_tls=True,checks={})
 def quote(i):
  rows=net.command(i,b'\xb0\x21',expected=b'\xb0\x1f')
  rows+=net.command(i)
  caption=struct.unpack_from('<f',[p for p in rows if p[:2]==b'\xb0\x20'][-1],2)[0]
  raw=[p for p in rows if p[:2]==b'\xb0\x1f'][-1];n=struct.unpack_from('<h',raw,2)[0]
  points=tuple(struct.unpack_from('<4f',raw,4+16*j) for j in range(n))
  assert points and points[0]==(caption,)*4
  return dict(caption=caption,display_right=points[0][0],display_left=points[-1][0],points=n)
 try:
  for i in (0,1):net.connect(i)
  initial=[quote(0),quote(1)];before=remote(STATE,data['names'])
  data['market_before']=before;PRIVATE.write_text(json.dumps(data))
  report['initial']=initial;report['checks']['both_real_accounts_graph_right_equals_native_caption']=True
  for i in (0,1):
   net.command(i,b'\xb0\x1d'+struct.pack('<i',50000),expected=b'\xb0\x1f')
   refreshed=quote(1-i)
   report.setdefault('peer_after_sale',[]).append(refreshed)
  after=remote(STATE,data['names']);data['market_after']=after;PRIVATE.write_text(json.dumps(data))
  assert len(after['sales'])==2 and after['crystals']==[0,0]
  prior=before['market'][0]
  updated=before['market'][1]
  for row in after['sales']:
   _,amount,credits,rate,sold=row
   steps=max(0,(sold-updated)//600);prior+=steps*100000;updated+=steps*600
   assert rate==prior and amount==50000 and credits==amount*rate//10000000
   prior-=amount
  assert after['market'][0]==prior and before['other_sales']==after['other_sales']
  assert after['wallets']==[before['wallets'][i]+after['sales'][i][2]+after['bonuses'][i]-before['bonuses'][i] for i in (0,1)]
  report['checks']['two_maximum_sales_decrease_shared_rate_0_005_each']=True
  report['checks']['payout_uses_pre_sale_rate_and_inventory_is_account_scoped']=True
  report['sales']=[dict(amount=r[1],credits=r[2],price=r[3]/10000000) for r in after['sales']]
  report['market_compensation']=remote(RESTORE,dict(names=data['names'],before=before,after=after))
  data['market_restored']=True;PRIVATE.write_text(json.dumps(data))
  report['passed']=True
 finally:
  net.close();(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))

def cleanup():
 data=load();assert data.get('market_restored'), 'Compensate only owned QA sales before fixture cleanup'
 result=remote(CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
 (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));PRIVATE.unlink();print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup'));a=p.parse_args();globals()[a.mode]()
