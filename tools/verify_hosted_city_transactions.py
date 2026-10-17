"""Ordinary one-stock buy/replay/sell through live HTTP for the owned pair."""
from datetime import datetime,timezone
import json
from pathlib import Path
from tools.hosted_stage9_graphical_qa import private_fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP

ROOT=Path(__file__).resolve().parents[1]
CODE=OWNERSHIP+r'''
import shlex,urllib.request,uuid,hashlib
from pathlib import Path
key=None
for line in Path('/etc/tio-server/bank-api.env').read_text().splitlines():
 if line.startswith('BANK_SERVICE_KEY='):key=shlex.split(line.partition('=')[2])[0]
assert key
def call(route,value):
 req=urllib.request.Request('http://127.0.0.1:8082/v1/city/'+route,data=json.dumps(value).encode(),
  headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 with urllib.request.urlopen(req,timeout=5) as response:
  assert response.status==200;return json.loads(response.read(65537))
def other_wallets():
 with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as check:
  rows=[tuple(row) for row in check.execute('SELECT account,credits,gold FROM wallets ORDER BY account') if row[0] not in names]
  return hashlib.sha256(repr(rows).encode()).hexdigest()
initial=[]
for n in names:
 s=call('status',dict(username=n,slot=1));assert s['username']==n and s['character']==n and s['canOperate']
 assert 0<s['quotes']['stocks']['price']<=s['balances']['credits'];initial.append(s)
before=other_wallets();results=[]
for n,s in zip(names,initial):
 price=s['quotes']['stocks']['price'];before_balance=s['balances'];before_stock=s['securities']['stocks']
 for action,delta in (('stocks_buy',-price),('stocks_sell',price)):
  request=dict(username=n,slot=1,action=action,requestId=uuid.uuid4().hex,count=1,quote=price)
  accepted=call('action',request);assert accepted['replayed'] is False and accepted['receipt']['creditsDelta']==delta
  replay=call('action',request);assert replay['replayed'] is True
  assert replay['receipt']==accepted['receipt'] and replay['status']['balances']==accepted['status']['balances']
  assert replay['status']['securities']==accepted['status']['securities']
 final=call('status',dict(username=n,slot=1));assert final['balances']==before_balance and final['securities']['stocks']==before_stock
 results.append(dict(owned_character_verified=True,buy_sell_accepted=True,both_replays_no_second_charge=True,balances_restored_by_ordinary_sale=True))
assert before==other_wallets()
print(json.dumps(dict(passed=True,owned_pair=True,results=results,other_player_wallets_unchanged=True,
 sql_player_data_injected=False,database_restored=False,graphical_client_acceptance=False)))
'''

def main():
    target=ROOT/'reports/gameplay-completion/stage9-city/hosted-http-transactions.json'
    if target.exists():raise ValueError('Preserve prior transaction verification')
    fixture=private_fixture();result=fixture.remote(CODE,fixture.ownership_payload());result['utc']=datetime.now(timezone.utc).isoformat()
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
