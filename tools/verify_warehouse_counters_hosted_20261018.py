"""Two owned excluded TLS accounts; warehouse transfers and resource counters."""
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
OUT=ROOT/'reports/warehouse-counters-20261018'
PRIVATE=ROOT/'.secrets/warehouse-counters-20261018.json'

PREPARE=r'''
import json,sqlite3
from dataclasses import replace
from pathlib import Path
from tio.rating_visibility import QA_LOGIN,excluded
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.locations import LocationStore,center
from tio.level_progression import FLOORS
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.warehouse import WarehouseStore
from tio.wallets import WalletStore
path='/var/lib/tio-server/reservation.sqlite3'
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3],'0x8c4a07':115,'0x8c4ab1':115}))
def item(i,t,count=1,current=1,maximum=None,equip=0):
 m=current if maximum is None else maximum
 return ItemRecord(i,t,bytes(2),count,equip,16 if equip else 0,(current,m,m),bytes(4),None,bytes(3))
for index,name in enumerate(request):
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  assert not db.execute('SELECT 1 FROM owned_pets WHERE account=?',(name,)).fetchone()
 OwnedPetStore(path).ensure(name,raw,encode_item_list(1,(item(9001,301,current=50,maximum=350,equip=1),)),human=True)
 SquadStore(path).assign(name,1,1);locations=LocationStore(path);WarehouseStore(path);WalletStore(path).ensure(name)
 entries=(item(1001,30,3 if index==0 else 7),item(1002,17,current=328,maximum=600),item(1003,18,current=612,maximum=1200),item(1004,19,current=3600)) if index==0 else (item(2001,30,7),item(2002,18,current=1200))
 with sqlite3.connect(path) as db:
  LocationStore._save(db,name,3,*center(3))
  for i in entries:
   db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',(name,i.instance_id,encode_item_list(0,(i,))))
   db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?)',(name,i.instance_id,'city',3,'owned-counter-qa'))
  db.execute('INSERT INTO crystal_wallets(account,amount) VALUES (?,?) ON CONFLICT(account) DO UPDATE SET amount=excluded.amount',(name,71+index))
  db.execute('INSERT INTO bank_securities(account,bonds,stocks) VALUES (?,?,?) ON CONFLICT(account) DO UPDATE SET bonds=excluded.bonds,stocks=excluded.stocks',(name,72+index,73+index))
  db.execute('INSERT INTO range_accounts(account,used_day,golden) VALUES (?,-1,?) ON CONFLICT(account) DO UPDATE SET used_day=-1,golden=excluded.golden',(name,2+index))
print(json.dumps(dict(owned_fixtures_only=True,ranking_excluded=True,expected=[[3,4540,73,72,71,2,1],[7,1200,74,73,72,3,1]])))
'''

def load():return json.loads(PRIVATE.read_text(encoding='utf-8'))
def values(a):return [a.unknown_u32_09,a.unknown_u32_08,a.spectra_stock,a.spectra_bonds,a.spectra_crystals,a.gold_slug,a.slug]
def assets(net,i):
 rows=net.command(i,b'\xb8\x11',expected=b'\xc8\x39')
 rows+=net.command(i)
 return decode_asset_count([r for r in rows if r[:2]==b'\xc8\x39'][-1])

def provision():
 assert not PRIVATE.exists()
 prefix='qt'+secrets.token_hex(4);data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
 data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])));PRIVATE.write_text(json.dumps(data),encoding='utf-8')
 report=remote(PREPARE,data['names']);(OUT/'fixture-provisioning.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

def run():
 data=load();net=Network(data);report=dict(passed=False,graphical_clients=False,public_tls=True,checks={})
 try:
  for i in (0,1):net.connect(i)
  initial=[values(assets(net,i)) for i in (0,1)]
  assert initial==[[3,4540,73,72,71,2,1],[7,1200,74,73,72,3,1]],initial
  report['initial']=initial;report['checks']['all_seven_values_and_account_isolation']=True
  def transfer(first=(),second=()):
   return net.command(0,encode_warehouse_transfer(WarehouseTransfer(0,1,first,second)),expected=b'\xc8\x39')
  transfer(second=((1001,1),(1002,1)))
  after=values(assets(net,0));assert after[:2]==[2,4212],after
  assert values(assets(net,1))==initial[1]
  report['checks']['native_6b_decrements_header_and_keeps_other_account_private']=True
  net.command(0,b'\xc2\x03'+struct.pack('<II',1,9001),expected=b'\x30')
  rows=net.command(0,b'\x2f\x01\0\x01\0\0\0',expected=b'\x30')
  bag=decode_item_list([r for r in rows if r[0]==0x30][-1])[1]
  kit=next(i for i in bag if i.template_id==17);upgrade=next(i for i in bag if i.template_id==30)
  assert kit.unknown_words[0]==37
  transfer(first=((kit.instance_id,1),(upgrade.instance_id,1)))
  final=values(assets(net,0));assert final[:2]==[3,4249],final
  report['checks']['repair_consumes291_and_redeposit_counts_remaining37']=True
  rows=net.command(0,b'\x69\0',expected=b'\x6a')
  entries=decode_warehouse_list([r for r in rows if r[0]==0x6a][-1])[3]
  assert sum(i.durability*i.count for i in entries if i.template_id in (17,18,19))==4249
  assert sum(i.count for i in entries if i.template_id==30)==3
  report['checks']['header_equals_authoritative_warehouse_list']=True
  report['final']=final
 finally:net.close()
 # Genuine reconnect, re-request the server counters; no in-process cache.
 net=Network(data)
 try:
  for i in (0,1):net.connect(i)
  assert values(assets(net,0))==report['final'] and values(assets(net,1))==initial[1]
  report['checks']['saved_values_survive_authenticated_reconnect']=True;report['passed']=True
 finally:net.close();(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))

def cleanup():
 data=load();result=remote(CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
 (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));PRIVATE.unlink();print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup'));a=p.parse_args();globals()[a.mode]()
