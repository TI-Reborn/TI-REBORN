"""Run repository public gameplay tests on an immutable hosted source snapshot.

Only source, public catalogs and test fixtures are copied. Production saves,
environment files, payment credentials and the running service are never opened.
The isolated test process has a hard 500-second budget, with per-test evidence.
"""
from __future__ import annotations

import argparse
import ast
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shlex
import subprocess
import shutil
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-followup/stage1-interfaces/public-regression'
BASE_FOLDER = FOLDER
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=15', 'root@185.184.42.88']

SNAPSHOT = r'''
import base64,hashlib,io,json,pathlib,subprocess,sys,tarfile
root=pathlib.Path('/opt/tio-emulator')
def files():
 out={}
 for directory,suffixes in {
  'tio':('.py',),'server':('.py',),'tools':('.py',),
  'config':('.json','.xml'),'evidence':('.json','.xml'),
  'deploy':('.py','.md','.service','.timer'),
  'registration':('.py',),'launcher':('.py','.md')}.items():
  for path in sorted((root/directory).rglob('*')):
   if path.is_file() and not path.is_symlink() and path.suffix.lower() in suffixes:
    out[path.relative_to(root).as_posix()]=path.read_bytes()
 for path in sorted(root.glob('*.md')):
  if not path.is_symlink():out[path.name]=path.read_bytes()
 for name in ('requirements.txt','registration/requirements.txt'):
  path=root/name
  if path.is_file():out[name]=path.read_bytes()
 return out
def state():
 p=subprocess.run(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts',
  '-p','ActiveState','-p','ExecMainStatus'],capture_output=True,text=True,check=True,timeout=10)
 return dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
before=files();pins={n:hashlib.sha256(raw).hexdigest() for n,raw in before.items()}
stream=io.BytesIO()
with tarfile.open(fileobj=stream,mode='w:gz') as archive:
 for name,raw in before.items():
  info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o644;info.mtime=0
  archive.addfile(info,io.BytesIO(raw))
after={n:hashlib.sha256(raw).hexdigest() for n,raw in files().items()}
if pins!=after:raise RuntimeError('Runtime changed during readonly snapshot')
print(json.dumps({'source_sha256':pins,'service_state':state(),
 'archive':base64.b64encode(stream.getvalue()).decode(),
 'hosted_player_data_opened':False,'hosted_runtime_modified':False}))
'''

