"""Adjust only owned QA account D's level/XP for the actual lobby GUI check.

Credentials are loaded through FreshSurroundingsQA and never returned or sent to
the remote operation. Every mutation repeats archival ownership, makes a fresh
online SQLite backup, and checks preservation in the authoritative database.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP

FOLDER = ROOT / 'reports/gameplay-completion/legacy-status-20261011/gui'
FIXTURE = ROOT / 'reports/arena-surroundings/private/qs3110ad96.json'

COMMON = OWNERSHIP + r'''
from collections import Counter
from contextlib import closing
from dataclasses import replace
import hashlib,subprocess,tempfile,tomllib
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.level_progression import FLOORS,normalize
from tio.owned_pets import OwnedPetStore

assert names==['qs3110ad96a','qs3110ad96b','qs3110ad96c','qs3110ad96d']
target=names[3]
dbpath=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
assert pathlib.Path(tomllib.loads(pathlib.Path('/etc/tio-server/server.toml').read_text())['data_directory'])/dbpath.name==dbpath
assert FLOORS[0]==0 and FLOORS[3]==7355

def sha(raw):return hashlib.sha256(raw).hexdigest()

def guard(db):
 assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
 connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
 assert connections==0,'A game/TLS connection is established; no fixture mutation permitted'
 counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')}
 assert not any(counts.values()),'Active/retained battle or settlement present'
 assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]==208
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 return dict(service='active',established_game_tls_connections=connections,**counts)

def inspect(db):
 result=[]
 for account in names:
  pets=[]
  for identity,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)):
   pet=decode_pet_info(raw,human_equipment=bool(human))
   pets.append(dict(pet_id=identity,human=bool(human),level=pet.fields['0x8c4aef'],xp=pet.fields['0x8c4b05'],
                    selected=pet.fields['0x8c44a6'],pet_sha256=sha(raw),inventory_sha256=sha(inventory)))
  assert pets and pets[0]['pet_id']==1 and pets[0]['human']
  result.append(dict(account=account,pets=pets))
 assert result[0]['pets'][0]['level']==result[2]['pets'][0]['level']==1
 assert len(result[3]['pets'])==1
 return result

def protected(db):
 result={}
 for table,sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
  quoted='"'+table.replace('"','""')+'"'
  columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
  rows=db.execute('SELECT * FROM '+quoted).fetchall()
  if table=='owned_pets':
   account_index=columns.index('account');pet_index=columns.index('pet_id');packet_index=columns.index('pet_packet')
   rows=[tuple('<authorized D packet>' if index==packet_index and row[account_index]==target and row[pet_index]==1 else value for index,value in enumerate(row)) for row in rows]
  result[table]=dict(schema_sha256=sha(sql.encode()),rows=len(rows),sha256=sha(json.dumps(sorted(map(repr,rows))).encode()))
 return result

def foreign_preservation(db,baseline_path=None):
 checked={}
 with closing(sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True)) as archive:
  # Archival backup proves the 204 original accounts remain unchanged. Other
  # save tables can have legitimate recovery/timer changes predating this QA;
  # preserve those against the new online backup made for this operation.
  assert archive.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]==204
  assert Counter(archive.execute('SELECT * FROM accounts').fetchall())==Counter(db.execute('SELECT * FROM accounts WHERE login NOT IN (?,?,?,?)',names).fetchall())
 if baseline_path is None:
  baseline=db;owned_connection=None
 else:
  owned_connection=sqlite3.connect('file:'+str(baseline_path)+'?mode=ro',uri=True);baseline=owned_connection
 try:
  old=baseline
  for table,sql in old.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
   quoted='"'+table.replace('"','""')+'"'
   columns=[r[1] for r in old.execute('PRAGMA table_info('+quoted+')')]
   account=next((c for c in ('account','login') if c in columns),None)
   if account is None:continue
   assert db.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]==sql
   before=old.execute('SELECT * FROM '+quoted+' WHERE "'+account+'" NOT IN (?,?,?,?)',names).fetchall()
   after=db.execute('SELECT * FROM '+quoted+' WHERE "'+account+'" NOT IN (?,?,?,?)',names).fetchall()
   assert Counter(before)==Counter(after),'Foreign account data changed in '+table
   checked[table]=dict(rows=len(before),sha256=sha(json.dumps(sorted(map(repr,before))).encode()))
 finally:
  if owned_connection is not None:owned_connection.close()
 assert checked['accounts']['rows']==204
 return dict(original_accounts_preserved=204,account_tables=checked)

def backup():
 saved_folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-legacy-negative-qa-',dir='/root'))
 saved_folder.chmod(0o700)
 with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(saved_folder/dbpath.name)) as saved:
  source.backup(saved)
  assert saved.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 (saved_folder/dbpath.name).chmod(0o600)
 return saved_folder
'''

INSPECT = COMMON + r'''
with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('BEGIN')
 state=guard(db);accounts=inspect(db);foreign=foreign_preservation(db)
print(json.dumps(dict(passed=True,read_only=True,guard=state,accounts=accounts,preservation=foreign,
 sources={p:sha(pathlib.Path(p).read_bytes()) for p in ('tio/level_progression.py','config/level_progression.json','tio/protocol/pet_info.py','tio/owned_pets.py')})))
'''

MUTATE = COMMON + r'''
action=data['action'];assert action in ('prepare','restore')
with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('BEGIN')
 guard(db);inspect(db);foreign_preservation(db)
sources={p:sha(pathlib.Path(p).read_bytes()) for p in ('tio/level_progression.py','config/level_progression.json','tio/protocol/pet_info.py','tio/owned_pets.py')}
assert sources==data['sources'],'Inspected source changed'
saved_folder=backup()
restore_from=None
if action=='restore':
 restore_from=pathlib.Path(data['restore_from']).resolve()
 assert restore_from.parent==pathlib.Path('/root') and restore_from.name.startswith('tio-before-legacy-negative-qa-')
 receipt=json.loads((restore_from/'negative-fixture.json').read_text())
 assert receipt['action']=='prepare' and receipt['account']==target and receipt['pet_id']==1
 with closing(sqlite3.connect('file:'+str(restore_from/dbpath.name)+'?mode=ro',uri=True)) as old:
  prior=old.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(target,)).fetchone()
  assert prior and prior[0]==1 and sha(prior[1])==receipt['before']['pet_sha256']
  old_fields=decode_pet_info(prior[1],human_equipment=True).fields
  assert old_fields['0x8c4aef']==1 and old_fields['0x8c4b05']==FLOORS[0]
 level,xp=old_fields['0x8c4aef'],old_fields['0x8c4b05']
else:level,xp=4,FLOORS[3]
with closing(sqlite3.connect(dbpath)) as db,db:
 db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
 state=guard(db);before_accounts=inspect(db);preserved=protected(db);foreign=foreign_preservation(db,saved_folder/dbpath.name)
 row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(target,)).fetchone()
 assert row and row[0]==1
 pet=decode_pet_info(row[1],human_equipment=True);fields=dict(pet.fields)
 assert fields['0x8c43eb']==1
 if action=='prepare':assert fields['0x8c4aef']==1 and fields['0x8c4b05']==FLOORS[0]
 else:assert fields['0x8c4aef']==4 and fields['0x8c4b05']==FLOORS[3]
 before=dict(level=fields['0x8c4aef'],xp=fields['0x8c4b05'],pet_sha256=sha(row[1]),inventory_sha256=sha(row[2]))
 fields.update({'0x8c4aef':level,'0x8c4b05':xp})
 packet=encode_pet_info(replace(pet,fields=fields));decoded=decode_pet_info(packet,human_equipment=True)
 assert {k:v for k,v in decoded.fields.items() if k not in ('0x8c4aef','0x8c4b05')}=={k:v for k,v in pet.fields.items() if k not in ('0x8c4aef','0x8c4b05')}
 assert normalize(packet,True)==packet,'Progression normalization would change the prepared packet'
 assert OwnedPetStore.validate(packet,row[2],True)==1
 assert db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(packet,target)).rowcount==1
 assert protected(db)==preserved,'Data outside D packet changed'
 after_accounts=inspect(db)
 assert before_accounts[:3]==after_accounts[:3],'A/B/C changed'
 after=dict(level=decoded.fields['0x8c4aef'],xp=decoded.fields['0x8c4b05'],pet_sha256=sha(packet),inventory_sha256=sha(row[2]))
 assert before['inventory_sha256']==after['inventory_sha256']
 state=guard(db);assert foreign_preservation(db,saved_folder/dbpath.name)==foreign
result=dict(passed=True,action=action,account=target,pet_id=1,human=True,before=before,after=after,
            backup=str(saved_folder),restored_from=str(restore_from) if restore_from else None,
            changed_fields=['level','xp'],a_b_c_exactly_preserved=True,all_other_rows_exactly_preserved=True,
            protected_tables=len(preserved),preservation=foreign,guard=state,sources=sources,
            authoritative_database=str(dbpath),graphical_clients_used=False,local_player_data_uploaded=False)
proof=saved_folder/'negative-fixture.json';proof.write_text(json.dumps(result,indent=2));proof.chmod(0o600)
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'prepare', 'restore'))
    args = parser.parse_args()
    compile(INSPECT, '<read-only owned fixture inspect>', 'exec')
    compile(MUTATE, '<owned D level/XP fixture>', 'exec')
    fixture = FreshSurroundingsQA.load_private(FIXTURE)
    assert fixture.host == '185.184.42.88' and fixture.prefix == 'qs3110ad96'
    assert fixture.names == ['qs3110ad96' + c for c in 'abcd']
    inspected = fixture.remote(INSPECT, fixture.ownership_payload())
    FOLDER.mkdir(parents=True, exist_ok=True)
    if args.action == 'inspect':
        output = FOLDER / 'negative-fixture-inspection.json'
        result = inspected
    else:
        output = FOLDER / ('negative-fixture.json' if args.action == 'prepare' else 'negative-fixture-restored.json')
        assert not output.exists(), 'Do not overwrite the authoritative mutation receipt'
        payload = {**fixture.ownership_payload(), 'action': args.action, 'sources': inspected['sources']}
        if args.action == 'restore':
            receipt = json.loads((FOLDER / 'negative-fixture.json').read_bytes())
            assert receipt['passed'] and receipt['account'] == fixture.names[3] and receipt['action'] == 'prepare'
            payload['restore_from'] = receipt['backup']
        result = fixture.remote(MUTATE, payload)
        assert result['passed'] and result['after']['level'] == (4 if args.action == 'prepare' else 1)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
