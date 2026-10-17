"""Owned D dual-fighter QA fixture; inspect is read only, prepare/restore explicit."""
from pathlib import Path
import hashlib
import json
import sys
import argparse
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP

FOLDER = ROOT / 'reports/gameplay-completion/legacy-status-20261011/gui'
COMMON = OWNERSHIP + r'''
from datetime import datetime,timezone
from contextlib import closing
from dataclasses import replace
import ast,hashlib,subprocess,time,tempfile,tomllib
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.level_progression import FLOORS,normalize
from tio.owned_pets import OwnedPetStore
from tio.services_completion import ServicesCompletion
assert names==['qs3110ad96'+c for c in'abcd']
target=names[3];path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
assert pathlib.Path(tomllib.loads(pathlib.Path('/etc/tio-server/server.toml').read_text())['data_directory'])/path.name==path
def sha(raw):return hashlib.sha256(raw).hexdigest()
def state(db):
 result=[]
 for identity,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(target,)):
  f=decode_pet_info(raw,human_equipment=bool(human)).fields
  result.append(dict(pet_id=identity,human=bool(human),name=f['0x8c4489'].decode('cp1251'),level=f['0x8c4aef'],xp=f['0x8c4b05'],selected=f['0x8c44a6'],hp=f['0x8c4ab1'],max_hp=f['0x8c4a07'],pet_sha256=sha(raw),inventory_sha256=sha(inventory)))
 return result
def scoped(db,table):
 cols=[r[1] for r in db.execute('PRAGMA table_info("'+table+'")')]
 return [dict(zip(cols,r)) for r in db.execute('SELECT * FROM "'+table+'" WHERE account=?',(target,))] if cols else []
def timeline():
 raw=subprocess.check_output(['journalctl','-u','tio-server','--since','2026-10-11 19:50:00 UTC','-o','json','--no-pager'],text=True)
 out=[]
 for line in raw.splitlines():
  try:event=json.loads(line)
  except ValueError:continue
  msg=event.get('MESSAGE','')
  if isinstance(msg,str) and (('account='+target+' ') in msg or ('requested_login='+target+' ') in msg):
   event_name=next((name for name in ('Login authorized','presence_join','presence_leave','presence_move','chat_message') if name in msg),None)
   if event_name:out.append(dict(timestamp_us=int(event['__REALTIME_TIMESTAMP']),timestamp_utc=datetime.fromtimestamp(int(event['__REALTIME_TIMESTAMP'])/1000000,timezone.utc).isoformat(),event=event_name,pid=event.get('_PID')))
 return out
def source_info():
 files=('tio/services_completion.py','server/services_runtime.py','tio/db_transaction.py','tio/protocol/pet_info.py','tio/level_progression.py','config/level_progression.json','server/presence.py','server/multi.py','tio/owned_pets.py','tio/protocol/item_list.py','tio/cities.py')
 result={p:sha(pathlib.Path(p).read_bytes()) for p in files}
 methods=[node.name for node in ast.walk(ast.parse(pathlib.Path('tio/services_completion.py').read_text())) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))]
 return dict(files=result,services_helper_methods=methods)
FIELDS=('0x8c4aef','0x8c4b05','0x8c4a07','0x8c4ab1')
def guard(db):
 assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
 assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]==208
 assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
 events=timeline();assert events and events[-1]['event']=='presence_leave','D still has an authenticated or city presence session'
 latest_login=max(e['timestamp_us'] for e in events if e['event']=='Login authorized')
 assert events[-1]['timestamp_us']>latest_login and time.time()-events[-1]['timestamp_us']/1e6>2
 pid=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID','--value'],text=True).strip()
 assert events[-1]['pid']==pid,'D disconnect proof belongs to another server process'
 for table in ('battle_checkpoint_members','battle_settlement_jobs','map_journeys'):
  assert not scoped(db,table),'D owns retained battle, settlement or journey'
 if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_prison'").fetchone():
  assert not db.execute('SELECT 1 FROM world_prison WHERE account=? AND remaining>0',(target,)).fetchone()
 assert [(p['pet_id'],p['human']) for p in state(db)]==[(1,True),(2,True)]
 ServicesCompletion._gate(db,target,True)
 return dict(d_offline_evidence=events[-1],service_pid=pid,accounts_count=208,d_checkpoints=0,d_settlements=0,all_connections_zero_required=False)
def protected(db,cancel_id=None):
 result={}
 for table,sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
  quoted='"'+table.replace('"','""')+'"'
  columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
  rows=db.execute('SELECT * FROM '+quoted).fetchall()
  if table=='owned_pets':
   ai=columns.index('account');pi=columns.index('pet_id');ri=columns.index('pet_packet')
   patched=[]
   for row in rows:
    if row[ai]==target and row[pi] in (1,2):
     f=decode_pet_info(row[ri],human_equipment=bool(row[columns.index('human')])).fields
     opaque=repr(sorted((k,v) for k,v in f.items() if k not in FIELDS))
     row=tuple(opaque if i==ri else value for i,value in enumerate(row))
    patched.append(row)
   rows=patched
  if cancel_id and table=='service_dismissals':rows=[r for r in rows if not(r[columns.index('account')]==target and r[columns.index('pet_id')]==2)]
  if cancel_id and table=='service_completion_receipts':rows=[r for r in rows if not(r[columns.index('account')]==target and r[columns.index('identity')]==cancel_id)]
  result[table]=dict(schema_sha256=sha(sql.encode()),rows=len(rows),sha256=sha(json.dumps(sorted(map(repr,rows))).encode()))
 return result
def backup():
 folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-dual-negative-qa-',dir='/root'));folder.chmod(0o700)
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(folder/path.name)) as dst:
  src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 (folder/path.name).chmod(0o600)
 return folder
def fields(db):
 out={}
 for identity,human,raw in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(target,)):
  f=decode_pet_info(raw,human_equipment=bool(human)).fields
  out[str(identity)]={k:f[k] for k in FIELDS}
 return out
def patch_fields(db,desired):
 for identity,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(target,)).fetchall():
  pet=decode_pet_info(raw,human_equipment=bool(human));original=dict(pet.fields);updated={**original,**desired[str(identity)]}
  packet=encode_pet_info(replace(pet,fields=updated));parsed=decode_pet_info(packet,human_equipment=bool(human)).fields
  assert {k:v for k,v in parsed.items() if k not in FIELDS}=={k:v for k,v in original.items() if k not in FIELDS}
  assert OwnedPetStore.validate(packet,inventory,bool(human))==identity
  assert normalize(packet,bool(human))==packet,'Prepared/restored packet is not a stable level-normalized save'
  assert db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,target,identity)).rowcount==1
def original_first_fixture():
 folder=pathlib.Path(data['first_fixture_backup']).resolve()
 assert folder.parent==pathlib.Path('/root') and folder.name.startswith('tio-before-legacy-negative-qa-')
 with closing(sqlite3.connect((folder/path.name).as_uri()+'?mode=ro',uri=True)) as old:
  human,raw,inventory=old.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(target,)).fetchone()
  assert human==1 and sha(raw)==data['first_fixture_pet_sha256'] and sha(inventory)==data['first_fixture_inventory_sha256']
  pet=decode_pet_info(raw,human_equipment=True)
  assert pet.fields['0x8c43eb']==1 and (pet.fields['0x8c4aef'],pet.fields['0x8c4b05'])==(1,0)
  return {k:pet.fields[k] for k in FIELDS}
'''

