"""Recover only the empty owned QA pair from the recorded local ACL failure.

No user account is selectable. Discovery proves original backup absence and
current salted identity. Rotation requires the unchanged proof, empty saves,
idle gameplay ports and a verified CurrentUser private directory first.
"""
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_hosted_economy_tls import EconomyFixture, PRIVATE, PINNED_SOURCES
from tools.verify_hosted_arena_surroundings import OWNERSHIP

DISCOVER = r'''
import hashlib,json,pathlib,re,sqlite3,sys
data=json.load(sys.stdin)
candidates=[p for p in pathlib.Path('/root').glob('tio-before-surroundings-qa-*') if p.stat().st_mtime>=data['after'] and (p/'qa-owned.json').is_file()]
assert len(candidates)==1,'Need exactly one recent owned QA provisioning backup'
folder=candidates[0];raw=(folder/'qa-owned.json').read_bytes();proof=json.loads(raw);names=proof['names']
assert re.fullmatch('qs[0-9a-f]{8}',proof['prefix']) and names==[proof['prefix']+'a',proof['prefix']+'b']
with sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True) as old:
 assert old.execute('SELECT count(*) FROM accounts').fetchone()[0]==data['before_count']
 assert not any(old.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 assert db.execute('SELECT count(*) FROM accounts').fetchone()[0]==data['before_count']+2
 for n in names:
  assert list(db.execute('SELECT hex(salt),hex(digest),iterations FROM accounts WHERE login=?',(n,)).fetchone())==proof['credentials'][n]
  for table in ('characters','wallets','owned_pets','battle_checkpoint_members'):
   assert table not in tables or db.execute('SELECT count(*) FROM '+table+' WHERE account=?',(n,)).fetchone()[0]==0
print(json.dumps(dict(backup=str(folder),prefix=proof['prefix'],names=names,owned_empty_accounts=2,
 previous_proof_sha256=hashlib.sha256(raw).hexdigest(),accounts_before=data['before_count'])))
'''

ROTATE = OWNERSHIP + r'''
import hashlib,os,secrets,subprocess
from server.accounts import ITERATIONS,password_bytes
assert hashlib.sha256((folder/'qa-owned.json').read_bytes()).hexdigest()==data['proof_sha256']
assert data['pairs'] and [n for n,p in data['pairs']]==names
for p,digest in data['source_hashes'].items():assert hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==digest
assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip()
previous=folder/'qa-owned-before-credential-recovery.json';snapshot=folder/'reservation-before-qa-credential-recovery.sqlite3'
assert not previous.exists() and not snapshot.exists(),'Recovery must be a single explicitly reviewed operation'
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(snapshot) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
snapshot.chmod(0o600);previous.write_bytes((folder/'qa-owned.json').read_bytes());previous.chmod(0o600)
rotated={}
for n,p in data['pairs']:
 salt=secrets.token_bytes(16);digest=hashlib.pbkdf2_hmac('sha256',password_bytes(p),salt,ITERATIONS)
 rotated[n]=(salt,digest,ITERATIONS)
temporary=folder/'qa-owned-recovered.tmp';nextproof=dict(proof,credentials={n:[s.hex().upper(),d.hex().upper(),i] for n,(s,d,i) in rotated.items()})
temporary.write_text(json.dumps(nextproof));temporary.chmod(0o600)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE');tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 for n in names:
  assert list(db.execute('SELECT hex(salt),hex(digest),iterations FROM accounts WHERE login=?',(n,)).fetchone())==proof['credentials'][n]
  for table in ('characters','wallets','owned_pets','battle_checkpoint_members'):
   assert table not in tables or db.execute('SELECT count(*) FROM '+table+' WHERE account=?',(n,)).fetchone()[0]==0
  assert db.execute('UPDATE accounts SET salt=?,digest=?,iterations=? WHERE login=?',(*rotated[n],n)).rowcount==1
 db.commit()
os.replace(temporary,folder/'qa-owned.json')
print(json.dumps(dict(rotated_only_owned_empty_accounts=2,consistent_recovery_backup=str(snapshot),
 previous_proof_preserved=str(previous),new_proof_sha256=hashlib.sha256((folder/'qa-owned.json').read_bytes()).hexdigest())))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rotate-owned-empty',action='store_true')
    parser.add_argument('--failed-report',type=Path,default=ROOT/'reports/stage4-economy/hosted-economy.json')
    parser.add_argument('--output',type=Path,default=ROOT/'reports/stage4-economy/qa-credential-recovery.json')
    args=parser.parse_args()
    failed=json.loads(args.failed_report.read_text(encoding='utf-8'))
    assert failed['passed'] is False and failed['error_type']=='RuntimeError'
    assert any(e['file']=='offsite_backup_windows.py' for e in failed['error_locations'])
    dummy=EconomyFixture('185.184.42.88','','',[],'')
    audit=dummy.remote(DISCOVER,dict(after=datetime.fromisoformat(failed['observed_utc']).timestamp()-30,before_count=179))
    audit['kind']='owned QA credential recovery after local ACL failure; no player account selected'
    if args.rotate_owned_empty:
        EconomyFixture.prepare_private_directory()
        fixture=EconomyFixture('185.184.42.88',audit['prefix'],audit['names'],[secrets.token_urlsafe(24) for _ in (0,1)],audit['backup'])
        fixture.save_private()
        audit['private_fixture']=fixture.credential_path
        result=fixture.remote(ROTATE,{**fixture.ownership_payload(), 'proof_sha256':audit['previous_proof_sha256'],
            'pairs':list(zip(fixture.names,fixture.passwords)),
            'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PINNED_SOURCES}})
        audit.update(result)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(audit))


if __name__=='__main__':main()
