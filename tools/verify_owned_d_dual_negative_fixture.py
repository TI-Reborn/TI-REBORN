"""Exercise reviewed QA packet edits and cancellation on an isolated SQLite fixture."""
import ast
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.prepare_owned_d_dual_negative_fixture import COMMON,FOLDER
from tools.verify_hosted_arena_surroundings import OWNERSHIP
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.level_progression import normalize
from tio.owned_pets import OwnedPetStore

def sha(raw):return hashlib.sha256(raw).hexdigest()

def main():
    inspected=json.loads((FOLDER/'d-dual-negative-fixture-inspection.json').read_text(encoding='utf-8'))
    helper_source=ROOT/'work/unity-3d-maps-20261011/actual-runtime/tio/services_completion.py'
    assert sha(helper_source.read_bytes())==inspected['sources']['files']['tio/services_completion.py']
    for p in ('tio/protocol/pet_info.py','tio/level_progression.py','config/level_progression.json'):
        assert sha((ROOT/p).read_bytes())==inspected['sources']['files'][p]
    spec=importlib.util.spec_from_file_location('tio.services_completion',helper_source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    helper=module.ServicesCompletion
    ns=dict(sqlite3=sqlite3,json=json,target=inspected['account'],sha=sha,decode_pet_info=decode_pet_info,
            encode_pet_info=encode_pet_info,replace=replace,normalize=normalize,OwnedPetStore=OwnedPetStore,
            FIELDS=('0x8c4aef','0x8c4b05','0x8c4a07','0x8c4ab1'))
    tree=ast.parse(COMMON[len(OWNERSHIP):])
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('state','fields','protected','patch_fields')]
    exec(compile(ast.Module(body=functions,type_ignores=[]),'<reviewed bounded functions>','exec'),ns)
    checks=[]
    with tempfile.TemporaryDirectory(prefix='tio-dual-negative-fixture-local-') as td:
        db=sqlite3.connect(Path(td)/'fixture.sqlite3')
        db.executescript('''
        CREATE TABLE accounts(login TEXT PRIMARY KEY);
        CREATE TABLE characters(account TEXT PRIMARY KEY,slot INTEGER);
        CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER);
        CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,human INTEGER,pet_packet BLOB,inventory_packet BLOB,PRIMARY KEY(account,pet_id));
        CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER);
        CREATE TABLE hired_candidates(account TEXT,candidate_id INTEGER,pet_id INTEGER);
        CREATE TABLE battle_checkpoint_members(account TEXT PRIMARY KEY,match_id TEXT);
        CREATE TABLE battle_settlement_jobs(account TEXT PRIMARY KEY,match_id TEXT);
        CREATE TABLE service_dismissals(account TEXT,pet_id INTEGER,scheduled_at INTEGER,due_at INTEGER,completed_at INTEGER,PRIMARY KEY(account,pet_id));
        CREATE TABLE service_completion_receipts(account TEXT,identity TEXT,action TEXT,request TEXT,receipt TEXT,PRIMARY KEY(account,identity));
        CREATE TRIGGER receipt_no_delete BEFORE DELETE ON service_completion_receipts BEGIN SELECT RAISE(ABORT,'immutable'); END;
        CREATE TRIGGER receipt_no_update BEFORE UPDATE ON service_completion_receipts BEGIN SELECT RAISE(ABORT,'immutable'); END;
        ''')
        target=inspected['account']
        db.execute('INSERT INTO characters VALUES (?,1)',(target,));db.execute('INSERT INTO wallets VALUES (?,2750,0)',(target,))
        db.execute('INSERT INTO character_locations VALUES (?,3)',(target,));db.execute('INSERT INTO hired_candidates VALUES (?,1073741824,2)',(target,))
        db.executemany('INSERT INTO accounts VALUES (?)',[(f'foreign{i:03d}',) for i in range(204)]+[(f'qs3110ad96{c}',) for c in 'abcd'])
        db.executemany('INSERT INTO wallets VALUES (?,3000,0)',[(f'foreign{i:03d}',) for i in range(204)])
        for row in inspected['source_owned_rows']:
            packet=bytes.fromhex(row['pet_packet_hex']);inventory=bytes.fromhex(row['inventory_packet_hex'])
            assert sha(packet)==next(p['pet_sha256'] for p in inspected['pets'] if p['pet_id']==row['pet_id'])
            db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(target,row['pet_id'],row['human'],packet,inventory))
        for row in inspected['pending_dismissals']:db.execute('INSERT INTO service_dismissals VALUES (?,?,?,?,?)',tuple(row[k] for k in ('account','pet_id','scheduled_at','due_at','completed_at')))
        for row in inspected['service_receipts']:db.execute('INSERT INTO service_completion_receipts VALUES (?,?,?,?,?)',tuple(row[k] for k in ('account','identity','action','request','receipt')))
        db.commit()
        foreign_before=db.execute('SELECT * FROM wallets WHERE account!=? ORDER BY account',(target,)).fetchall()
        before=ns['protected'](db,'qa-local-cancel')
        desired={k:dict(v) for k,v in inspected['original_fields'].items()}
        desired['2'].update({'0x8c4aef':4,'0x8c4b05':7355,'0x8c4a07':115,'0x8c4ab1':115})
        db.execute('BEGIN IMMEDIATE');helper._gate(db,target,True);helper._pet(db,target,2)
        ns['patch_fields'](db,desired)
        pending=inspected['pending_dismissals'][0]
        assert db.execute('DELETE FROM service_dismissals WHERE account=? AND pet_id=2 AND scheduled_at=? AND due_at=? AND completed_at IS NULL',(target,pending['scheduled_at'],pending['due_at'])).rowcount==1
        request=helper._request('qa-local-cancel','qa_cancel_dismiss',{'petId':2,'originalRequestId':inspected['service_receipts'][0]['identity']})
        assert helper._prior(db,target,'qa-local-cancel','qa_cancel_dismiss',request) is None
        cancellation=helper._finish(db,target,'qa-local-cancel','qa_cancel_dismiss',request,petId=2,qaFixture=True)
        assert ns['protected'](db,'qa-local-cancel')==before
        assert [p['level'] for p in ns['state'](db)]==[4,4]
        assert ns['state'](db)[1]['selected']==1
        db.commit();checks.append('prepare [4,4] stable normalization; selection and inventory preserved')
        assert helper._prior(db,target,'qa-local-cancel','qa_cancel_dismiss',request)['receipt']==cancellation['receipt']
        checks.append('compensating cancellation receipt replays; immutable native receipt preserved')
        try:db.execute('DELETE FROM service_completion_receipts WHERE account=?',(target,))
        except sqlite3.IntegrityError:db.rollback();checks.append('receipt deletion forbidden by trigger')
        else:raise AssertionError('Immutable receipt deletion succeeded')
        before_restore=ns['protected'](db)
        restored={k:dict(v) for k,v in inspected['original_fields'].items()};restored['1'].update({'0x8c4aef':1,'0x8c4b05':0})
        db.execute('BEGIN IMMEDIATE');ns['patch_fields'](db,restored)
        assert ns['protected'](db)==before_restore
        assert [(p['level'],p['xp'],p['hp'],p['max_hp']) for p in ns['state'](db)]==[(1,0,1000,1000),(1,0,85,85)]
        db.commit();checks.append('restore both original level/XP fixtures with original hire health')
        assert db.execute('SELECT * FROM wallets WHERE account!=? ORDER BY account',(target,)).fetchall()==foreign_before
        checks.append('all 204 foreign wallets preserved')
        prior=ns['protected'](db);db.execute('BEGIN IMMEDIATE');db.execute('UPDATE wallets SET credits=7 WHERE account=?',('foreign000',))
        assert ns['protected'](db)!=prior;db.rollback();assert ns['protected'](db)==prior
        checks.append('unrelated foreign write detected; rollback preserves state')
        db.execute('INSERT INTO battle_checkpoint_members VALUES (?,?)',(target,'owned-test-checkpoint'))
        try:helper._gate(db,target,True)
        except module.ServiceRejected:db.rollback();checks.append('own checkpoint blocks service gate')
        else:raise AssertionError('Checkpoint gate failed')
        db.execute('INSERT INTO battle_settlement_jobs VALUES (?,?)',(target,'owned-test-settlement'))
        try:helper._gate(db,target,True)
        except module.ServiceRejected:db.rollback();checks.append('own settlement blocks service gate')
        else:raise AssertionError('Settlement gate failed')
        db.close()
    report=dict(passed=True,scope='local isolated SQLite fixture only; no authoritative writes',checks=checks,
                helper_source_sha256=sha(helper_source.read_bytes()),tool_sha256=sha((ROOT/'tools/prepare_owned_d_dual_negative_fixture.py').read_bytes()),
                actual_owned_source_packets_sha256={str(p['pet_id']):p['pet_sha256'] for p in inspected['pets']})
    output=FOLDER/'d-dual-negative-fixture-local-verification.json'
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