INSPECT = COMMON + r'''
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
 result=dict(read_only=True,ownership_verified=True,account=target,observed_utc=datetime.now(timezone.utc).isoformat(),pets=state(db),wallet=scoped(db,'wallets'),
  pending_dismissals=scoped(db,'service_dismissals'),service_receipts=scoped(db,'service_completion_receipts'),retired_pets_count=len(scoped(db,'service_retired_pets')),
  checkpoints=scoped(db,'battle_checkpoint_members'),settlements=scoped(db,'battle_settlement_jobs'),accounts_count=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],integrity=db.execute('PRAGMA quick_check').fetchone()[0])
 result['source_owned_rows']=[dict(pet_id=i,human=h,pet_packet_hex=p.hex(),inventory_packet_hex=v.hex()) for i,h,p,v in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(target,))]
result['owned_d_timeline']=timeline();result['sources']=source_info()
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN');result['guard']=guard(db);result['original_fields']=fields(db)
print(json.dumps(result))
'''

MUTATE = COMMON + r'''
action=data['action'];assert action in ('prepare','restore')
assert source_info()==data['sources'],'Reviewed actual server sources changed'
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN');guard(db)
 if action=='prepare':
  assert state(db)==data['before_pets'],'D packet changed since review'
  assert scoped(db,'service_dismissals')==data['pending_dismissals']
  assert scoped(db,'service_completion_receipts')==data['service_receipts']
save=backup()
with closing(sqlite3.connect(path)) as db,db:
 db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
 before_guard=guard(db);before=state(db);original_fields=fields(db);cancel_id=data['cancel_identity'] if action=='prepare' else None
 preserved=protected(db,cancel_id)
 cancellation=None
 if action=='prepare':
  assert before==data['before_pets'] and original_fields==data['original_fields']
  assert scoped(db,'service_dismissals')==data['pending_dismissals']
  pending=data['pending_dismissals'];assert len(pending)==1 and pending[0]['pet_id']==2 and pending[0]['completed_at'] is None
  row=pending[0];assert row['scheduled_at']<int(time.time())<row['due_at'] and row['due_at']-row['scheduled_at']==172800
  receipts=scoped(db,'service_completion_receipts');assert receipts==data['service_receipts'] and len(receipts)==1
  native=receipts[0];assert native['identity']==data['native_identity'] and native['action']=='service_dismiss' and json.loads(native['request'])=={'petId':2}
  receipt=json.loads(native['receipt']);assert receipt['dismissAt']==row['due_at'] and receipt['petId']==2 and receipt['creditsDelta']==receipt['goldDelta']==0
  ServicesCompletion._pet(db,target,2)
  request=ServicesCompletion._request(cancel_id,'qa_cancel_dismiss',dict(petId=2,originalRequestId=native['identity'],scheduledAt=row['scheduled_at'],dismissAt=row['due_at']))
  assert ServicesCompletion._prior(db,target,cancel_id,'qa_cancel_dismiss',request) is None
  assert db.execute('DELETE FROM service_dismissals WHERE account=? AND pet_id=? AND scheduled_at=? AND due_at=? AND completed_at IS NULL',(target,2,row['scheduled_at'],row['due_at'])).rowcount==1
  cancellation=ServicesCompletion._finish(db,target,cancel_id,'qa_cancel_dismiss',request,petId=2,originalRequestId=native['identity'],cancelledDismissAt=row['due_at'],qaFixture=True)
  desired={k:dict(v) for k,v in original_fields.items()}
  desired['2'].update({'0x8c4aef':4,'0x8c4b05':FLOORS[3]})
  old=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=2',(target,)).fetchone()[0]
  pet=decode_pet_info(old,human_equipment=True)
  f=decode_pet_info(normalize(encode_pet_info(replace(pet,fields={**pet.fields,**desired['2']})),True),human_equipment=True).fields
  desired['2']={k:f[k] for k in FIELDS};desired['2']['0x8c4ab1']=desired['2']['0x8c4a07']
  assert desired['1']==original_fields['1'] and (desired['2']['0x8c4aef'],desired['2']['0x8c4b05'],desired['2']['0x8c4a07'])==(4,7355,115)
  restore_fields={k:dict(v) for k,v in original_fields.items()}
  original_main=original_first_fixture()
  restore_fields['1'].update({k:original_main[k] for k in ('0x8c4aef','0x8c4b05')})
 else:
  receipt=data['prepare_receipt'];assert receipt['action']=='prepare' and receipt['account']==target
  assert fields(db)['1']['0x8c4aef']==4 and fields(db)['1']['0x8c4b05']==7355
  assert fields(db)['2']['0x8c4aef']==4 and fields(db)['2']['0x8c4b05']==7355 and fields(db)['2']['0x8c4a07']==115
  assert not scoped(db,'service_dismissals'),'New pending dismissal must be reviewed separately'
  own_receipt=db.execute('SELECT receipt FROM service_completion_receipts WHERE account=? AND identity=?',(target,receipt['cancellation']['receipt']['requestId'])).fetchone()
  assert own_receipt and json.loads(own_receipt[0])==receipt['cancellation']['receipt']
  original_main=original_first_fixture()
  assert (original_main['0x8c4aef'],original_main['0x8c4b05'])==(1,0)
  desired={k:dict(v) for k,v in receipt['restore_fields'].items()}
  # Main actor's health is outside the original level/XP fixture scope.
  for k in ('0x8c4a07','0x8c4ab1'):desired['1'][k]=original_fields['1'][k]
  restore_fields=desired
 patch_fields(db,desired)
 assert protected(db,cancel_id)==preserved,'Any row or field outside the declared owned D scope changed'
 after_guard=guard(db);assert before_guard==after_guard,'D online state changed during fixture transaction'
 after=state(db)
 assert scoped(db,'wallets')==data['wallet'],'D wallet changed'
 result=dict(passed=True,action=action,account=target,backup=str(save),before=before,after=after,original_fields=original_fields,restore_fields=restore_fields,
  prepared_fields=fields(db),cancellation=cancellation,protected_tables=len(preserved),all_other_rows_and_fields_preserved=True,
  protection_sha256=sha(json.dumps(preserved,sort_keys=True).encode()),guard=after_guard,sources=source_info(),
  foreign_game_sessions_allowed=True,local_player_data_uploaded=False)
(save/'dual-negative-fixture.json').write_text(json.dumps(result,indent=2));(save/'dual-negative-fixture.json').chmod(0o600)
print(json.dumps(result))
'''

