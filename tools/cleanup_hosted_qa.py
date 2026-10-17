"""Scoped cleanup requested on 2026-10-12; preserve all ordinary player rows."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote

REMOTE=r'''
import sqlite3,json,pathlib,sys,shutil,tempfile,subprocess,hashlib,re
from contextlib import closing
data=json.load(sys.stdin)
path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
names=data['names'];owners=names+['@character:'+n+':'+str(s) for n in names for s in range(2,6)]
assert all(re.fullmatch(r'q(?:[a-z]|er)[0-9a-f]{8}[a-h]',n) for n in names)
marks=','.join('?' for _ in owners);clan_ids=(3,4)
def q(s):return '"'+s.replace('"','""')+'"'
def tables(db):return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
def cols(db,t):return [r[1] for r in db.execute('PRAGMA table_info('+q(t)+')')]
def idle():
 with closing(sqlite3.connect(path)) as db:
  for t in ('battle_checkpoints','battle_settlement_jobs'):assert db.execute('SELECT count(*) FROM '+t).fetchone()[0]==0,'Active battles; defer update'
def plan(db):
 assert set(r[0] for r in db.execute('SELECT login FROM accounts'))>=set(names)
 assert db.execute('SELECT id,name,leader FROM clans WHERE id IN (3,4) ORDER BY id').fetchall()==[(3,b'qs9001ec02','qs9001ec02a'),(4,b'qs3a5e4825','qs3a5e4825a')]
 assert not db.execute('SELECT 1 FROM clan_members WHERE clan_id IN (3,4) AND account NOT IN ('+marks+')',owners).fetchone()
 assert not db.execute('SELECT 1 FROM alliance_members WHERE clan_id IN (3,4)').fetchone(),'Shared alliance requires separate review'
 rules={}
 immutable={t for t,sql in db.execute("SELECT tbl_name,sql FROM sqlite_master WHERE type='trigger'") if 'BEFORE DELETE' in sql.upper()}
 for t in tables(db):
  if t in immutable:continue # Retain immutable historical audit; it cannot create a character or rank.
  cs=cols(db,t);parts=[];args=[]
  for c in ('account','login','owner'):
   if c in cs:parts.append(q(c)+' IN ('+marks+')');args+=owners
  if 'clan_id' in cs:
   parts.append('clan_id IN (3,4)')
  if t=='clans':parts.append('id IN (3,4)')
  if parts:rules[t]=(' OR '.join(parts),args)
 shops=[r[0] for r in db.execute('SELECT id FROM private_shops WHERE account IN ('+marks+')',owners)]
 for t in ('private_shop_sales','private_shop_orders'):
  if shops:rules[t]=('shop IN ('+','.join('?' for _ in shops)+')',shops)
 return rules
def fingerprint(db,rules):
 result={}
 for t in tables(db):
  where,args=rules.get(t,('0',[]))
  # Mine ownership released by a separate, explicit update below.
  if t=='mine_claims':where,args='owner_clan IN (3,4)',[]
  rows=db.execute('SELECT * FROM '+q(t)+' WHERE NOT COALESCE(('+where+'),0)',args).fetchall()
  result[t]=hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest()
 return result
def cleanup(db,fail=False):
 rules=plan(db);before=fingerprint(db,rules)
 baseline_fk=db.execute('PRAGMA foreign_key_check').fetchall()
 # Preserve shared historical audit/match records. Only current ownership is released.
 claims=db.execute('SELECT location,revision FROM mine_claims WHERE owner_clan IN (3,4)').fetchall()
 db.execute('UPDATE mine_claims SET owner_clan=NULL,tax_percent=0,revision=revision+1 WHERE owner_clan IN (3,4)')
 deleted={}
 # Child records first; FK check below proves no newly dangling relationships.
 order=sorted(rules,key=lambda t:(t in ('clans','accounts','private_shops'),t))
 for t in order:
  where,args=rules[t];count=db.execute('DELETE FROM '+q(t)+' WHERE '+where,args).rowcount
  if count:deleted[t]=count
  if fail:raise RuntimeError('rollback probe')
 assert fingerprint(db,rules)==before,'Unrelated database rows changed'
 assert db.execute('PRAGMA foreign_key_check').fetchall()==baseline_fk
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert db.execute('SELECT count(*) FROM characters WHERE account IN ('+marks+')',owners).fetchone()[0]==0
 assert deleted['accounts']==len(names) and deleted['clans']==2
 return dict(deleted=deleted,released_mines=claims,unrelated_rows_preserved=True,integrity='ok')

idle()
for n,digest in data['expected'].items():assert hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest()==digest,'Remote code changed: '+n
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-qa-cleanup-',dir='/root'));folder.chmod(0o700)
def backup_db():
 with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(folder/path.name)) as dst:src.backup(dst)
 (folder/path.name).chmod(0o600)
backup_db()
for name in data['files']:
 source=pathlib.Path(name)
 if source.exists():
  dest=folder/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
shutil.copy2('/etc/tio-server/server.toml',folder/'server.toml');(folder/'server.toml').chmod(0o600)
with tempfile.TemporaryDirectory() as temp:
 trial=pathlib.Path(temp)/path.name;shutil.copy2(folder/path.name,trial)
 with closing(sqlite3.connect(trial)) as db:
  initial=repr(list(db.iterdump()))
  try:
   with db:cleanup(db,fail=True)
  except RuntimeError:pass
  assert repr(list(db.iterdump()))==initial,'Rollback failed'
  with db:result=cleanup(db)
idle()
subprocess.run(['systemctl','stop','tio-server'],check=True)
try:
 idle();backup_db() # Final durable state after ordinary connected players are saved.
 with closing(sqlite3.connect(path)) as db,db:
  db.execute('BEGIN IMMEDIATE');result=cleanup(db)
 for name,content in data['files'].items():
  dest=pathlib.Path(name);stage=dest.with_suffix(dest.suffix+'.qa-new')
  stage.write_text(content,encoding='utf-8');stage.chmod(0o644);stage.replace(dest)
 checked=subprocess.run(['runuser','-u','tio','--','.venv/bin/python','-m','server','--config','/etc/tio-server/server.toml','--check'],capture_output=True,text=True)
 assert checked.returncode==0,checked.stderr
 result['preflight']=checked.stdout.strip()
finally:
 subprocess.run(['systemctl','start','tio-server'],check=True)
result.update(backup=str(folder),rollback_verified=True,trial_cleanup_passed=True,graphical_clients_used=False)
(folder/'receipt.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
'''

def main():
    inspection=json.loads((ROOT/'reports/qa-cleanup/inspection.json').read_text())
    import re
    names=[n for n in inspection['accounts'] if re.fullmatch(r'q(?:[a-z]|er)[0-9a-f]{8}[a-h]',n)]
    expected=json.loads((ROOT/'reports/qa-cleanup/source-hashes.json').read_text())
    files={n:(ROOT/n).read_text(encoding='utf-8') for n in (*expected,'tio/rating_visibility.py')}
    result=remote(REMOTE,dict(names=names,expected=expected,files=files))
    (ROOT/'reports/qa-cleanup/deployment.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
