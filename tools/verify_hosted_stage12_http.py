"""Owner-bound stage12 read-only HTTP acceptance; root runs it after deployment.

No action endpoints, no-op receipts, financial changes, player provisioning or
fixtures are written. The retained two-account fixture proves QA ownership.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.hosted_stage9_graphical_qa_revision3 import private_fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP

FOLDER = ROOT / 'reports/gameplay-completion/stage12-release'
ENDPOINTS = ('/v1/ratings/status', '/v1/city/status', '/v2/services/status')

CODE = OWNERSHIP + r'''
import hashlib,shlex,time,urllib.request,urllib.error,uuid
from datetime import datetime,timezone
from pathlib import Path
from server.ratings_public import validate_response

assert len(names)==2
key=None
for line in Path('/etc/tio-server/bank-api.env').read_text().splitlines():
 if line.startswith('BANK_SERVICE_KEY='):key=shlex.split(line.partition('=')[2])[0]
assert key and 32<=len(key)<=512
started=time.monotonic();checks=[];failures=[];archive_coverage={};request_count=0
endpoints=('/v1/ratings/status','/v1/city/status','/v2/services/status')

def wallets():
 with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
  db.execute('PRAGMA query_only=ON')
  rows=db.execute('SELECT account,credits,gold FROM wallets ORDER BY account').fetchall()
  return dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest())

def call(port,path,value=None,*,raw=None,auth='valid',content_type='application/json',method='POST',json_required=True):
 global request_count
 assert port in (8082,8083) and path in endpoints and method in ('POST','GET')
 if time.monotonic()-started>32:raise AssertionError('bounded_http_deadline')
 if raw is None:raw=json.dumps(value,separators=(',',':')).encode()
 headers={'Content-Type':content_type}
 if auth!='absent':headers['Authorization']='Bearer '+(key if auth=='valid' else 'invalid-stage12-key')
 request=urllib.request.Request('http://127.0.0.1:'+str(port)+path,data=raw,headers=headers,method=method)
 try:reply=urllib.request.urlopen(request,timeout=3)
 except urllib.error.HTTPError as error:reply=error
 with reply:
  status=reply.status;body=reply.read(65537);mime=reply.headers.get_content_type()
 request_count+=1
 assert len(body)<=65536,'oversize_response'
 if json_required:
  assert mime=='application/json','unexpected_mimetype'
  parsed=json.loads(body)
  assert isinstance(parsed,dict),'nonobject_response'
 else:parsed=None
 return status,parsed

def reject(port,path,value,expected,code='invalid_request',**kwargs):
 status,result=call(port,path,value,**kwargs)
 assert status==expected,'incorrect_rejection_status'
 if result is not None:assert result=={'error':code},'unsafe_or_incorrect_rejection'
 checks.append(dict(kind='rejection',port=port,endpoint=path,status=status,code=code if result is not None else None))

before=wallets()
try:
 ratings_path=endpoints[0];city_path=endpoints[1];services_path=endpoints[2]
 for n in names:
  for fmt in ('pairs','wall'):
   current={}
   for port in (8082,8083):
    query=dict(username=n,format=fmt,scope=None,offset=0,limit=10)
    status,result=call(port,ratings_path,query);assert status==200
    validate_response(result,query);assert result['username']==n
    current[port]=result['ratings']
    checks.append(dict(kind='ratings_current',account=n,port=port,format=fmt,scope=result['ratings']['scope'],rows=len(result['ratings']['rows']),total=result['ratings']['total']))
   assert current[8082]==current[8083],'ratings_hops_differ'
   archived=next((s['id'] for s in current[8083]['seasons'] if s['state']=='archived'),None)
   now=datetime.now(timezone.utc);prior_year,prior_month=(now.year,now.month-1) if now.month>1 else (now.year-1,12)
   historical=archived or f'{prior_year:04d}-{prior_month:02d}'
   archive_coverage[fmt]=archive_coverage.get(fmt,False) or archived is not None
   for scope,offset in (('all',0),(historical,0),(None,10),('all',9990)):
    responses=[]
    for port in (8082,8083):
     query=dict(username=n,format=fmt,scope=scope,offset=offset,limit=10)
     status,result=call(port,ratings_path,query);assert status==200
     validate_response(result,query);dto=result['ratings'];responses.append(dto)
     if scope==archived and archived is not None:assert dto['archived'] and dto['seasonState']=='archived'
     checks.append(dict(kind='ratings_filter',account=n,port=port,format=fmt,scope=dto['scope'],offset=offset,rows=len(dto['rows']),total=dto['total'],seasonState=dto['seasonState'],existingArchive=scope==archived and archived is not None))
    assert responses[0]==responses[1],'ratings_filter_hops_differ'
  for port in (8082,8083):
   status,city=call(port,city_path,dict(username=n,slot=1));assert status==200
   status,services=call(port,services_path,dict(username=n,slot=1));assert status==200
   assert city['username']==services['username']==n and city['slot']==services['slot']==1
   assert city['character']==services['character']==n and services['version']==2
   assert city['characters']==services['characters'] and city['balances']==services['balances']
   assert city['canOperate']==services['canOperate'] and type(city['canOperate'])is bool
   assert city['conversion']['creditsPerGold']==100 and city['itemsLimit']==200 and city['marksLimit']==100
   assert services['services']['avatarsEnabled']is False and services['services']['avatars']==[]
   assert services['personalWarehouse']['policy']=='legacy_and_durable_overflow_preserved'
   assert services['personalWarehouse']['town']==city['city']['id']
   assert services['services']['renamePrices']==dict(mainGold=30,recruitCredits=3000)
   status,empty=call(port,services_path,dict(username=n,slot=5));assert status==200
   assert empty['character']is None and empty['canOperate']is False
   assert all(empty[k]is None for k in ('balances','services','personalWarehouse','clanWarehouse'))
   status,empty_city=call(port,city_path,dict(username=n,slot=5));assert status==200
   assert empty_city['character']is None and empty_city['canOperate']is False and empty_city['balances']is None
   checks.append(dict(kind='city_v1_services_v2',account=n,port=port,identity=True,balancesMatch=True,canOperate=city['canOperate'],emptySlotFenced=True,cityReason=city['city']['reason']))
 n=names[0];valid=dict(username=n,format='pairs',scope=None,offset=0,limit=10)
 missing='qa_absent_'+uuid.uuid4().hex[:12]
 with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
  assert not db.execute('SELECT 1 FROM accounts WHERE login=?',(missing,)).fetchone()
 for port in (8082,8083):
  for path in endpoints:
   value=valid if path==ratings_path else dict(username=n,slot=1)
   for auth in ('absent','invalid'):reject(port,path,value,401,'unauthorized',auth=auth)
   reject(port,path,dict(value,username=missing),404,'account_not_found')
  for field,value in (('format','duel'),('scope','current'),('scope','2026-13'),('scope',False),('offset',1),('offset',True),('offset',10000),('limit',20),('limit',True),('username','../account')):
   reject(port,ratings_path,dict(valid,**{field:value}),400)
  reject(port,ratings_path,dict(valid,owner=n),400)
  reject(port,ratings_path,{k:v for k,v in valid.items() if k!='format'},400)
  reject(port,ratings_path,valid,400,raw=b'{')
  reject(port,ratings_path,valid,400,raw=(json.dumps(valid)[:-1]+',"limit":10}').encode())
  reject(port,ratings_path,valid,413,raw=b' '*4097)
  reject(port,ratings_path,valid,415 if port==8082 else 400,content_type='text/plain')
  reject(port,ratings_path,valid,405,method='GET',json_required=False)
  for path in (city_path,services_path):
   reject(port,path,dict(username=n,slot=True),400)
   reject(port,path,dict(username=n,slot=6),400)
   reject(port,path,dict(username=n,slot=1,owner=n),400)
except Exception as error:
 # The traceback, response bodies, SQL rows and key never enter public proof.
 failures.append(dict(code='acceptance_check_failed',type=type(error).__name__))
finally:
 after=wallets()
 if before!=after:failures.append(dict(code='wallet_fingerprint_changed'))
 result=dict(version=1,passed=not failures,checks=checks,failures=failures,requests=request_count,
  walletFingerprints=dict(before=before,after=after),all_wallets_unchanged=before==after,
  owned_accounts=2,ports=[8082,8083],only_status_endpoints=True,action_endpoints_called=False,
  financial_mutations=False,sql_write_statements=False,sql_player_data_injected=False,
  existingArchiveVerified=archive_coverage,requestedArchiveAcceptanceComplete=all(archive_coverage.get(fmt,False) for fmt in ('pairs','wall')),
  limitations=[] if all(archive_coverage.get(fmt,False) for fmt in ('pairs','wall')) else ['No archived season exists for at least one format; historical-month filter verified without creating archives'],
  graphical_client_acceptance=False,portal_cookie_session_verified=False,
  source_sha256={name:hashlib.sha256(Path('/opt/tio-emulator',name).read_bytes()).hexdigest() for name in ('server/ratings_public.py','server/city_http.py','server/bank_gateway.py','server/city_operations.py','server/city_services.py')})
 print(json.dumps(result,separators=(',',':')))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',default='reports/gameplay-completion/stage12-release')
    parser.add_argument('--check-only',action='store_true',help='Compile the read-only script; do not open fixture or SSH')
    args=parser.parse_args()
    folder=Path(args.folder)
    if not folder.is_absolute():folder=ROOT/folder
    if folder.resolve()!=FOLDER.resolve():raise ValueError('Only the reviewed stage12 release evidence folder is accepted')
    compile(CODE,'stage12-http-acceptance','exec')
    if args.check_only:
        print(json.dumps(dict(prepared=True,remoteExecuted=False,endpoints=list(ENDPOINTS),scriptSha256=hashlib.sha256(CODE.encode()).hexdigest())))
        return
    target=folder/'hosted-http-acceptance.json'
    if target.exists():raise ValueError('Preserve previous acceptance proof')
    fixture=private_fixture()
    try:result=fixture.remote(CODE,fixture.ownership_payload())
    except Exception as error:
        result=dict(version=1,passed=False,verificationCompleted=False,errorType=type(error).__name__,
            all_wallets_unchanged=None,financial_mutations=False,only_status_endpoints=True)
    result['utc']=datetime.now(timezone.utc).isoformat()
    result['verifierSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['remoteCodeSha256']=hashlib.sha256(CODE.encode()).hexdigest()
    folder.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],proof=str(target.relative_to(ROOT)),
        all_wallets_unchanged=result.get('all_wallets_unchanged'),requests=result.get('requests'),
        existingArchiveVerified=result.get('existingArchiveVerified'))))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