# These tests concern another local-only task or artifacts outside the Linux
# gameplay runtime. They remain visible as exclusions rather than test skips.
EXCLUDED_MODULES = {
 'test_capture_shared_mines_recovery': 'Operator backup capture wrapper, not gameplay runtime',
 'test_operate_shared_mines_maintenance': 'Operator maintenance CLI wrapper, not gameplay runtime',
 'test_shared_mines_maintenance': 'Firewall/systemd maintenance wrapper, gameplay recovery tests retained',
 'test_shared_mines_route': 'Operator QA route planner, not installed gameplay runtime',
 'test_mine_scene_fixture': 'Windows game scenery fixture manipulation, actual runtime mines retained',
 'test_reservation_launcher': 'Windows local demonstration launcher, not hosted gameplay runtime',
 'test_reservation_texture_codec': 'Client bitmap codec, separate native/client acceptance',
 'test_arena_fog_validation': 'Windows client scenery assets, separate native/client acceptance',
 'test_client_battle_background': 'Windows client/private contracts executable fixtures',
 'test_client_battle_loot': 'Windows DLL fixture, separate native/client acceptance',
 'test_client_russian_encoding': 'Windows DLL/localization fixture',
 'test_client_upgrade_kit': 'Windows DLL fixture',
 'test_equipment_batch_client': 'Windows binary release controls, not hosted runtime',
 'test_loader_evidence': 'Windows loader diagnosis logs, not hosted gameplay runtime',
 'test_menu_native_semantics': 'Windows x86 client binaries, separate native/client acceptance',
 'test_menu_qa_guards': 'Windows client staging protection, not hosted runtime',
 'test_menu_interface_publish_safety': 'Client publication controls, separately covered release suite',
 'test_menu_interface_release': 'Client publication controls, separately covered release suite',
 'test_sc_auction_view': 'x86 native SC display proof, separate native/client acceptance',
 'test_publish_gameplay_sc_client': 'Frozen historical client publisher assets, not installed gameplay code',
 'test_publish_world_completion_client': 'Frozen client publisher assets, not installed gameplay code',
 'test_world_completion_catalog': 'Candidate catalog builder evidence, installed XML checked by runtime tests',
 'test_backup_tools_deployment': 'Operational deployment-tool safety, not installed gameplay runtime',
 'test_clan_warfare_candidate': 'Historical candidate builder, not installed gameplay runtime',
 'test_clan_warfare_deployment': 'Operational deployment-tool safety, not installed gameplay runtime',
 'test_game_tls_deploy': 'Operational deployment-tool safety, TLS runtime remains included',
 'test_game_tls_download_metadata': 'Launcher publication controls, TLS runtime remains included',
 'test_gameplay_deployment': 'Operational candidate deployment-tool safety',
 'test_launcher_014_publication': 'Windows launcher publication controls',
 'test_offsite_backup_windows': 'Windows DPAPI backup client, not installed gameplay runtime',
 'test_portal_backup': 'Operational PostgreSQL/website backups, not gameplay runtime',
 'test_recovery_bundle': 'Operational backup bundle, not gameplay runtime',
 'test_scheduled_backup': 'Operational scheduler backups, not gameplay runtime',
 'test_shared_mines_deployment_revision': 'Historical deployment tool fixtures',
 'test_shared_mines_qa': 'Historical hosted verifier fixtures, gameplay mine tests remain included',
 'test_stage4_deployment': 'Operational deployment-tool safety',
 'test_stage7_hosted_qa': 'Historical hosted verifier fixtures, not gameplay runtime',
 'test_verify_hosted_gameplay_modes': 'Hosted verification tool safety, no live players in this suite',
 'test_hosted_clan_warfare': 'Historical hosted verifier fixtures, not gameplay runtime',
 'test_hosted_completion_probes': 'Hosted verification tool safety, no live players in this suite',
 'test_hosted_economy_verifier': 'Historical hosted verifier fixtures, not gameplay runtime',
 'test_hosted_mines_expiry_qa': 'Hosted verification tool safety, no live players in this suite',
 'test_hosted_surroundings_asset_contract': 'Hosted/client asset QA helper, separate native/client acceptance',
 'test_hosted_world_travel': 'Hosted verification tool safety, no live players in this suite',
}

# Mixed modules retain their gameplay checks; only external artifact censuses
# and candidate-source-scope proofs are omitted, with exact test IDs reported.
EXCLUDED_TESTS = {
 'test_battle_loot.BattleLootTests.test_positions_match_real_fragment_records':
  'Windows original game asset census, runtime loot/container tests retained',
 'test_forest_encounters.ForestTests.test_client_materials_and_unchanged_denver_resources':
  'External client texture/icon/XML artifact census, encounter gameplay retained',
 'test_armor_models.ArmorModelTests.test_installed_resources_for_all_supported_armor':
  'Windows installed armor resource census; hosted item XML and stats retained',
}

TEST_HELPERS = (
 'tools/audit_unanswered_requests.py',
 'tools/build_skills_fixture.py',
 'tools/import_weapon_catalog.py',
 'tools/normalize_armor_models.py',
 'tools/normalize_equipment_effects.py',
 'tools/normalize_weapon_xml.py',
)

FIXTURES = (
 'config/battle_item_catalog_extension.xml',
 'evidence/items_diagnostic_provenance.json',
 'evidence/item_batch_native.json',
 'evidence/player_top100_native.json',
 'evidence/clan_crest_native.json',
 'reports/dog-encounters/client/animation.xml',
 'reports/dog-encounters/client/items.xml',
 'reports/gameplay-completion/stage8-world/source/map_generation.py',
 'reports/gameplay-completion/stage8-world/source/combat.py',
 'reports/gameplay-completion/stage8-world/source/world_completion_before_detroit.py',
 'reports/gameplay-completion/stage8-world/runtime/tio/map_generation.py',
)

