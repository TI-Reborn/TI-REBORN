"""Remove only the Test1/Test2 accounts created in the current user task."""
from contextlib import closing
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote

COMMON=r'''
import hashlib,json,pathlib,sqlite3,subprocess,sys
from contextlib import closing
from server.accounts import Accounts
data=json.load(sys.stdin)
path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
logins=('test1','test2')
owners=tuple(n if slot==1 else '@character:'+n+':'+str(slot) for n in logins for slot in range(1,5))
assert tuple(n for n,p in data['pairs'])==logins
folder=pathlib.Path(data['creation_backup']).resolve()
assert folder.parent==pathlib.Path('/root') and folder.name.startswith('tio-before-user-test-accounts-')
proof=json.loads((folder/'creation.json').read_text())
assert {s['owner'] for s in proof['states']}==set(owners)
with closing(sqlite3.connect((folder/path.name).as_uri()+'?mode=ro',uri=True)) as original:
 assert not any(original.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in logins)
for login,password in data['pairs']:assert Accounts(path).verify(login.encode(),password.encode())==login
marks=','.join('?' for _ in owners)
def quote(value):return '"'+value.replace('"','""')+'"'
def tables(db):return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
def columns(db,table):return [r[1] for r in db.execute('PRAGMA table_info('+quote(table)+')')]
def foreign_fingerprint(db):
 result={}
 for table in tables(db):
  cols=columns(db,table)
  owner=next((c for c in ('account','login','owner') if c in cols),None)
  query='SELECT * FROM '+quote(table)
  rows=db.execute(query+' WHERE '+quote(owner)+' IS NULL OR '+quote(owner)+' NOT IN ('+marks+')',owners).fetchall() if owner else db.execute(query).fetchall()
  schema=db.execute("SELECT sql FROM sqlite_master WHERE name=?",(table,)).fetchone()[0]
  result[table]=dict(schema=schema,rows=len(rows),sha256=hashlib.sha256(json.dumps(sorted(map(repr,rows))).encode()).hexdigest())
 return result
def inspect(db):
 owned={};other={};schema={}
 for table in tables(db):
  cols=columns(db,table);own=next((c for c in ('account','login','owner') if c in cols),None)
  if own:
   count=db.execute('SELECT count(*) FROM '+quote(table)+' WHERE '+quote(own)+' IN ('+marks+')',owners).fetchone()[0]
   if count:owned[table]=dict(column=own,rows=count)
  # Exact save/account references in non-ownership fields must be reviewed.
  for col in cols:
   if col in ('account','login','owner'):continue
   count=db.execute('SELECT count(*) FROM '+quote(table)+' WHERE '+quote(col)+' IN ('+marks+')'+(' AND '+quote(own)+' NOT IN ('+marks+')' if own else ''),owners+owners if own else owners).fetchone()[0]
   if count:other[table+'.'+col]=count
  schema[table]=db.execute("SELECT sql FROM sqlite_master WHERE name=?",(table,)).fetchone()[0]
 chars=[]
 for state in proof['states']:
  owner=state['owner']
  row=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(owner,)).fetchone()
  assert row and row[0].decode()==state['character'],'Owned character changed'
  count=db.execute('SELECT count(*) FROM owned_pets WHERE account=?',(owner,)).fetchone()[0]
  chars.append(dict(owner=owner,name=state['character'],fighters=count))
 return dict(owned=owned,other_references=other,characters=chars,schemas=schema,
  accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
  battle_members=db.execute('SELECT count(*) FROM battle_checkpoint_members WHERE account IN ('+marks+')',owners).fetchone()[0])
'''

INSPECT=COMMON+r'''
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('BEGIN');result=inspect(db)
result.update(connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines()),
 service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip())
print(json.dumps(result))
'''

