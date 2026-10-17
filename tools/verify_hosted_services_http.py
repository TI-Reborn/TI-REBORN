"""Owner-bound Services V2 HTTP checks using ordinary free no-op receipts."""
from datetime import datetime,timezone
import json
from tools.deploy_gameplay_completion import ROOT
from tools.hosted_stage9_graphical_qa import private_fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP

CODE=OWNERSHIP+r'''
import hashlib,shlex,urllib.request,urllib.error,uuid
from pathlib import Path
key=None
for line in Path('/etc/tio-server/bank-api.env').read_text().splitlines():
 if line.startswith('BANK_SERVICE_KEY='):key=shlex.split(line.partition('=')[2])[0]
assert key
def call(port,version,kind,value):
 req=urllib.request.Request('http://127.0.0.1:'+str(port)+'/'+version+'/'+kind,data=json.dumps(value).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 with urllib.request.urlopen(req,timeout=5) as response:
  assert response.status==200;return json.loads(response.read(65537))
def wallets():
 with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
  return hashlib.sha256(repr(db.execute('SELECT account,credits,gold FROM wallets ORDER BY account').fetchall()).encode()).hexdigest()
before=wallets();results=[]
for n in names:
 for port in (8082,8083):
  s=call(port,'v2/services','status',dict(username=n,slot=1));assert s['version']==2 and s['username']==n and s['character']==n and s['canOperate']
  assert s['personalWarehouse']['capacity']==32 and s['personalWarehouse']['policy']=='legacy_and_durable_overflow_preserved'
  assert s['clanWarehouse'] is None and not s['services']['avatarsEnabled']
  empty=call(port,'v2/services','status',dict(username=n,slot=5));assert empty['services'] is None and not empty['canOperate']
  city=call(port,'v1/city','status',dict(username=n,slot=1));assert city['city']['id']==3 and city['canOperate']
  results.append(dict(port=port,owned_character_verified=True,capacity=32,legacy=s['personalWarehouse']['legacy'],empty_slot_fenced=True,city_v1_compatible=True))
 request=dict(username=n,slot=1,action='service_rename',requestId=uuid.uuid4().hex,petId=1,newName=n)
 first=call(8082,'v2/services','action',request);again=call(8082,'v2/services','action',request)
 assert first['replayed'] is False and again['replayed'] is True and first['receipt']==again['receipt']
 assert first['receipt']['creditsDelta']==first['receipt']['goldDelta']==0 and again['status']['character']==n
 assert set(first['receipt'])=={'requestId','action','creditsDelta','goldDelta'}
for port in (8082,8083):
 req=urllib.request.Request('http://127.0.0.1:'+str(port)+'/v2/services/status',data=b'{}',headers={'Content-Type':'application/json'})
 try:urllib.request.urlopen(req,timeout=3);raise AssertionError('Unauthenticated services access')
 except urllib.error.HTTPError as error:assert error.code==401
assert before==wallets()
print(json.dumps(dict(passed=True,results=results,owned_pair_free_rename_noop_receipt_replay=True,all_wallets_unchanged=True,unauthenticated_status=401,
 sql_player_data_injected=False,graphical_client_acceptance=False)))
'''

def main():
 target=ROOT/'reports/gameplay-completion/stage11-warehouse-services-r6/hosted-http-acceptance.json'
 if target.exists():raise ValueError('Preserve previous proof')
 fixture=private_fixture();result=fixture.remote(CODE,fixture.ownership_payload());result['utc']=datetime.now(timezone.utc).isoformat()
 target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