def inspect():
    fixture = FreshSurroundingsQA.load_private(ROOT / 'reports/arena-surroundings/private/qs3110ad96.json')
    result = fixture.remote(INSPECT, fixture.ownership_payload())
    output = FOLDER / 'd-dual-negative-fixture-inspection.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(evidence=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),**{k:v for k,v in result.items() if k!='source_owned_rows'}),ensure_ascii=False))

def review():
    inspected = json.loads((FOLDER / 'd-dual-negative-fixture-inspection.json').read_text(encoding='utf-8'))
    assert inspected['read_only'] and inspected['ownership_verified'] and inspected['guard']
    closed = FOLDER / 'd-navigation-session.json'
    assert json.loads(closed.read_text())['client_terminated'] is True
    cancel_identity = 'qa-negative-cancel-' + uuid.uuid4().hex
    first = json.loads((FOLDER / 'negative-fixture.json').read_text(encoding='utf-8'))
    assert first['passed'] and first['action']=='prepare' and first['account']==inspected['account'] and first['before']['level']==1 and first['before']['xp']==0
    document = dict(version=1,tool=str(Path(__file__).resolve()),tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    account=inspected['account'],before_pets=inspected['pets'],original_fields=inspected['original_fields'],wallet=inspected['wallet'],
                    pending_dismissals=inspected['pending_dismissals'],service_receipts=inspected['service_receipts'],
                    native_identity='native-1d043ddc19fc4ef9ac5ccdc595c787fe',cancel_identity=cancel_identity,sources=inspected['sources'],
                    first_fixture_backup=first['backup'],first_fixture_pet_sha256=first['before']['pet_sha256'],first_fixture_inventory_sha256=first['before']['inventory_sha256'],
                    d_closed_client_receipt=str(closed),d_closed_client_receipt_sha256=hashlib.sha256(closed.read_bytes()).hexdigest(),
                    mutation_scope=['owned D pet2 LEVEL4/XP7355/maxHP115/HP115; preserve all other fields','DELETE only exact pending D pet2 48h job','append owned D qa_cancel_dismiss receipt; retain immutable native receipt'],
                    restore_scope=['pet1 LEVEL1/XP0 from original negative fixture; preserve current health/selection/inventory','pet2 LEVEL1/XP0/maxHP85/HP85; preserve current selection/inventory and all other fields','cancellation remains recorded; do not recreate the QA dismissal job'],
                    applying_requires_explicit_root_dispatch=True)
    output = FOLDER / 'd-dual-negative-fixture-review.json'
    assert not output.exists(), 'Review pin is immutable'
    output.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(evidence=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),**document),ensure_ascii=False))

