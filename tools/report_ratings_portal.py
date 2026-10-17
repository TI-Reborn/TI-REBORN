"""Tie the frozen ratings portal delivery to exact focused public test sources."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-followup/stage4-ratings/portal'
FINAL=FOLDER/'final'
CHECKED=FOLDER/'validation2'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(name,value):
    path=FINAL/name
    if path.exists():raise ValueError('Preserve earlier ratings portal report')
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def main():
    final=read(FINAL/'candidate-manifest.json');checked=read(CHECKED/'candidate-manifest.json')
    if {n:e['sha256'] for n,e in final['files'].items()}!={n:e['sha256'] for n,e in checked['files'].items()}:
        raise ValueError('Final runtime differs from tested runtime')
    runtime=read(CHECKED/'public-regression-candidate/local-isolated.json')
    if not runtime['passed'] or not runtime['source_unchanged'] or runtime['result']['tests_run']!=36:
        raise ValueError('Missing exact public runtime proof')
    if runtime['result']['failures'] or runtime['result']['errors'] or runtime['result']['skips']:
        raise ValueError('Public runtime proof contains failures')
    web=read(CHECKED/'web-validation.json')
    if not web['passed'] or not web['source_unchanged']:raise ValueError('Missing portal proof')
    for name,entry in final['files'].items():
        if sha(FINAL/entry['source'])!=entry['sha256']:raise ValueError('Final runtime source changed')
        if runtime['test_runtime_sha256'][name]!=entry['sha256']:raise ValueError('Tested runtime source differs')
    for name,entry in read(FINAL/'web-manifest.json')['files'].items():
        if sha(FINAL/entry['source'])!=entry['sha256'] or web['source_sha256'][name.removeprefix('web/')]!=entry['sha256']:
            raise ValueError('Tested portal source differs')
    if sha(FINAL/'tests/test_ratings_public.py')!=sha(CHECKED/'public-regression-candidate/test-snapshot/tests/test_ratings_public.py'):
        raise ValueError('Final ratings test differs')
    if sha(FINAL/'web/tests/ratings.test.ts')!=web['source_sha256']['tests/ratings.test.ts']:
        raise ValueError('Final portal test differs')
    log=(CHECKED/'focused-tests.log').read_text(encoding='utf-8')
    if not re.search(r'tests 22\b',log) or not re.search(r'pass 22\b',log) or not re.search(r'fail 0\b',log):
        raise ValueError('Missing 22-case portal proof')
    month=dict(type='string',pattern=r'^(?!0000|9999)[0-9]{4}-(?:0[1-9]|1[0-2])$')
    listing=read(ROOT/'reports/gameplay-followup/stage4-ratings/rating-contract.schema.json')
    listing.pop('$schema',None);listing['properties']['limit']={'const':10}
    listing['properties']['offset']['multipleOf']=10;listing['properties']['rows']['maxItems']=10
    listing['properties']['rows']['items']['properties']['names']['items']=dict(type='string',minLength=1,maxLength=64,pattern=r'^[^\u0000-\u001f\u007f]+$')
    listing['properties']['scope']=dict(anyOf=[{'const':'all'},month])
    listing['properties']['currentSeason']['properties']['id']=month
    listing['properties']['seasons']['items']['properties']['id']=month
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$defs':{
            'listing':listing,
            'coreRequest':dict(type='object',additionalProperties=False,
                required=['username','format','scope','offset','limit'],properties={
                    'username':dict(type='string',pattern='^[a-z0-9_]{3,32}$'),
                    'format':dict(enum=['pairs','wall']),
                    'scope':dict(anyOf=[{'type':'null'},{'const':'all'},month]),
                    'offset':dict(type='integer',minimum=0,maximum=9990,multipleOf=10),'limit':{'const':10}}),
            'coreResponse':dict(type='object',additionalProperties=False,required=['username','ratings'],properties={
                'username':dict(type='string',pattern='^[a-z0-9_]{3,32}$'),'ratings':{'$ref':'#/$defs/listing'}})},
        '$ref':'#/$defs/coreResponse',
        'description':'Semantic validators additionally bind username/query, UTC month boundaries, archive state, pagination and ordered squads.'}
    save('portal-contract.schema.json',schema)
    save('integration-contract.json',dict(version=1,
        facade='server.ratings_public.RatingsPublic(router, clock=time.time).status(data)',
        coreEndpoint='POST http://127.0.0.1:8083/v1/ratings/status',
        privateGatewayEndpoint='POST http://127.0.0.1:8082/v1/ratings/status',
        portalEndpoint='GET /api/ratings/status?format=pairs|wall&scope=current|all|YYYY-MM&page=1..1000',
        page='/ru/ratings and /en/ratings',
        defaults=dict(format='pairs',scope='current',page=1,limit=10),
        identity='ACTIVE linked portal session supplies username; no browser username, owner or slot',
        scope='current maps to null on the private core request; responses always use the actual YYYY-MM',
        authorization='Existing BANK_SERVICE_KEY on both fixed loopback HTTP hops; portal cookie session for GET',
        query={'keys':['format','scope','page'],'duplicateKeys':'rejected','unknownKeys':'rejected'},
        result={'username':'verified login of caller','ratings':'public listing only; hash teamId and character names, no save owners, account lists, Gaussian parameters or wallets'},
        paging={'rows':10,'maximumPage':1000,'recentSeasonOptions':12,'otherMonth':'explicit month input, not limited to recent options'},
        consistency='Hub lock, stopping recheck, read-only SQLite URI, query_only=ON and one BEGIN snapshot',
        responseLimitBytes=65536,requestLimitBytes=4096,
        mutations=[],historicalPrizesAssigned=False,StripeChanges=False,
        merge={'city_http':['import RatingsPublic','ratings=None constructor argument','self.ratings','allow /v1/ratings/status','dedicated ratings dispatch before unchanged CityV1 dispatch'],
               'bank_gateway':['new @app.post(/v1/ratings/status) block only'],
               'parentOwnedPortalLinks':['web/src/lib/portal-routes.ts: add ratings to portalPages','web/src/components/content-pages.tsx: add account link']},
        prerequisites=['Frozen stage4 rating_completion.py/config/runtime mechanics package','Published stage9-city foundation; merge concurrent services routes before deployment'],
        schema='portal-contract.schema.json'))
    save('validation.json',dict(version=1,utc=datetime.now(timezone.utc).isoformat(),passed=True,
        runtime={'tests':36,'newRatingsTests':12,'existingCityTests':24,'failures':0,'errors':0,'skips':0,
                 'seconds':runtime['seconds'],'proof':'../validation2/public-regression-candidate/local-isolated.json',
                 'proofSha256':sha(CHECKED/'public-regression-candidate/local-isolated.json'),
                 'finalRuntimeIdenticalToTested':True},
        portal={'tests':22,'newRatingsTests':7,'existingCityTests':6,'existingAssaultTests':9,'failures':0,'skips':0,
                'typescript':'PASS','proof':'../validation2/web-validation.json','proofSha256':sha(CHECKED/'web-validation.json'),
                'finalWebSourcesIdenticalToTested':True},
        originalProofsRetained=['../validation1/public-regression-candidate/local-isolated.json','../validation1/initial-typecheck.json','../validation1/web-validation.json'],
        revisions=['validation2: strict ASCII month identifiers and explicit access to archives older than twelve recent seasons'],
        deliveryManifestSha256=sha(FINAL/'delivery-manifest.json'),webManifestSha256=sha(FINAL/'web-manifest.json'),
        schemaSha256=sha(FINAL/'portal-contract.schema.json'),
        wholePublicSuite=False,hostedVerification=False,graphicalAcceptance=False,
        hostedRuntimeModified=False,playerDataOpened=False,
        remaining=['Parent merges concurrent services adapters and adds portal allowlist/account links','Parent builds/publishes the combined portal and backs up then deploys core changes','Hosted and graphical acceptance follow deployment']))
    print(json.dumps(dict(passed=True,server_tests=36,portal_tests=22,
                         delivery_manifest_sha256=sha(FINAL/'delivery-manifest.json'),web_manifest_sha256=sha(FINAL/'web-manifest.json'),
                         schema_sha256=sha(FINAL/'portal-contract.schema.json'))))


if __name__=='__main__':main()