RUNNER = r'''
import hashlib,json,pathlib,sys,time,traceback,unittest
root=pathlib.Path(__file__).resolve().parent
sys.path[:0]=[str(root),str(root/'tests'),str(root/'tools')]
plan=json.loads((root/'regression-plan.json').read_text())
started=time.monotonic()
class Result(unittest.TextTestResult):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs);self.records=[];self.times={}
 def startTest(self,test):
  self.times[test.id()]=time.monotonic();super().startTest(test)
 def record(self,test,outcome,detail=None):
  row={'test':test.id(),'outcome':outcome,'seconds':round(time.monotonic()-self.times.get(test.id(),time.monotonic()),3)}
  if detail is not None:row['detail']=detail
  self.records.append(row)
  with (root/'test-events.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
 def addSuccess(self,test):self.record(test,'passed');super().addSuccess(test)
 def addFailure(self,test,err):self.record(test,'failure',self._exc_info_to_string(err,test));super().addFailure(test,err)
 def addError(self,test,err):self.record(test,'error',self._exc_info_to_string(err,test));super().addError(test,err)
 def addSkip(self,test,reason):self.record(test,'skipped',reason);super().addSkip(test,reason)
 def addSubTest(self,test,subtest,err):
  if err is not None:self.record(subtest,'failure' if issubclass(err[0],test.failureException) else 'error',self._exc_info_to_string(err,test))
  super().addSubTest(test,subtest,err)
def leaves(suite):
 for test in suite:
  if isinstance(test,unittest.TestSuite):yield from leaves(test)
  else:yield test
suite=unittest.TestSuite();inventory=[];already=set(plan.get('completed_test_ids',()))
excluded=[]
for module in plan['selected_modules']:
 for test in leaves(unittest.defaultTestLoader.loadTestsFromName(module)):
  if test.id() in plan['excluded_tests']:excluded.append({'test':test.id(),'reason':plan['excluded_tests'][test.id()]})
  else:
   inventory.append(test.id())
   if test.id() not in already:suite.addTest(test)
(root/'test-inventory.json').write_text(json.dumps(inventory))
with (root/'test-log.txt').open('w') as stream:
 result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
report={'passed':result.wasSuccessful(),'tests_run':result.testsRun,
 'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
 'seconds':round(time.monotonic()-started,3),'records':result.records,
 'excluded_tests_found':excluded,'python':sys.version,'graphical_client_acceptance':False}
report['inventory']=inventory;report['omitted_previously_completed']=sorted(already.intersection(inventory))
(root/'test-result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ('passed','tests_run','failures','errors','skips','seconds')}),flush=True)
sys.exit(not result.wasSuccessful())
'''

