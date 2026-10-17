"""Read owned QA inventory and foreign-account fingerprints without secrets."""
import argparse,json
from datetime import datetime,timezone
from tools.deploy_gameplay_completion import ROOT
from tools.hosted_stage9_graphical_qa import private_fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP

CODE=OWNERSHIP+r'''
from contextlib import closing
import hashlib,sys
sys.path.insert(0,'/opt/tio-emulator')
from tio.protocol.item_list import decode_item_list
def record(i):return dict(instance=i.instance_id,template=i.template_id,count=i.count,equipped=i.equipped,slot=i.client_slot,durability=list(i.unknown_words))
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
 foreign={}
 for table in ('wallets','owned_pets','warehouse_items','character_locations'):
  rows=db.execute('SELECT * FROM '+table+' WHERE account NOT IN (?,?) ORDER BY account',names).fetchall()
  foreign[table]=dict(rows=len(rows),sha256=hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest())
 results=[]
 for index,n in enumerate(names):
  w=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(n,)).fetchone()
  pets=[dict(petId=key,items=[record(i) for i in decode_item_list(raw)[1]]) for key,raw in db.execute('SELECT pet_id,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(n,))]
  warehouse=[]
  for key,raw in db.execute('SELECT instance_id,item_packet FROM warehouse_items WHERE account=? ORDER BY instance_id',(n,)):
   item,=decode_item_list(raw)[1]
   place=db.execute('SELECT bucket,town,origin FROM warehouse_places WHERE account=? AND instance_id=?',(n,key)).fetchone()
   warehouse.append(dict(record(item),placement=list(place) if place else 'legacy'))
  town=db.execute('SELECT town_id FROM character_locations WHERE account=?',(n,)).fetchone()
  results.append(dict(accountIndex=index,credits=w[0],gold=w[1],town=town[0],pets=pets,warehouse=warehouse))
 print(json.dumps(dict(owned=True,accounts=results,foreign=foreign,readonly=True,integrity=db.execute('PRAGMA integrity_check').fetchone()[0])))
'''
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',required=True);args=parser.parse_args()
    target=(ROOT/args.report).resolve()
    if not target.is_relative_to(ROOT/'reports') or target.suffix!='.json' or target.exists():raise ValueError('Fresh report required')
    fixture=private_fixture();result=fixture.remote(CODE,fixture.ownership_payload());result['utc']=datetime.now(timezone.utc).isoformat()
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(readonly=True,integrity=result['integrity'],accounts=result['accounts'])))
if __name__=='__main__':main()
