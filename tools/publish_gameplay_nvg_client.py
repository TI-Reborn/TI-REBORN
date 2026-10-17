"""Review/publish the exact .5 -> .6 F9 NVG client; no DB or service restart.

The SSH transaction is the reviewed SC publisher with fail-closed exact text
amendments. prepare only observes the server; publication requires the frozen
ten-file stage9 deployment and 144 local plus 144 hosted isolated checks.
Graphical acceptance follows publication and is never inferred from these checks.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import ssl
import sys
import tempfile
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import publish_gameplay_sc_client as established
from deploy.client_battle_items import patch_nvg,nvg_patch_plan as native_patch_plan

FOLDER=ROOT/'reports/gameplay-completion/stage9-interfaces-revision2'
NVG=ROOT/'reports/gameplay-followup/stage1-interfaces/nvg'
VERSION='2026.10.08.6';PREVIOUS_VERSION='2026.10.08.5'
BASE_SHA='7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b';BASE_BYTES=7761408
CANDIDATE_SHA='c712f60caf98356f5958ee7df0710c126df5a266c9f41319074771f419c88664';CANDIDATE_BYTES=7765504
BASE_MANIFEST_SHA='e13099fab0a9683f16a93b01924993418db245b6a3ef36772c270e0d689bffaf'
SERVER_MANIFEST_SHA='84fe52058ad3cc33339d0cd751d4342ec053cac9d5707fb0b1984096558b6fbb'
ORIGIN='https://185.184.42.88/updates/'
ESTABLISHED_SHA='82850858473d606036a2fc8f9d35934470f9ad89ad700c068837ab0669044992'
ESTABLISHED_REMOTE_SHA='fed532d93b467ddc4e50f76629741fdc5807ef9d5659ab048acb24acee71945a'
NATIVE_PROOF_SHA='9a0d03a3ef841a46385c9b0b8750a3b75bb6a485acac0ad3024dffedda742329'
NATIVE_TEST_SHA='45d51d33ae1a19ca72cbd79be1c85f2645fb114083979d4eb49b0a9033df9b46'
SERVER_FILES=('server/alliance_service.py','server/assault_public.py','server/bank_gateway.py',
    'server/economy_runtime.py','server/private_market.py','tio/arena_service.py','tio/battle_item_visuals.py',
    'tio/protocol/clan_ratings.py','tio/protocol/night_vision_state.py','tio/team_scene.py')
SERVER_ABI=('tio/protocol/night_vision_state.py','tio/battle_item_visuals.py')
NATIVE_SOURCES=('deploy/client_battle_items.py','tools/verify_battle_item_client_native.py',
    'tools/verify_nvg_client_native.py','tests/test_nvg_client_native.py')
SEEDS={'base/autoexec.cfg','base/config.cfg'}


def sha(raw):return hashlib.sha256(raw).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)


def nvg_patch_plan(source,candidate):
    # The native builder deliberately returns an AP tuple; reports and the SSH
    # payload are JSON. Compare their canonical public representation.
    return json.loads(json.dumps(native_patch_plan(source,candidate)))


def checked_manifest(raw,*,version):
    require(isinstance(raw,bytes) and 1<=len(raw)<=4*1024*1024,'Manifest outside reviewed bound')
    value=json.loads(raw)
    require(isinstance(value,dict) and type(value.get('schema'))is int and value['schema']==1
            and value.get('version')==version and version in (PREVIOUS_VERSION,VERSION),'Exact release version required')
    files=value.get('files');require(isinstance(files,list) and len(files)==6330,'Exact 6330-record catalogue required')
    paths=set();seeds=set()
    for row in files:
        require(isinstance(row,dict) and {'path','size','sha256'}<=set(row)<={'path','size','sha256','seed'},'Unknown descriptor')
        name=row['path']
        require(isinstance(name,str) and name and len(name)<=256 and chr(92)not in name
            and not any(ord(c)<32 or c==':' for c in name) and name==str(PurePosixPath(name))
            and not PurePosixPath(name).is_absolute() and '..'not in PurePosixPath(name).parts
            and name not in paths and PurePosixPath(name).name.lower()!='login.ini','Unsafe/duplicate/private client path')
        paths.add(name)
        require(type(row['size'])is int and 0<=row['size']<=64*1024*1024
            and isinstance(row['sha256'],str) and re.fullmatch('[a-f0-9]{64}',row['sha256'])is not None,'Invalid blob identity')
        require('seed'not in row or type(row['seed'])is bool,'Invalid seed type')
        if row.get('seed',False):seeds.add(name)
    require(seeds==SEEDS,'Only the two original configs may be seed records')
    dll=next((r for r in files if r['path']=='silver.dll'),None)
    expected=(BASE_SHA,BASE_BYTES) if version==PREVIOUS_VERSION else (CANDIDATE_SHA,CANDIDATE_BYTES)
    require(dll is not None and (dll['sha256'],dll['size'])==expected and not dll.get('seed',False),'Exact silver release required')
    if version==PREVIOUS_VERSION:require(sha(raw)==BASE_MANIFEST_SHA,'Exact official .5 baseline manifest required')
    return value


def new_manifest(old):
    value=checked_manifest(old,version=PREVIOUS_VERSION);value['version']=VERSION
    next(r for r in value['files'] if r['path']=='silver.dll').update(sha256=CANDIDATE_SHA,size=CANDIDATE_BYTES,seed=False)
    return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def transition(old,new):
    a=checked_manifest(old,version=PREVIOUS_VERSION);b=checked_manifest(new,version=VERSION)
    require(set(a)==set(b) and all(a[k]==b[k] for k in a if k not in ('version','files')),'Unrelated manifest metadata changed')
    require([r['path']for r in a['files']]==[r['path']for r in b['files']],'Unrelated catalogue changed')
    changes=[y['path']for x,y in zip(a['files'],b['files']) if x!=y]
    require(changes==['silver.dll'],'Only silver.dll may change')
    prior=next(r for r in a['files'] if r['path']=='silver.dll');after=next(r for r in b['files'] if r['path']=='silver.dll')
    require(after==dict(prior,sha256=CANDIDATE_SHA,size=CANDIDATE_BYTES,seed=False),'Unexpected silver descriptor')
    return changes


def fetch(path,maximum):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.load_default_certs();context.keylog_filename=None
    url=ORIGIN+path;request=urllib.request.Request(url,headers={'Cache-Control':'no-cache','Pragma':'no-cache'})
    with urllib.request.urlopen(request,context=context,timeout=45)as response:
        require(response.status==200 and response.geturl()==url,'Trusted HTTPS endpoint changed');raw=response.read(maximum+1)
    require(len(raw)<=maximum,'HTTPS response outside reviewed bound');return raw


def amend(code,before,after,*,count=1):
    require(code.count(before)==count,'Established SSH transaction guard changed')
    return code.replace(before,after)


def remote_program():
    require(sha((ROOT/'tools/publish_gameplay_sc_client.py').read_bytes())==ESTABLISHED_SHA
            and sha(established.REMOTE.encode())==ESTABLISHED_REMOTE_SHA,'Reviewed publisher source changed')
    code=established.REMOTE
    # Exact substitutions only. Everything else, especially the lock, backup,
    # immutable blob, atomic manifest, journal and conditional rollback, remains.
    code=amend(code,"BASE='2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f';BASE_BYTES=7753216",
        f"BASE='{BASE_SHA}';BASE_BYTES={BASE_BYTES}")
    code=amend(code,"CANDIDATE='7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b';CANDIDATE_BYTES=7761408",
        f"CANDIDATE='{CANDIDATE_SHA}';CANDIDATE_BYTES={CANDIDATE_BYTES}\nBASELINE_MANIFEST_SHA='{BASE_MANIFEST_SHA}'\nRELEASE_FILES={SERVER_FILES!r}\nABI_FILES={SERVER_ABI!r}")
    code=amend(code,'2026.10.08.3',PREVIOUS_VERSION,count=3);code=amend(code,'2026.10.08.4',VERSION,count=3)
    old="names=('tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py','tio/sc_auction.py','server/private_market.py','server/economy_runtime.py','tools/loopback_exchange.py','config/sc_auction.json')"
    code=amend(code,old,"names=tuple(dict.fromkeys(RELEASE_FILES+('tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py','tio/sc_auction.py','tools/loopback_exchange.py','config/sc_auction.json')))")
    code=amend(code,"if value.get('schema')!=1 or value.get('version')!=version:raise ValueError('Client source version changed')",
        "if type(value.get('schema'))is not int or value.get('schema')!=1 or value.get('version')!=version:raise ValueError('Client source version changed')\n if version=='"+PREVIOUS_VERSION+"' and sha(raw)!=BASELINE_MANIFEST_SHA:raise ValueError('Exact official baseline changed')")
    code=amend(code,"if not isinstance(files,list) or not 1<=len(files)<=10000:raise ValueError('Invalid client file count')",
        "if not isinstance(files,list) or len(files)!=6330:raise ValueError('Exact 6330 records required')")
    code=amend(code," if dll is None or (dll['sha256'],dll['size'])!=expected or dll.get('seed',False):raise ValueError('Unexpected DLL base')",
        " if {r['path']for r in files if r.get('seed',False)}!={'base/autoexec.cfg','base/config.cfg'}:raise ValueError('Original seed records required')\n if any(PurePosixPath(r['path']).name.lower()=='login.ini'for r in files):raise ValueError('Private login file forbidden')\n if dll is None or (dll['sha256'],dll['size'])!=expected or dll.get('seed',False):raise ValueError('Unexpected DLL base')")
    old="if plan['previous_sha256']!=BASE or plan['updated_sha256']!=CANDIDATE or plan['appended_bytes']!=8192 or plan['existing_f6_f7_and_four_other_item_hooks_preserved']is not True or plan['all_stock_bd_builders_preserved']is not True or len(plan['changes'])!=4:raise ValueError('Unreviewed SC edit plan')"
    new="if plan['previous_sha256']!=BASE or plan['updated_sha256']!=CANDIDATE or plan['previous_bytes']!=BASE_BYTES or plan['updated_bytes']!=CANDIDATE_BYTES or plan['appended_bytes']!=4096 or plan['all_other_published_bytes_preserved']is not True or plan['existing_f6_f7_f8_code_preserved']is not True or plan['activation_original_ap_gate_preserved']is not True or plan['unknown_state_original_ap_gate_preserved']is not True or plan['shortcut_consumed_before_free_off']is not True or plan['free_off_ap']!=[0,1,2] or len(plan['changes'])!=5:raise ValueError('Unreviewed F9 edit plan')"
    code=amend(code,old,new)
    code=amend(code,"if name not in ('tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py') or state['runtime'].get(name) is None or state['runtime'][name]['sha256']!=expected:raise RuntimeError('Reviewed SC server ABI not deployed')",
        "if name not in ABI_FILES or state['runtime'].get(name) is None or state['runtime'][name]['sha256']!=expected:raise RuntimeError('Reviewed F9 server ABI not deployed')")
    code=amend(code,"if set(p['server_abi'])!={'tio/protocol/sc_auction_view.py','tio/protocol/sc_auction.py'}:raise ValueError('Missing deployed SC ABI guard')",
        "if set(p['server_abi'])!=set(ABI_FILES):raise ValueError('Missing F9 ABI guard')\n  parity=p['server_source_sha256']\n  if set(parity)!=set(RELEASE_FILES) or any(state['runtime'].get(n) is None or state['runtime'][n]['sha256']!=v for n,v in parity.items()) or any(p['server_abi'][n]!=parity[n] for n in ABI_FILES):raise RuntimeError('Complete stage9 source parity required')")
    code=amend(code,'   return dict(result,recovered_completed_publication=True)',
        "   if guards()!=result['guards']:raise RuntimeError('Completed publication runtime/service/launcher guards changed')\n   return dict(result,recovered_completed_publication=True)")
    for old,new,count in (("'.sc-client-'","'.nvg-client-'",1),("'tio-before-sc-client-'","'tio-before-nvg-client-'",1),("'tio-sc-client-'","'tio-nvg-client-'",1)):
        code=amend(code,old,new,count=count)
    compile(code,'guarded-nvg-client-remote','exec');return code


REMOTE=remote_program();READ=REMOTE+'\nprint(json.dumps(inspect()))\n'
PUBLISH=REMOTE+'\nimport sys\nprint(json.dumps(publish(json.load(sys.stdin))))\n'


def folder_checked(folder):
    path=Path(folder).absolute()
    require(path==FOLDER.absolute() and not path.is_symlink(),'Only the frozen stage9 revision2 report folder is allowed')
    require(not any(p.is_symlink()or(hasattr(p,'is_junction')and p.is_junction())for p in (path,)+tuple(path.parents)),
            'Report folder contains a filesystem link')
    return path


def server_sources(folder):
    folder=folder_checked(folder);raw=(folder/'candidate-manifest.json').read_bytes()
    require(sha(raw)==SERVER_MANIFEST_SHA,'Frozen server manifest changed');manifest=json.loads(raw)
    require(manifest.get('local_private_contracts_included')is False and set(manifest['files'])==set(SERVER_FILES),
            'Exact public ten-file revision required')
    hashes={}
    for name,row in manifest['files'].items():
        require(row['source']=='runtime/'+name,'Unreviewed server candidate path')
        target=folder/row['source']
        require(not any(p.is_symlink()or(hasattr(p,'is_junction')and p.is_junction())for p in (target,)+tuple(target.parents)),
                'Frozen source contains a filesystem link')
        digest=sha(target.read_bytes());require(digest==row['sha256'],'Frozen runtime source changed');hashes[name]=digest
    return hashes


def native_sources():return {n:sha((ROOT/n).read_bytes())for n in NATIVE_SOURCES}


def native_evidence(source,candidate):
    proof_raw=(NVG/'native-proof.json').read_bytes();test_raw=(NVG/'validation.json').read_bytes()
    require(sha(proof_raw)==NATIVE_PROOF_SHA and sha(test_raw)==NATIVE_TEST_SHA,'Existing native evidence changed')
    proof=json.loads(proof_raw);tests=json.loads(test_raw);plan=nvg_patch_plan(source,candidate)
    require(proof.get('passed')is True and proof.get('status')=='PASS' and proof['preservation']==plan
            and proof['source_sha256']==native_sources(),'Native proof/source/plan parity failed')
    require(tests.get('passed')is True,'Focused native tests required')
    return proof_raw,test_raw,plan


def isolated_validation(value,hashes):
    require(value.get('passed')is True and value.get('source_unchanged')is True
        and value.get('source_sha256')==hashes and value.get('exit_code')==0,'Successful exact source isolated validation required')
    output=value.get('output','')
    require(isinstance(output,str) and len(re.findall(r'(?m)^Ran 144 tests in [0-9.]+s\s*$',output))==1
            and re.search(r'(?m)^OK\s*$',output)is not None and 'skipped='not in output,'144 tests without skips required')


def deployment_evidence(folder,hashes):
    folder=folder_checked(folder);records={}
    for name in ('local-validation.json','hosted-isolated-validation.json','validation.json','deployment.json'):
        raw=(folder/name).read_bytes();records[name]=sha(raw);value=json.loads(raw)
        if name in ('local-validation.json','hosted-isolated-validation.json'):isolated_validation(value,hashes)
        elif name=='validation.json':require(value.get('passed')is True and value.get('source_unchanged')is True
            and value.get('source_sha256')==hashes,'Combined exact source validation required')
        else:require(value.get('source_parity')is True and value.get('source_sha256')==hashes
            and value.get('service')=='active' and isinstance(value.get('backup'),str)
            and value['backup'].startswith('/root/tio-before-gameplay-completion-'),'Confirmed stage9 deployment/source parity required')
    return records


def write_json(path,value):
    with Path(path).open('x',encoding='utf-8')as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')


def prepare(folder):
    folder=folder_checked(folder);require(not(folder/'client').exists(),'Preserve existing client evidence')
    hashes=server_sources(folder);observed=established.remote(READ,{})
    old=base64.b64decode(observed['manifest'],validate=True)
    require(sha(old)==observed['manifest_sha256']and fetch('manifest.json',4*1024*1024)==old,'SSH/HTTPS manifest parity required')
    checked_manifest(old,version=PREVIOUS_VERSION);source=fetch('blobs/'+BASE_SHA,BASE_BYTES)
    require(len(source)==BASE_BYTES and sha(source)==BASE_SHA,'Exact HTTPS published .5 DLL required')
    candidate=patch_nvg(source)
    require(len(candidate)==CANDIDATE_BYTES and sha(candidate)==CANDIDATE_SHA and patch_nvg(candidate)==candidate,'Reviewed F9 DLL required')
    proof,tests,plan=native_evidence(source,candidate);new=new_manifest(old);transition(old,new)
    require(server_sources(folder)==hashes and base64.b64decode(established.remote(READ,{})['manifest'],validate=True)==old
            and fetch('manifest.json',4*1024*1024)==old,'Source changed during preparation')
    with tempfile.TemporaryDirectory(prefix='nvg-client-build-',dir=folder)as temporary:
        stage=Path(temporary)/'client';(stage/'source').mkdir(parents=True);(stage/'candidate').mkdir()
        for name,raw in (('source/silver.dll',source),('candidate/silver.dll',candidate),('previous-manifest.json',old),
                         ('manifest.json',new),('native-proof.json',proof),('native-tests.json',tests)):(stage/name).write_bytes(raw)
        write_json(stage/'remote-inspection.json',observed)
        release=dict(passed=True,operation=uuid.uuid4().hex,version=VERSION,previous_version=PREVIOUS_VERSION,
            source_sha256=BASE_SHA,source_bytes=BASE_BYTES,candidate_sha256=CANDIDATE_SHA,candidate_bytes=CANDIDATE_BYTES,
            before_manifest_sha256=sha(old),manifest_sha256=sha(new),native_proof_sha256=sha(proof),native_tests_sha256=sha(tests),
            native_source_sha256=native_sources(),server_source_sha256=hashes,server_abi={n:hashes[n]for n in SERVER_ABI},
            server_manifest_sha256=SERVER_MANIFEST_SHA,publisher_sha256=sha(Path(__file__).read_bytes()),
            remote_program_sha256=sha(REMOTE.encode()),patch_plan=plan,changed=['silver.dll'],preserved_records=6329,
            published=False,graphical_acceptance_complete=False,authentication_ui_tested=False,trusted_https=True,
            database_opened=False,local_player_data_uploaded=False,prepared_utc=datetime.now(timezone.utc).isoformat(),
            publish_command=f'python -m tools.publish_gameplay_nvg_client publish --folder "{folder}" --version {VERSION}')
        write_json(stage/'release.json',release);stage.replace(folder/'client')
    return release


def reviewed(folder):
    folder=folder_checked(folder);client=folder/'client';release=json.loads((client/'release.json').read_text(encoding='utf-8'))
    old=(client/'previous-manifest.json').read_bytes();new=(client/'manifest.json').read_bytes()
    source=(client/'source/silver.dll').read_bytes();candidate=(client/'candidate/silver.dll').read_bytes();hashes=server_sources(folder)
    proof,tests,plan=native_evidence(source,candidate)
    require(release.get('passed')is True and release['version']==VERSION and release['previous_version']==PREVIOUS_VERSION
        and release['source_sha256']==BASE_SHA and release['source_bytes']==BASE_BYTES
        and release['candidate_sha256']==CANDIDATE_SHA and release['candidate_bytes']==CANDIDATE_BYTES
        and sha(source)==BASE_SHA and len(source)==BASE_BYTES and sha(candidate)==CANDIDATE_SHA and len(candidate)==CANDIDATE_BYTES
        and patch_nvg(source)==candidate and patch_nvg(candidate)==candidate and release['patch_plan']==plan
        and release['before_manifest_sha256']==sha(old)and release['manifest_sha256']==sha(new)
        and release['native_source_sha256']==native_sources()and release['server_source_sha256']==hashes
        and release['server_abi']=={n:hashes[n]for n in SERVER_ABI}and release['server_manifest_sha256']==SERVER_MANIFEST_SHA
        and release['publisher_sha256']==sha(Path(__file__).read_bytes())and release['remote_program_sha256']==sha(REMOTE.encode())
        and release['native_proof_sha256']==sha(proof)and release['native_tests_sha256']==sha(tests)
        and (client/'native-proof.json').read_bytes()==proof and (client/'native-tests.json').read_bytes()==tests,
        'Reviewed candidate/source/evidence changed')
    transition(old,new);return release,old,new,candidate


def verify(folder):
    release,_,new,_=reviewed(folder)
    require(fetch('manifest.json',4*1024*1024)==new,'HTTPS published manifest differs')
    raw=fetch('blobs/'+CANDIDATE_SHA,CANDIDATE_BYTES)
    require(len(raw)==CANDIDATE_BYTES and sha(raw)==CANDIDATE_SHA,'HTTPS published DLL differs')
    result=dict(passed=True,version=VERSION,trusted_https=True,manifest_sha256=sha(new),silver_sha256=CANDIDATE_SHA,
        database_opened=False,server_restarted=False,installed_client_changed=False,graphical_acceptance_complete=False,
        verified_utc=datetime.now(timezone.utc).isoformat())
    target=folder_checked(folder)/'client/https-verification.json'
    if target.exists():target=target.with_name('https-verification-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'.json')
    write_json(target,result);return result


def publish(folder):
    folder=folder_checked(folder);require(not(folder/'client/publication.json').exists(),'Preserve publication evidence; use verify')
    release,old,new,candidate=reviewed(folder);evidence=deployment_evidence(folder,release['server_source_sha256'])
    observed=established.remote(READ,{});current=base64.b64decode(observed['manifest'],validate=True)
    require(current in (old,new)and fetch('manifest.json',4*1024*1024)==current,'Current SSH/HTTPS baseline changed')
    for name,digest in release['server_source_sha256'].items():
        require(observed['guards']['runtime'].get(name,{}).get('sha256')==digest,'Deployed stage9 runtime changed')
    require(deployment_evidence(folder,release['server_source_sha256'])==evidence,'Deployment evidence changed before publication')
    result=established.remote(PUBLISH,dict(operation=release['operation'],before_manifest=base64.b64encode(old).decode(),
        after_manifest=base64.b64encode(new).decode(),candidate=base64.b64encode(candidate).decode(),
        plan=release['patch_plan'],server_abi=release['server_abi'],server_source_sha256=release['server_source_sha256']))
    write_json(folder/'client/publication.json',dict(result,deployment_evidence_sha256=evidence));verify(folder);return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','review','publish','verify'))
    parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--version',default=VERSION,choices=(VERSION,))
    args=parser.parse_args(argv)
    if args.action=='review':
        release,*_=reviewed(args.folder);result=dict(passed=True,version=release['version'],changed=release['changed'],published=False)
    else:result={'prepare':prepare,'publish':publish,'verify':verify}[args.action](args.folder)
    print(json.dumps(result,ensure_ascii=True,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