REMOTE_RUN = r'''
import base64,hashlib,io,json,os,pathlib,signal,subprocess,sys,tarfile,tempfile,time
p=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator')
def check():
 actual={}
 for name in p['source_sha256']:
  path=root/name;actual[name]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
 return actual
before=check()
if before!=p['source_sha256']:raise RuntimeError('Snapshot no longer matches actual hosted runtime')
with tempfile.TemporaryDirectory(prefix='tio-public-regression-') as temp:
 stage=pathlib.Path(temp)
 raw=base64.b64decode(p['archive'],validate=True)
 if hashlib.sha256(raw).hexdigest()!=p['archive_sha256']:raise ValueError('Test bundle digest mismatch')
 with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
  for entry in archive:
   path=pathlib.PurePosixPath(entry.name)
   if not entry.isfile() or path.is_absolute() or '..' in path.parts or '\\' in entry.name or ':' in entry.name:raise ValueError('Unsafe test bundle')
   target=stage/entry.name;target.parent.mkdir(parents=True,exist_ok=True)
   with archive.extractfile(entry) as source:target.write_bytes(source.read())
 for name,expected in p.get('test_runtime_sha256',p['source_sha256']).items():
  if hashlib.sha256((stage/name).read_bytes()).hexdigest()!=expected:raise ValueError('Runtime snapshot replaced by local files')
 env=dict(os.environ)
 for key in tuple(env):
  if any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','STRIPE','SERVICE_KEY')):env.pop(key)
 env['PYTHONDONTWRITEBYTECODE']='1';env.pop('TIO_DETROIT_CANDIDATE',None)
 start=time.monotonic();timed_out=False
 # A fresh process group ensures crash-test children cannot escape cleanup.
 process=subprocess.Popen([str(root/'.venv-web/bin/python'),'-X','utf8','regression-runner.py'],
  cwd=stage,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,
  preexec_fn=lambda:os.nice(10))
 try:stdout,stderr=process.communicate(timeout=500)
 except subprocess.TimeoutExpired:
  timed_out=True;os.killpg(process.pid,signal.SIGTERM)
  try:stdout,stderr=process.communicate(timeout=5)
  except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);stdout,stderr=process.communicate(timeout=5)
 after=check()
 result=json.loads((stage/'test-result.json').read_text()) if (stage/'test-result.json').is_file() else None
 events=(stage/'test-events.jsonl').read_text() if (stage/'test-events.jsonl').is_file() else ''
 log=(stage/'test-log.txt').read_text() if (stage/'test-log.txt').is_file() else ''
 inventory=json.loads((stage/'test-inventory.json').read_text()) if (stage/'test-inventory.json').is_file() else None
 print(json.dumps({'passed':process.returncode==0 and before==after and not timed_out,
  'exit_code':process.returncode,'timed_out':timed_out,'seconds':round(time.monotonic()-start,3),
  'result':result,'event_log':events,'test_log':log,'process_stdout':stdout,'process_stderr':stderr,
  'source_before':before,'source_after':after,'source_unchanged':before==after,
  'test_runtime_sha256':p.get('test_runtime_sha256',p['source_sha256']),
  'isolated_candidate':bool(p.get('isolated_candidate')),
  'inventory':inventory,
  'hosted_player_data_opened':False,'hosted_player_data_copied':False,
  'hosted_runtime_modified':False,'graphical_client_acceptance':False}))
'''


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def remote(code: str, payload: dict, *, timeout: int = 60) -> dict:
    completed = subprocess.run(SSH+['python3 -c '+shlex.quote(code)],
        input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    if completed.returncode:
        raise RuntimeError('Read-only regression helper failed: '+completed.stderr[-2000:])
    return json.loads(completed.stdout)


def extract(raw: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        for entry in archive:
            path=PurePosixPath(entry.name)
            if (not entry.isfile() or path.is_absolute() or '..' in path.parts
                or PureWindowsPath(entry.name).root or PureWindowsPath(entry.name).drive):
                raise ValueError('Unexpected snapshot member')
            target=destination/Path(*path.parts)
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(entry) as source:
                target.write_bytes(source.read())


def imports(path: Path) -> set[str]:
    names=set()
    for node in ast.walk(ast.parse(path.read_bytes(),filename=str(path))):
        if isinstance(node,ast.Import):names.update(x.name for x in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module:
            names.add(node.module)
            if node.module in ('tio','server','tools'):
                names.update(node.module+'.'+x.name for x in node.names if x.name!='*')
    return names


def build_plan(snapshot: dict) -> dict:
    excluded=dict(EXCLUDED_MODULES);selected=[]
    frozen_tests=FOLDER/'test-snapshot/tests'
    for path in sorted(frozen_tests.glob('test_*.py')):
        name=path.stem
        if name in ('test_nvg_client_native','test_public_runtime_regression_controls'):
            excluded[name]='New client/runner control suite, separately verified; not gameplay runtime'
        if name=='test_assault_public' and not snapshot.get('isolated_candidate'):
            excluded[name]='New stage9-only test; absent installed baseline .5 feature namespace'
        if 'contract' in name or name in ('test_pve_contracts','test_party_travel','test_travel_party'):
            excluded[name]='Another local-only private contracts/party task; absent installed public runtime'
        if name not in excluded:
            missing=sorted(module for module in imports(path)
                if module.startswith(('tio.','server.'))
                and module.replace('.','/')+'.py' not in snapshot['source_sha256']
                and module.replace('.','/')+'/__init__.py' not in snapshot['source_sha256']
                and module not in ('tio.protocol','server.protocol'))
            # A from-package import can be a symbol, not a module. Only known
            # private namespaces determine exclusion; unknown cases run/fail.
            private=[m for m in missing if any(x in m for x in ('contract','party_travel','travel_party'))]
            if private:excluded[name]='Imports undeployed private namespace(s): '+', '.join(private)
        if name not in excluded:selected.append(name)
    return {'selected_modules':selected,'excluded_modules':excluded,
        'excluded_tests':EXCLUDED_TESTS,'runtime_source_count':len(snapshot['source_sha256']),
        'policy':'All current public gameplay modules, excluding explicitly listed private, client and operational-only modules',
        'hard_test_budget_seconds':500,'graphical_client_acceptance':False,
        'test_source_sha256':{p.relative_to(FOLDER/'test-snapshot').as_posix():sha(p.read_bytes())
             for p in frozen_tests.rglob('*') if p.is_file() and p.suffix in ('.py','.pem')},
        'baseline_feature_version':'2026.10.08.5; tests frozen before stage9 F9/assault-public changes'}


def snapshot_action() -> None:
    FOLDER.mkdir(parents=True,exist_ok=True)
    if (FOLDER/'snapshot.json').exists():raise ValueError('Preserve previous snapshot evidence')
    observed=remote(SNAPSHOT,{})
    raw=base64.b64decode(observed.pop('archive'),validate=True)
    observed['archive_sha256']=sha(raw)
    observed['timestamp_utc']=datetime.now(timezone.utc).isoformat()
    (FOLDER/'hosted-source.tar.gz').write_bytes(raw)
    extract(raw,FOLDER/'snapshot')
    (FOLDER/'snapshot.json').write_text(json.dumps(observed,indent=2)+'\n',encoding='utf-8')
    plan=build_plan(observed)
    (FOLDER/'plan.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'source_files':len(observed['source_sha256']),
        'selected_modules':len(plan['selected_modules']),'excluded_modules':len(plan['excluded_modules']),
        'service_state':observed['service_state'],'hosted_player_data_opened':False}))


def bundle(plan_override: dict | None = None) -> tuple[bytes,dict]:
    snapshot=json.loads((FOLDER/'snapshot.json').read_text())
    plan=plan_override or json.loads((FOLDER/'plan.json').read_text())
    test_pins=snapshot.get('test_runtime_sha256',snapshot['source_sha256'])
    files={n:(FOLDER/'snapshot'/n).read_bytes() for n in test_pins}
    for name,expected in test_pins.items():
        if sha(files[name])!=expected:raise RuntimeError('Local hosted-source snapshot changed')
    fixtures={}
    frozen=FOLDER/'test-snapshot'
    for name,expected in plan['test_source_sha256'].items():
        if sha((frozen/name).read_bytes())!=expected:raise RuntimeError('Frozen test source changed: '+name)
    # Test modules also provide public fixture classes/functions. Include
    # their import closure without selecting or running additional suites.
    needed_tests=set(plan['selected_modules']);pending=list(needed_tests)
    while pending:
        name=pending.pop();path=frozen/'tests'/(name+'.py')
        if not path.is_file():continue
        for module in imports(path):
            if module.startswith('test_') and '.' not in module and module not in needed_tests:
                if (frozen/'tests'/(module+'.py')).is_file():
                    needed_tests.add(module);pending.append(module)
    for path in sorted((frozen/'tests').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py','.pem'):
            if path.name.startswith('test_') and path.stem not in needed_tests:continue
            files[path.relative_to(frozen).as_posix()]=path.read_bytes()
    # Only explicit literals in selected tests identify additional native
    # packet/provenance fixtures. They are existing public evidence, never SQL.
    extra=set()
    for module in plan['selected_modules']:
        for node in ast.walk(ast.parse((frozen/'tests'/(module+'.py')).read_bytes())):
            if not isinstance(node,ast.Constant) or not isinstance(node.value,str):continue
            name=node.value
            if name.startswith('evidence/') and Path(name).suffix in ('.json','.xml'):extra.add(name)
            elif '/' not in name and name.endswith(('.json','.xml')) and (ROOT/'evidence'/name).is_file():
                extra.add('evidence/'+name)
    for name in (*FIXTURES,*sorted(extra),*TEST_HELPERS):
        path=ROOT/name
        if not path.is_file():raise FileNotFoundError('Declared public fixture missing: '+name)
        raw=path.read_bytes()
        if name in files and files[name]!=raw:
            # Production catalogs must remain the exact hosted version.
            fixtures[name]={'sha256':sha(files[name]),'origin':'hosted snapshot'}
        else:
            files[name]=raw;fixtures[name]={'sha256':sha(raw),'origin':'public existing repository test fixture'}
    # The repository's default example config has no production credentials.
    # It is only needed by the source-packaging boundary test.
    for name in ('config/server.toml',):
        raw=(ROOT/name).read_bytes();files[name]=raw
        fixtures[name]={'sha256':sha(raw),'origin':'repository nonproduction example'}
    files['regression-plan.json']=json.dumps(plan).encode()
    files['regression-runner.py']=RUNNER.encode()
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as archive:
        for name,raw in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o644;info.mtime=0
            archive.addfile(info,io.BytesIO(raw))
    return stream.getvalue(),fixtures


def reports(kind: str = 'hosted') -> list[Path]:
    if kind not in ('hosted','local'):raise ValueError('Unexpected report kind')
    return sorted(FOLDER.glob(kind+'-isolated*.json'))


def completed_ids(kind: str = 'hosted') -> set[str]:
    completed=set()
    for path in reports(kind):
        log=path.with_name(path.stem.replace(kind+'-isolated',kind+'-test-events')+'.jsonl')
        if not log.exists():continue
        for line in log.read_text().splitlines():
            record=json.loads(line)
            completed.add(record['test'].split(' (',1)[0])
    return completed


def run_action(resume: bool = False) -> None:
    number=len(reports())
    if resume and not number:raise ValueError('No initial verification to resume')
    suffix=('-batch-'+str(number).zfill(2)) if resume else ''
    target=FOLDER/('hosted-isolated'+suffix+'.json')
    if target.exists():raise ValueError('Preserve previous regression results')
    snapshot=json.loads((FOLDER/'snapshot.json').read_text())
    plan=json.loads((FOLDER/'plan.json').read_text())
    if resume:
        # The first frozen test copy raced with a new stage9-only test file.
        # Preserve that failed loader record; exclude its undeployed namespace
        # explicitly from the .5 baseline rather than claim a runtime defect.
        corrections={
            'test_assault_public':'New stage9-only test created before test copy; server.assault_public absent by design in baseline .5',
            'test_armor_models':'Both tests require Windows installed meshes; this is a client artifact census, not Linux gameplay runtime',
        }
        if snapshot.get('isolated_candidate'):corrections.pop('test_assault_public')
        for module,reason in corrections.items():
            if module in plan['selected_modules']:plan['selected_modules'].remove(module)
            plan['excluded_modules'][module]=reason
        plan['completed_test_ids']=sorted(completed_ids())
    raw,fixtures=bundle(plan)
    (FOLDER/('test-bundle'+suffix+'.tar.gz')).write_bytes(raw)
    (FOLDER/('test-fixtures'+suffix+'.json')).write_text(json.dumps(fixtures,indent=2)+'\n')
    (FOLDER/('plan'+suffix+'.json')).write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps({'running':'hosted public runtime snapshot','test_bundle_sha256':sha(raw)}),flush=True)
    result=remote(REMOTE_RUN,{'source_sha256':snapshot['source_sha256'],
        'test_runtime_sha256':snapshot.get('test_runtime_sha256',snapshot['source_sha256']),
        'isolated_candidate':snapshot.get('isolated_candidate',False),
        'archive_sha256':sha(raw),'archive':base64.b64encode(raw).decode()},timeout=540)
    log=result.pop('test_log');events=result.pop('event_log')
    (FOLDER/('hosted-test-log'+suffix+'.txt')).write_text(log,encoding='utf-8')
    (FOLDER/('hosted-test-events'+suffix+'.jsonl')).write_text(events,encoding='utf-8')
    result['timestamp_utc']=datetime.now(timezone.utc).isoformat()
    result['test_bundle_sha256']=sha(raw)
    result['verification_tool_sha256']=sha(Path(__file__).read_bytes())
    result['resumed_after_unique_completed_tests']=len(plan.get('completed_test_ids',()))
    result['test_fixture_sha256']=fixtures
    result['log_sha256']=sha(log.encode());result['events_sha256']=sha(events.encode())
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('passed','exit_code','timed_out','seconds','source_unchanged')}))
    if result['result']:
        print(json.dumps({k:result['result'][k] for k in ('tests_run','failures','errors','skips')}))
    if not result['passed']:raise SystemExit(1)


