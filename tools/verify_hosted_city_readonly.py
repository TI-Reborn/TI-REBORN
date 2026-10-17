"""Read actual private city HTTP for the retained owned pair; no mutations."""
from datetime import datetime, timezone
import json
from pathlib import Path
from tools.hosted_stage9_graphical_qa import private_fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP

ROOT=Path(__file__).resolve().parents[1]
CODE=OWNERSHIP+r'''
import urllib.request,urllib.error,shlex
from pathlib import Path
key=None
for line in Path('/etc/tio-server/bank-api.env').read_text().splitlines():
 if line.startswith('BANK_SERVICE_KEY='):key=shlex.split(line.partition('=')[2])[0]
assert key
results=[]
for port in (8082,8083):
 for n in data['names']:
  req=urllib.request.Request('http://127.0.0.1:'+str(port)+'/v1/city/status',
    data=json.dumps(dict(username=n,slot=1)).encode(),
    headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
  with urllib.request.urlopen(req,timeout=5) as response:
   assert response.status==200
   value=json.loads(response.read(65537));assert value['username']==n and value['character']==n
   assert value['slot']==1 and value['city']['id']==3 and value['canOperate']
   results.append(dict(port=port,owned_character_verified=True,city=value['city']['id'],
      canOperate=value['canOperate'],items=len(value['items']),marks=len(value['marks']),
      credit_balance_available=type(value['balances']['credits']) is int,version1_fields=len(value)))
 req=urllib.request.Request('http://127.0.0.1:'+str(port)+'/v1/city/status',data=b'{}',headers={'Content-Type':'application/json'})
 try:urllib.request.urlopen(req,timeout=5);raise AssertionError('Unauthenticated city access')
 except urllib.error.HTTPError as error:assert error.code==401
print(json.dumps(dict(passed=True,owned_pair=True,results=results,unauthenticated_status=401,
 hosted_data_mutated=False,graphical_client_acceptance=False)))
'''

def main():
    target=ROOT/'reports/gameplay-completion/stage9-city/hosted-readonly-http.json'
    if target.exists():raise ValueError('Preserve prior proof')
    fixture=private_fixture();result=fixture.remote(CODE,fixture.ownership_payload())
    result['utc']=datetime.now(timezone.utc).isoformat()
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
