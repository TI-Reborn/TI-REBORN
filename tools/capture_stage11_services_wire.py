"""Synthetic DTO fixtures from exact frozen public stage11-r5, never player saves."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/gameplay-followup/stage34-portal-integration'
FROZEN=ROOT/'reports/gameplay-completion/stage11-warehouse-services-r5'

SCRIPT=r'''
from contextlib import closing
import json,sqlite3,sys
from unittest.mock import patch
from urllib.request import Request,urlopen
sys.path.insert(0,'tests')
sys.stdout.reconfigure(encoding='utf-8')
import test_city_operations as fixture
from server.city_services import CityServices,validate
from server.city_operations import CityError
from server.city_http import CityHTTP
from server.bank_gateway import create_app
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.db_transaction import transaction
from tio.protocol.pet_info import decode_pet_info

case=fixture.CityOperationsTests(methodName='runTest');case.setUp()
try:
    manager=CityServices(case.router,operations=case.ops);case.router._city_services=manager
    manager.helper.clock=lambda:case.now
    with closing(sqlite3.connect(case.path)) as db:
        template=db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
    hire=HireStore(case.path,CityCatalogs(fixture.fixture.ROOT/'config/city_catalogs.json'),template)
    human=decode_pet_info(hire.hire('alice',2)[0],human_equipment=True).fields['0x8c43eb']
    dog=decode_pet_info(hire.hire('alice',3)[0],human_equipment=False).fields['0x8c43eb']
    status=lambda username='alice',slot=1:manager.status(dict(username=username,slot=slot))
    states=[dict(label='active-owned',value=status()),dict(label='empty-owned-slot',value=status(slot=5))]
    replies=[];requests=[]
    def operation(action,nonce,**fields):
        data=dict(username='alice',slot=1,action=action,requestId=nonce,**fields)
        first=manager.action(data);again=manager.action(data)
        assert first['replayed'] is False and again['replayed'] is True
        assert first['receipt']==again['receipt']
        assert set(first['receipt'])=={'requestId','action','creditsDelta','goldDelta'}
        requests.append(data);replies.extend([dict(label=action,value=first),dict(label=action+'-replay',value=again)])
        return first
    bad=[]
    for prefix in ('_','-'):
        data=dict(username='alice',slot=1,action='service_rename',requestId=prefix+'b'*15,petId=1,newName='WireAlice')
        before=case.rows()
        try:validate(data,action=True);accepted=True
        except CityError:accepted=False
        try:manager.action(data)
        except CityError as error:bad.append(dict(request=data,publicValidatorAccepted=accepted,actionAccepted=False,error=error.code,status=error.status))
        else:raise AssertionError('Expected real helper nonce rejection')
        assert case.rows()==before
    for nonce in ('a'*16,'b'*64,'176b8c01-5a10-4c3a-ab25-8f1c924e7581'):
        operation('service_rename',nonce,petId=1,newName='WireAlice')
    operation('service_rename','wire-recruit-rename-0001',petId=human,newName='Новый Боец')
    dismissed=operation('service_dismiss','wire-dog-dismiss-0001',petId=dog)
    due=next(p['dismissAt'] for p in dismissed['status']['services']['pets'] if p['petId']==dog)
    assert type(due) is int and due==case.now+172800
    states.append(dict(label='pending-dismissal',value=status()))
    case.now=due
    completed=manager.helper.finalize_due('alice',allowed=True);assert dog in completed['completed']
    states.append(dict(label='pending-dogmeat',value=status()))
    operation('service_claim_dogmeat','wire-dogmeat-claim-0001',dismissedPetId=dog,petId=human)
    with transaction(case.path) as db:db.execute("UPDATE wallets SET credits=50000 WHERE account='alice'")
    operation('warehouse_purchase','wire-warehouse-buy-0001',service=3,wanted=1,expectedClan=1)
    states.append(dict(label='shared-clan-expansion-peer',value=status('bob')))
    case.router.team_arena.private['alice']=(None,None)
    states.append(dict(label='busy-owned-character',value=status()))
    case.router.team_arena.private.clear()
    with transaction(case.path) as db:db.execute("DELETE FROM clan_members WHERE account='bob'")
    states.append(dict(label='unclanned-character',value=status('bob')))
    client=create_app(case.path,fixture.KEY).test_client()
    service=CityHTTP(case.router,fixture.KEY,port=0,operations=case.ops).start()
    original=urlopen
    def transport(request,timeout):
        assert request.full_url.startswith('http://127.0.0.1:8083/v2/services/')
        forwarded=Request(request.full_url.replace(':8083/',':'+str(service.http.server_port)+'/'),data=request.data,headers=dict(request.headers),method='POST')
        return original(forwarded,timeout=timeout)
    try:
        with patch('urllib.request.urlopen',side_effect=transport):
            response=client.post('/v2/services/status',json={'username':'alice','slot':1},headers={'Authorization':'Bearer '+fixture.KEY})
            assert response.status_code==200;states.append(dict(label='real-private-http-status',value=response.json))
            response=client.post('/v2/services/action',json=requests[-1],headers={'Authorization':'Bearer '+fixture.KEY})
            assert response.status_code==200 and response.json['replayed'] is True
            replies.append(dict(label='real-private-http-replay',value=response.json))
    finally:service.close()
    print(json.dumps(dict(version=1,states=states,replies=replies,requests=requests,nonceMismatch=bad),ensure_ascii=False))
finally:case.doCleanups()
'''


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def pins():return {p.relative_to(FROZEN/'runtime').as_posix():sha(p) for p in (FROZEN/'runtime').rglob('*') if p.is_file()}


def main():
    global FROZEN
    parser=argparse.ArgumentParser();parser.add_argument('--revision',choices=('r5','r6'),default='r6')
    revision=parser.parse_args().revision;FROZEN=ROOT/('reports/gameplay-completion/stage11-warehouse-services-'+revision)
    output=REPORT/('runtime/web/tests/fixtures/stage11-services-'+revision+'.json')
    proof=REPORT/('services-wire-'+revision+'-proof.json')
    if output.exists() or proof.exists():raise ValueError('Preserve previous synthetic fixtures')
    before=pins();manifest=json.loads((FROZEN/'candidate-manifest.json').read_text(encoding='utf-8'))
    for name,entry in manifest['files'].items():
        if before[name]!=entry['sha256']:raise ValueError('Frozen stage11 source changed: '+name)
    with tempfile.TemporaryDirectory(prefix='stage11-wire-',dir=REPORT) as folder:
        temp=Path(folder);shutil.copytree(FROZEN/'runtime',temp,dirs_exist_ok=True)
        shutil.copytree(ROOT/'tests',temp/'tests',ignore=shutil.ignore_patterns('__pycache__'))
        env={key:value for key,value in os.environ.items() if key.upper() in ('PATH','SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','USERPROFILE','LOCALAPPDATA')}
        result=subprocess.run([str(ROOT/'data/registration-check-env/Scripts/python.exe'),'-c',SCRIPT],cwd=temp,
                              env=env,capture_output=True,encoding='utf-8',errors='replace',timeout=60)
    log=REPORT/('services-wire-'+str(1+len(tuple(REPORT.glob('services-wire-*.log'))))+'.log')
    log.write_text(result.stderr,encoding='utf-8')
    if result.returncode:
        print(result.stderr);raise SystemExit(result.returncode)
    value=json.loads(result.stdout);unchanged=pins()==before
    if not unchanged:raise ValueError('Frozen stage11 source changed during capture')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    proof.write_text(json.dumps(dict(version=1,utc=datetime.now(timezone.utc).isoformat(),passed=True,
        stage11_manifest_sha256=sha(FROZEN/'candidate-manifest.json'),source_sha256=before,source_unchanged=unchanged,
        syntheticAccounts=['alice','bob'],statusFixtures=len(value['states']),actionFixtures=len(value['replies']),
        receiptBoundaries=[16,36,64],noncePolicy='Alnum first; frozen r6 wrapper matches helper and new portal schema',
        dataSha256=sha(output),log=log.name,playerDataOpened=False,hostedChanges=False,privateHTTP='real bound ephemeral loopback core plus Flask test proxy'),
        indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,status_fixtures=len(value['states']),action_fixtures=len(value['replies']),source_unchanged=unchanged)))


if __name__=='__main__':main()