def candidate_folder(path: Path) -> Path:
    path=path.resolve()
    allowed=ROOT/'reports/gameplay-followup/stage1-interfaces'
    deployed_stages={ROOT/'reports/gameplay-completion'/name for name in (
        'stage9-interfaces','stage9-interfaces-revision2')}
    ratings=ROOT/'reports/gameplay-followup/stage4-ratings'
    rating_candidates={ratings,*(ratings/name for name in ('validation1','validation2','validation3','validation4','final')),
                       *(ratings/'portal'/name for name in ('validation1','validation2','final'))}
    if path not in deployed_stages|rating_candidates and (not path.is_relative_to(allowed) or path==allowed):
        raise ValueError('Candidate evidence must be in a specific stage1 report subfolder')
    return path


def prepare_candidate(path: Path) -> None:
    global FOLDER
    parent=candidate_folder(path)
    manifest_path=parent/'candidate-manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    base=json.loads((BASE_FOLDER/'snapshot.json').read_text(encoding='utf-8'))
    entries=manifest.get('files')
    if not isinstance(entries,dict) or not entries:raise ValueError('Select explicit frozen candidate files')
    FOLDER=parent/'public-regression-candidate'
    if FOLDER.exists():raise ValueError('Preserve previously prepared candidate evidence')
    prepared={}
    for name,entry in entries.items():
        parts=PurePosixPath(name)
        if (parts.is_absolute() or '..' in parts.parts or '\\' in name or ':' in name
            or parts.parts[0] not in ('tio','server','tools','config','evidence')
            or not ((parts.parts[0] in ('tio','server','tools') and parts.suffix=='.py')
                    or (parts.parts[0]=='config' and parts.suffix in ('.json','.xml'))
                    or (parts.parts[0]=='evidence' and parts.suffix=='.xml'))):
            raise ValueError('Unexpected candidate runtime path: '+name)
        if any(word in name.lower() for word in ('contract','party_travel','travel_party')):
            raise ValueError('Private local runtime must not enter a public candidate: '+name)
        if entry.get('before')!=base['source_sha256'].get(name):
            raise ValueError('Candidate is not based on pinned hosted .5 runtime: '+name)
        source=(parent/entry['source']).resolve()
        if not source.is_relative_to(parent):raise ValueError('Candidate source escapes its report folder')
        raw=source.read_bytes()
        if len(raw)>4*1024*1024 or sha(raw)!=entry['sha256']:
            raise ValueError('Candidate source changed: '+name)
        if parts.suffix=='.py':
            compile(raw,name,'exec')
            for node in ast.walk(ast.parse(raw,filename=name)):
                modules=[]
                if isinstance(node,ast.Import):modules=[item.name for item in node.names]
                elif isinstance(node,ast.ImportFrom) and node.module:modules=[node.module]
                if any(word in module.lower() for module in modules
                    for word in ('pve_contract','contracts','party_travel','travel_party')):
                    raise ValueError('Candidate imports private local runtime: '+name)
        elif parts.suffix=='.json':json.loads(raw)
        elif b'<!DOCTYPE' in raw.upper():raise ValueError('Unexpected XML doctype')
        if entry['sha256']==entry['before']:raise ValueError('Unchanged candidate file selected: '+name)
        prepared[name]=raw
    FOLDER.mkdir()
    shutil.copytree(BASE_FOLDER/'snapshot',FOLDER/'snapshot')
    test_pins=dict(base['source_sha256'])
    for name,raw in prepared.items():
        target=FOLDER/'snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        test_pins[name]=sha(raw)
    shutil.copytree(ROOT/'tests',FOLDER/'test-snapshot/tests',ignore=shutil.ignore_patterns('__pycache__'))
    state={**base,'isolated_candidate':True,'test_runtime_sha256':test_pins,
        'candidate_manifest_sha256':sha(manifest_path.read_bytes()),
        'candidate_file_sha256':{n:sha(raw) for n,raw in prepared.items()},
        'prepared_utc':datetime.now(timezone.utc).isoformat()}
    (FOLDER/'snapshot.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
    plan=build_plan(state)
    plan['baseline_feature_version']='Isolated stage9 candidate on immutable actual hosted .5 sources; never deployed'
    if 'test_armor_models' in plan['selected_modules']:plan['selected_modules'].remove('test_armor_models')
    plan['excluded_modules']['test_armor_models']='Client Windows mesh census, separate native/client acceptance'
    (FOLDER/'plan.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'prepared':str(FOLDER),'candidate_files':len(prepared),
        'selected_modules':len(plan['selected_modules']),'private_local_runtime_uploaded':False}))