REMOVE=COMMON+r'''
import shutil,tempfile
def ensure_idle():
 assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
 assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip(),'Game connections present'
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
  for table in ('battle_checkpoints','battle_settlement_jobs'):assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,'Battle processing present'

def delete_owned(db,*,fail=False):
 before=foreign_fingerprint(db)
 state=inspect(db)
 assert state['integrity']=='ok' and state['battle_members']==0 and not state['other_references']
 assert state['owned']==data['expected_owned'],'Target records changed since inspection'
 # Reject embedded references in shared structured records as well.
 for table in tables(db):
  cols=columns(db,table);own=next((c for c in ('account','login','owner') if c in cols),None)
  for col in set(cols)&{'members','request_json','receipt_json','roster','report','payload','body'}:
   for login in logins:
    query='SELECT count(*) FROM '+quote(table)+' WHERE instr(lower(CAST('+quote(col)+' AS TEXT)),?)>0'
    if own:query+=' AND ('+quote(own)+' IS NULL OR '+quote(own)+' NOT IN ('+marks+'))'
    args=(login,)+owners if own else (login,)
    assert db.execute(query,args).fetchone()[0]==0,'Shared embedded target reference: '+table+'.'+col
 deleted={}
 for table in sorted(state['owned'],key=lambda t:t=='accounts'):
  col=state['owned'][table]['column']
  count=db.execute('DELETE FROM '+quote(table)+' WHERE '+quote(col)+' IN ('+marks+')',owners).rowcount
  assert count==state['owned'][table]['rows']
  deleted[table]=count
  if fail:raise RuntimeError('Isolated rollback verification')
 assert foreign_fingerprint(db)==before,'Unrelated database records changed'
 for table in tables(db):
  for col in set(columns(db,table))&{'account','login','owner'}:
   assert db.execute('SELECT count(*) FROM '+quote(table)+' WHERE '+quote(col)+' IN ('+marks+')',owners).fetchone()[0]==0,'Target rows remain'
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 return dict(deleted_rows=deleted,existing_rows_preserved=True,integrity='ok')

ensure_idle()
backup=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-delete-user-test-accounts-',dir='/root'))
backup.chmod(0o700)
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/path.name)) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
(backup/path.name).chmod(0o600)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml')
(backup/'server.toml').chmod(0o600)
with tempfile.TemporaryDirectory(prefix='tio-delete-accounts-check-') as testdir:
 pathlib.Path(testdir).chmod(0o700)
 testpath=pathlib.Path(testdir)/path.name;shutil.copy2(backup/path.name,testpath)
 with closing(sqlite3.connect(testpath)) as db:
  before=foreign_fingerprint(db)
  initial=[db.execute('SELECT count(*) FROM accounts').fetchone()[0],db.execute('SELECT count(*) FROM owned_pets').fetchone()[0]]
  try:
   with db:
    db.execute('BEGIN IMMEDIATE');delete_owned(db,fail=True)
  except RuntimeError:pass
  else:raise AssertionError('Rollback verification did not fail')
  assert foreign_fingerprint(db)==before
  assert [db.execute('SELECT count(*) FROM accounts').fetchone()[0],db.execute('SELECT count(*) FROM owned_pets').fetchone()[0]]==initial
  with db:
   db.execute('BEGIN IMMEDIATE');trial=delete_owned(db)
  assert trial['deleted_rows']['accounts']==2 and trial['deleted_rows']['owned_pets']==90
ensure_idle()
with closing(sqlite3.connect(path)) as db,db:
 db.execute('PRAGMA synchronous=FULL')
 db.execute('BEGIN IMMEDIATE')
 before_count=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
 result=delete_owned(db)
 after_count=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
 assert after_count==before_count-2
result.update(backup=str(backup),accounts_before=before_count,accounts_after=after_count,
 isolated_deletion_check_passed=True,rollback_verified=True,
 service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip())
receipt=backup/'deletion.json';receipt.write_text(json.dumps(result,indent=2));receipt.chmod(0o600)
print(json.dumps(result))
'''

VERIFY=r'''
import json,sqlite3,subprocess,sys
from contextlib import closing
from server.accounts import Accounts
data=json.load(sys.stdin)
owners=tuple(data['owners']);marks=','.join('?' for _ in owners)
path='/var/lib/tio-server/reservation.sqlite3'
remaining={}
with closing(sqlite3.connect('file:'+path+'?mode=ro',uri=True)) as db:
 for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
  quoted='"'+table.replace('"','""')+'"'
  cols=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
  for col in set(cols)&{'account','login','owner'}:
   count=db.execute('SELECT count(*) FROM '+quoted+' WHERE "'+col+'" IN ('+marks+')',owners).fetchone()[0]
   if count:remaining[table+'.'+col]=count
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 total=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
assert not remaining and integrity=='ok'
service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()
assert service=='active'
print(json.dumps(dict(accounts_absent=True,target_save_rows_remaining=remaining,accounts=total,integrity=integrity,service=service,graphical_clients_used=False)))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('inspect','remove','verify'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    creation=json.loads((ROOT/'reports/user-test-accounts/creation.json').read_text())
    private=json.loads((ROOT/'.secrets/user-test-accounts-20261010.json').read_text())
    payload=dict(pairs=private['pairs'],creation_backup=creation['backup'])
    if args.command=='remove':
        inspected=json.loads((ROOT/'reports/user-test-accounts/deletion-inspection.json').read_text())
        payload['expected_owned']=inspected['owned']
        result=remote(REMOVE,payload)
    elif args.command=='verify':
        result=remote(VERIFY,dict(owners=[s['owner'] for s in creation['states']]))
    else:result=remote(INSPECT,payload)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='schemas'},indent=2))

if __name__=='__main__':main()
