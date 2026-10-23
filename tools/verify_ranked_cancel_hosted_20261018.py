"""Two owned excluded TLS accounts; native search cancellation and match race."""
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
OUT=ROOT/'reports/ranked-cancel-20261018'
PRIVATE=ROOT/'.secrets/ranked-cancel-20261018.json'

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
path='/var/lib/tio-server/reservation.sqlite3'
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3],'0x8c4a07':115,'0x8c4ab1':115}))
for name in request:
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:assert excluded(db,name)
 items=(ItemRecord(91001,301,bytes(2),1,1,16,(350,350,350),bytes(4),None,bytes(3)),ItemRecord(91002,3,bytes(2),60,0,0,(1,1,1),bytes(4),None,bytes(3)))
 OwnedPetStore(path).ensure(name,raw,encode_item_list(1,items),human=True)
 SquadStore(path).assign(name,1,1)
 with sqlite3.connect(path) as db:LocationStore._save(db,name,2,*center(2))
print(json.dumps(dict(owned_fixtures_only=True,ranking_excluded=True,town=2)))
'''

def load():return json.loads(PRIVATE.read_text(encoding='utf-8'))
def provision():
 assert not PRIVATE.exists()
 prefix='qt'+secrets.token_hex(4);data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
 data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])));PRIVATE.write_text(json.dumps(data),encoding='utf-8')
 report=remote(PREPARE,data['names']);(OUT/'fixture-provisioning.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

def run():
 data=load();net=Network(data);report=dict(passed=False,graphical_clients=False,public_tls=True,checks={})
 join=b'\xc6\x21'+bytes(2)+struct.pack('<III',1,1,0)+b'\0'
 try:
  for i in (0,1):net.connect(i)
  result=remote("import subprocess,json;n=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines());print(json.dumps(n))",None)
  report['background_connections']=max(0,result-2)
  report['checks']['reserved_qa_match_pool_isolated_from_real_players']=True
  for i in (0,1):
   rows=net.command(i,b'\xc6\x23')
   assert b'\xc6\x06' not in rows
  report['checks']['idle_cancel_keeps_native_selection']=True
  for _ in range(3):
   net.command(0,join,expected=b'\xc6\x03')
   rows=net.command(0,b'\xc6\x23',expected=b'\xc6\x06')
   assert b'\xc6\x06' in rows
   rows=net.command(0,b'\x69\0',expected=b'\x6a')
   assert any(p[:1]==b'\x6a' for p in rows)
  report['checks']['three_search_cancel_city_inventory_cycles']=True
  net.command(1,join,expected=b'\xc6\x03')
  net.command(0,b'\xc6\x23')
  # Cancelled A must stay in city; B must still be queued until its own cancel.
  assert not any(p[:1]==b'\x41' for p in net.received[0]+net.received[1])
  net.command(1,b'\xc6\x23',expected=b'\xc6\x06')
  net.command(1,b'\x69\0',expected=b'\x6a')
  report['checks']['cancel_does_not_affect_other_account_or_leave_ghost_opponent']=True
  for i in (0,1):net.command(i,join)
  for i in (0,1):
   if not any(p[:1]==b'\x41' for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
   net.command(i,b'\x36')
  state=remote(r'''
import json,sqlite3
from tio.battle_snapshot import loads
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(request[0],)).fetchone()
 assert row
 b=loads(row[1])[0]['battle'];assert {r[0] for r in b['reward_roster'].values()}==set(request)
 print(json.dumps(dict(match=row[0],finished=b['finished'],bots=bool(b['bots']))))
''',data['names'])
  assert not state['finished'] and not state['bots']
  data['matches']=[state['match']];PRIVATE.write_text(json.dumps(data))
  for i in (0,1):
   rows=net.command(i,b'\xc6\x23');assert b'\xc6\x06' not in rows
  report['checks']['late_close_cancel_does_not_forfeit_started_pvp']=True
  # Finish the owned match normally; no interrupted or manually removed battle.
  net.command(0,b'\x2a\x01')
  net.command(1,b'\x2a\x01')
  report['checks']['normal_exit_after_real_two_account_match']=True
  rows=net.command(0,b'\x69\0',expected=b'\x6a')
  report['checks']['city_available_after_battle']=any(p[:1]==b'\x6a' for p in rows)
  # An ordinary map movement must work after search cancellation.
  from tio.locations import center
  x,y=center(2)
  rows=net.command(0,b'\x1b'+struct.pack('<ii',x+35,y),expected=b'\x1d')
  assert any(p.startswith(b'\xf0\x61\0\0\0') for p in rows)
  report['checks']['leave_denver_after_cancel']=True
  report['passed']=True
 finally:
  net.close();(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))


def cleanup():
 data=load()
 assert remote("import sqlite3,json;d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True);print(json.dumps(d.execute('SELECT count(*) FROM battle_checkpoint_members WHERE account IN (?,?)',request).fetchone()[0]))",data['names'])==0, 'Finish own battle normally before cleanup'
 source=CLEANUP.replace("names=request['names'];", "matches=request.get('matches',[]);assert all(isinstance(m,str) and len(m)>20 for m in matches)\nnames=request['names'];")
 source=source.replace("  condition=' OR '.join(parts) if parts else '0';", "  if 'match_id' in columns and matches:parts.append('match_id IN ('+','.join('?' for _ in matches)+')');args+=matches\n  condition=' OR '.join(parts) if parts else '0';")
 result=remote(source,dict(matches=data.get('matches',[]),names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
 (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));PRIVATE.unlink();print(json.dumps(result))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup'));a=p.parse_args();globals()[a.mode]()