def mutate(action, review_path):
    review_path = Path(review_path).resolve()
    assert review_path.parent == FOLDER.resolve() and review_path.name == 'd-dual-negative-fixture-review.json'
    pin = json.loads(review_path.read_text(encoding='utf-8'))
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == pin['tool_sha256'], 'Tool changed after review'
    assert hashlib.sha256(Path(pin['d_closed_client_receipt']).read_bytes()).hexdigest() == pin['d_closed_client_receipt_sha256']
    payload = {**pin,'action':action}
    if action == 'restore':
        receipt = FOLDER / 'd-dual-negative-fixture-prepared.json'
        payload['prepare_receipt'] = json.loads(receipt.read_text(encoding='utf-8'))
        assert payload['prepare_receipt']['passed'] and payload['prepare_receipt']['sources'] == pin['sources']
    output = FOLDER / ('d-dual-negative-fixture-prepared.json' if action == 'prepare' else 'd-dual-negative-fixture-restored.json')
    assert not output.exists(), 'Do not overwrite authoritative fixture receipt'
    fixture = FreshSurroundingsQA.load_private(ROOT / 'reports/arena-surroundings/private/qs3110ad96.json')
    result = fixture.remote(MUTATE,{**fixture.ownership_payload(),**payload})
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(evidence=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),**result),ensure_ascii=False))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect','review','prepare','restore'))
    parser.add_argument('--review-pin')
    args = parser.parse_args()
    compile(INSPECT,'<read only inspect>','exec');compile(MUTATE,'<owned D dual negative fixture>','exec')
    if args.action=='inspect':inspect()
    elif args.action=='review':review()
    else:
        assert args.review_pin, 'An immutable reviewed tool and source pin is required'
        mutate(args.action,args.review_pin)