def local_action(python: Path | None = None, *, resume: bool = False, modules: list[str] | None = None) -> None:
    number=len(reports('local'))
    if resume and not number:raise ValueError('No local verification to resume')
    suffix=('-batch-'+str(number).zfill(2)) if resume else ''
    target=FOLDER/('local-isolated'+suffix+'.json')
    if target.exists():raise ValueError('Preserve previous local candidate verification')
    executable=python.resolve() if python is not None else Path(sys.executable)
    if not executable.is_file():raise FileNotFoundError('Test interpreter missing')
    snapshot=json.loads((FOLDER/'snapshot.json').read_text())
    plan=json.loads((FOLDER/'plan.json').read_text())
    if modules is not None:
        if not modules or len(set(modules))!=len(modules) or set(modules)-set(plan['selected_modules']):
            raise ValueError('Focused modules must be unique members of the declared public plan')
        plan['selected_modules']=modules
        plan['focused_public_subset']=True
    if resume:plan['completed_test_ids']=sorted(completed_ids('local'))
    raw,fixtures=bundle(plan)
    (FOLDER/('local-test-bundle'+suffix+'.tar.gz')).write_bytes(raw)
    (FOLDER/('local-plan'+suffix+'.json')).write_text(json.dumps(plan,indent=2)+'\n')
    env=dict(os.environ)
    for key in tuple(env):
        if any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','STRIPE','SERVICE_KEY')):env.pop(key)
    env['PYTHONDONTWRITEBYTECODE']='1';env.pop('TIO_DETROIT_CANDIDATE',None)
    began=time.monotonic();timed_out=False
    print(json.dumps({'running':'local isolated public candidate',
        'test_bundle_sha256':sha(raw),'python':str(executable)}),flush=True)
    with tempfile.TemporaryDirectory(prefix='tio-public-regression-local-') as directory:
        stage=Path(directory);extract(raw,stage)
        test_pins=snapshot.get('test_runtime_sha256',snapshot['source_sha256'])
        def hashes():return {n:sha((stage/n).read_bytes()) for n in test_pins}
        if hashes()!=test_pins:raise ValueError('Local candidate bundle checksum mismatch')
        options={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name=='nt' else {'start_new_session':True}
        process=subprocess.Popen([str(executable),'-X','utf8','regression-runner.py'],cwd=stage,
            env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',**options)
        try:stdout,stderr=process.communicate(timeout=500)
        except subprocess.TimeoutExpired:
            timed_out=True
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,check=False,timeout=10)
            else:
                import signal
                os.killpg(process.pid,signal.SIGKILL)
            stdout,stderr=process.communicate(timeout=10)
        result=json.loads((stage/'test-result.json').read_text()) if (stage/'test-result.json').is_file() else None
        inventory=json.loads((stage/'test-inventory.json').read_text()) if (stage/'test-inventory.json').is_file() else None
        events=(stage/'test-events.jsonl').read_text(encoding='utf-8') if (stage/'test-events.jsonl').is_file() else ''
        log=(stage/'test-log.txt').read_text(encoding='utf-8') if (stage/'test-log.txt').is_file() else ''
        unchanged=hashes()==test_pins
    (FOLDER/('local-test-events'+suffix+'.jsonl')).write_text(events,encoding='utf-8')
    (FOLDER/('local-test-log'+suffix+'.txt')).write_text(log,encoding='utf-8')
    report={'passed':process.returncode==0 and unchanged and not timed_out,
        'exit_code':process.returncode,'timed_out':timed_out,'seconds':round(time.monotonic()-began,3),
        'result':result,'inventory':inventory,'source_unchanged':unchanged,
        'test_runtime_sha256':test_pins,'isolated_candidate':snapshot.get('isolated_candidate',False),
        'test_fixture_sha256':fixtures,'test_bundle_sha256':sha(raw),
        'verification_tool_sha256':sha(Path(__file__).read_bytes()),
        'log_sha256':sha(log.encode()),'events_sha256':sha(events.encode()),
        'process_stdout':stdout,'process_stderr':stderr,
        'hosted_player_data_opened':False,'hosted_player_data_copied':False,
        'hosted_runtime_modified':False,'graphical_client_acceptance':False,
        'selected_modules':plan['selected_modules'],'focused_public_subset':bool(plan.get('focused_public_subset')),
        'timestamp_utc':datetime.now(timezone.utc).isoformat()}
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','timed_out','seconds','source_unchanged')}))
    if result:print(json.dumps({k:result[k] for k in ('tests_run','failures','errors','skips')}))
    if not report['passed']:raise SystemExit(1)


def main() -> None:
    global FOLDER
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('snapshot','run','resume','prepare-candidate','run-local','resume-local'))
    parser.add_argument('--candidate-folder',type=Path,
        help='Stage1 report subfolder containing explicit candidate-manifest.json')
    parser.add_argument('--python',type=Path,help='Explicit existing interpreter for local checks')
    parser.add_argument('--modules',nargs='+',help='Explicit focused local subset of the selected public modules')
    args=parser.parse_args();action=args.action
    if action=='prepare-candidate':
        if args.candidate_folder is None:parser.error('--candidate-folder is required')
        prepare_candidate(args.candidate_folder);return
    if args.candidate_folder is not None:
        FOLDER=candidate_folder(args.candidate_folder)/'public-regression-candidate'
    if action in ('run-local','resume-local'):local_action(args.python,resume=action=='resume-local',modules=args.modules);return
    if args.modules is not None:parser.error('--modules applies only to isolated local checks')
    if action=='snapshot':snapshot_action()
    else:run_action(action=='resume')


if __name__=='__main__':main()
