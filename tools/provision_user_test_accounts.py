"""Inspect/provision the user-requested Test1/Test2 hosted fixtures.

The remote database is authoritative. Never copy local saves to hosting.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import secrets
import tempfile
from types import SimpleNamespace
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
HOST = 'root@185.184.42.88'
SOURCES = ('server/accounts.py', 'tio/characters.py', 'tio/character_identity.py',
           'tio/onboarding.py', 'tio/roster_progression.py', 'tio/level_progression.py',
           'tio/owned_pets.py', 'tio/db_transaction.py', 'tio/locations.py',
           'config/level_progression.json', 'config/roster_progression.json',
           'evidence/owned_pet_trial.json')
SOURCES += ('tio/equipment.py', 'tio/durability.py', 'tio/weapons.py',
            'tio/weapon_proficiency.py', 'tio/weight.py', 'tio/enhancement_limits.py',
            'config/weight.json', 'config/weapon_catalog.json',
            'config/weapon_proficiency.json', 'evidence/items_diagnostic.xml')

APPLY = r'''
from dataclasses import replace
import hashlib,json,pathlib,secrets,sqlite3
from server.accounts import identity,password_bytes,ITERATIONS
from tio.characters import CharacterStore
from tio.character_identity import alias
from tio.db_transaction import transaction
from tio.roster_progression import profile
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list,decode_item_list
from tio.owned_pets import OwnedPetStore
from tio.level_progression import FLOORS,RULES,normalize
from tio.weapon_proficiency import ProficiencyRules
from tio.weight import base_capacity,inventory_weight
from tio.locations import LocationStore,center
from tio.equipment import EquipmentStore,armor_rules
from tio.weapons import WeaponCatalog
from tio.durability import definitions

BANDS=((4,6),(7,10),(11,15),(16,20))
LOGINS=('test1','test2')
OWNERS=tuple(alias(n,s) for n in LOGINS for s in range(1,5))

def fingerprint(db):
 result={}
 marks=','.join('?' for _ in OWNERS)
 for table,sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
  quoted='"'+table.replace('"','""')+'"'
  columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
  owner=next((c for c in ('account','login','owner') if c in columns),None)
  query='SELECT * FROM '+quoted
  rows=db.execute(query+' WHERE "'+owner+'" NOT IN ('+marks+')',OWNERS).fetchall() if owner else db.execute(query).fetchall()
  result[table]=dict(schema=sql,rows=len(rows),sha256=hashlib.sha256(json.dumps(sorted(map(repr,rows))).encode()).hexdigest())
 return result

def blueprint(title,lo,hi):
 rows=[(1+(lv-lo)%2,lv,title if lv==lo else 'HumanL'+str(lv)) for lv in range(lo,hi+1)]
 for resource,label in ((3,'Doberman'),(4,'Husky'),(5,'Shepherd')):
  rows.extend((resource,lv,label+'L'+str(lv)) for lv in (lo,hi))
 rows.append((6,hi,'MinerL'+str(hi)))
 return rows

def roster(path,db,owner,title,lo,hi,template):
 armor=armor_rules();weapons=WeaponCatalog()
 rules={i:(16,128) for i in weapons.weapons if i not in (300,333,337)}
 rules.update({i:(r['slot'],) for i,r in armor.items()})
 equipment=EquipmentStore(path,rules,armor=armor,weapons_only=True)
 next_item=1
 records=[]
 for pet_id,(resource,lv,name) in enumerate(blueprint(title,lo,hi),1):
  human=resource in (1,2,6)
  look=bytes((1,0,0,1,0,0)) if resource==1 else bytes((2,8,0,1,0,0)) if resource==2 else None
  raw=profile(template,pet_id,resource,name.encode(),look)
  pet=decode_pet_info(raw,human_equipment=human)
  hp=RULES['initial_hp'][str(resource)]+(lv-1)*RULES['hp_per_level']
  fields={**pet.fields,'0x8c4aef':lv,'0x8c4b05':FLOORS[lv-1],
   '0x8c4a07':hp,'0x8c4ab1':hp,'0x8c4b57':base_capacity(resource,lv),
   '0x8c44a6':pet_id if pet_id<=3 else 0}
  raw=ProficiencyRules().normalize(encode_pet_info(replace(pet,fields=fields)),human)
  gear=(304,208,210,212) if resource in (1,2) else (335,262,258,259) if resource==6 else (255,)
  items=[]
  for item_id in gear:
   durability=int(definitions()[item_id].get('durability','1'))
   items.append(ItemRecord(next_item,item_id,bytes(2),1,0,0,(durability,)*3,bytes(4),None,bytes(3)))
   next_item+=1
  if resource in (1,2):
   ammo=weapons.weapons[304].ammo_id
   items.append(ItemRecord(next_item,ammo,bytes(2),50,0,0,(1,)*3,bytes(4),None,bytes(3)))
   next_item+=1
  for item in tuple(items):
   if item.template_id not in gear:continue
   slot=armor[item.template_id]['slot'] if item.template_id in armor else 16
   items=equipment.place(raw,human,items,item.instance_id,slot)
  inventory=encode_item_list(pet_id,items)
  weight=inventory_weight(inventory)
  assert weight<=base_capacity(resource,lv),'Overloaded test fighter'
  pet=decode_pet_info(raw,human_equipment=human)
  raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4b6d':weight}))
  assert normalize(raw,human)==raw,'XP/level normalization changed fixture'
  assert OwnedPetStore.validate(raw,inventory,human)==pet_id
  db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(owner,pet_id,int(human),raw,inventory))
  if pet_id>1:db.execute('INSERT OR IGNORE INTO hired_candidates VALUES (?,?,?)',(owner,0x30000000+pet_id,pet_id))
  records.append(dict(id=pet_id,name=name,resource=resource,level=lv,xp=FLOORS[lv-1],hp=hp,weight=weight,items=[i.template_id for i in items]))
 db.execute('INSERT INTO item_sequences VALUES (?,?)',(owner,next_item))
 return records

def apply(path,pairs,*,fail=False):
 assert tuple(n for n,p in pairs)==LOGINS
 for n,p in pairs:identity(n);password_bytes(p)
 template=bytes.fromhex(json.loads(pathlib.Path('evidence/owned_pet_trial.json').read_text())['packet_hex'])
 with transaction(path) as db:
  before=fingerprint(db)
  assert not any(db.execute('SELECT 1 FROM accounts WHERE lower(login)=?',(n,)).fetchone() for n in LOGINS),'Requested account exists; never reset it'
  assert not any(db.execute('SELECT 1 FROM characters WHERE account=?',(n,)).fetchone() for n in OWNERS),'Unexpected existing save'
  titles=[n.capitalize() if s==1 else n.capitalize()+'L'+str(BANDS[s-1][0]) for n in LOGINS for s in range(1,5)]
  assert not any(db.execute('SELECT 1 FROM characters WHERE name_key=?',(n.lower(),)).fetchone() for n in titles),'Requested character name exists'
  store=CharacterStore(path);LocationStore(path)
  states=[]
  for login,password in pairs:
   salt=secrets.token_bytes(16);digest=hashlib.pbkdf2_hmac('sha256',password_bytes(password),salt,ITERATIONS)
   db.execute('INSERT INTO accounts VALUES (?,?,?,?)',(login,salt,digest,ITERATIONS))
   for slot,(lo,hi) in enumerate(BANDS,1):
    title=login.capitalize() if slot==1 else login.capitalize()+'L'+str(lo)
    store.create(login,CharacterCreateRequest(title.encode(),0,(1,0,0,0)))
    owner=store.owner(login,slot)
    assert owner==alias(login,slot)
    if fail:raise RuntimeError('Injected local rollback check')
    db.execute('DELETE FROM owned_pets WHERE account=?',(owner,))
    pets=roster(path,db,owner,title,lo,hi,template)
    db.execute('UPDATE wallets SET credits=1000000,gold=1000000 WHERE account=?',(owner,))
    db.execute('INSERT INTO paid_services VALUES (?,2,5)',(owner,))
    db.execute('UPDATE character_onboarding SET completed=1 WHERE account=?',(owner,))
    # These user-requested admin test characters bypass the fresh-player tutorial.
    db.execute('UPDATE character_tutorials SET step=4,completed=1,match_id=NULL,observed_events=15 WHERE account=?',(owner,))
    LocationStore._save(db,owner,3,*center(3))
    assert len(pets)<=12 and {r['level'] for r in pets}==set(range(lo,hi+1))
    assert {r['resource'] for r in pets}==set(range(1,7))
    states.append(dict(login=login,slot=slot,owner=owner,character=title,band=[lo,hi],pets=pets,credits=1000000,gold=1000000))
   assert len(store.list(login))==4
  after=fingerprint(db)
  assert before==after,'Existing hosted rows or schema changed'
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 return dict(states=states,existing_rows_preserved=True,integrity='ok')
'''

CREATE = APPLY + r'''
import os,subprocess,sys,tarfile,tempfile,tomllib
data=json.load(sys.stdin)
path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
config=pathlib.Path('/etc/tio-server/server.toml')
assert pathlib.Path(tomllib.loads(config.read_text())['data_directory'])/path.name==path
actual={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in data['source_sha256']}
assert actual==data['source_sha256'],'Inspected source changed'
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
def idle():
 assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip(),'Game connections present'
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
  for t in ('battle_checkpoints','battle_settlement_jobs'):assert db.execute('SELECT count(*) FROM '+t).fetchone()[0]==0,'Retained battle present'
  for n in LOGINS:assert not db.execute('SELECT 1 FROM accounts WHERE lower(login)=?',(n,)).fetchone(),'Account already exists'
idle()
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-user-test-accounts-',dir='/root'))
folder.chmod(0o700)
with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(folder/path.name) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 count=dst.execute('SELECT count(*) FROM accounts').fetchone()[0]
(folder/path.name).chmod(0o600)
with tarfile.open(folder/'previous-code-config.tar.gz','w:gz') as archive:
 for p in data['source_sha256']:archive.add(p,arcname='code/'+p)
 archive.add(config,arcname='config/server.toml')
 archive.add('/etc/systemd/system/tio-server.service',arcname='systemd/tio-server.service')
(folder/'previous-code-config.tar.gz').chmod(0o600)
idle()
result=apply(path,data['pairs'])
with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:after=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
assert after==count+2
result.update(backup=str(folder),accounts_before=count,accounts_after=after,source_sha256=actual,
 service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip())
proof=folder/'creation.json';proof.write_text(json.dumps(result,indent=2));proof.chmod(0o600)
print(json.dumps(result))
'''

REMOTE_SELFTEST = APPLY + r'''
import sys,tempfile
from contextlib import closing
data=json.load(sys.stdin)
actual={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in data['source_sha256']}
assert actual==data['source_sha256']
with tempfile.TemporaryDirectory(prefix='tio-test-accounts-dryrun-') as folder:
 pathlib.Path(folder).chmod(0o700)
 path=pathlib.Path(folder)/'fixture.sqlite3'
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(path)) as dst:
  src.backup(dst)
 path.chmod(0o600)
 with closing(sqlite3.connect(path)) as db:before=fingerprint(db)
 pairs=[(n,'LocalOnlyTestPassword123') for n in LOGINS]
 try:apply(path,pairs,fail=True)
 except RuntimeError:pass
 else:raise AssertionError('Missing rollback failure')
 with closing(sqlite3.connect(path)) as db:assert fingerprint(db)==before
 result=apply(path,pairs)
 try:apply(path,pairs)
 except AssertionError:pass
 else:raise AssertionError('Missing duplicate rejection')
 print(json.dumps(dict(passed=True,production_database_changed=False,remote_source_sha256=actual,rollback_verified=True,duplicate_rejected=True,existing_rows_preserved=True,characters=len(result['states']),fighters=sum(len(s['pets']) for s in result['states']))))
'''

INSPECT = r'''
import hashlib,json,pathlib,sqlite3,subprocess,sys
data=json.load(sys.stdin)
config=pathlib.Path('/etc/tio-server/server.toml')
import tomllib
settings=tomllib.loads(config.read_text())
path=pathlib.Path(settings['data_directory'])/'reservation.sqlite3'
assert path==pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 conflicts={n:bool(db.execute('SELECT 1 FROM accounts WHERE lower(login)=?',(n,)).fetchone()) for n in ('test1','test2')}
 characters=[]
 for n in ('test1','test1l7','test1l11','test1l16','test2','test2l7','test2l11','test2l16'):
  if db.execute('SELECT 1 FROM characters WHERE name_key=?',(n,)).fetchone():characters.append(n)
 schemas={t:db.execute("SELECT sql FROM sqlite_master WHERE name=?",(t,)).fetchone()[0] for t in ('accounts','characters','owned_pets','wallets','paid_services','character_tutorials','character_onboarding','locations') if t in tables}
 idle={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_settlement_jobs') if t in tables}
 result=dict(accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],
  integrity=db.execute('PRAGMA integrity_check').fetchone()[0],conflicts=conflicts,
  character_conflicts=characters,schemas=schemas,idle=idle)
result.update(service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip(),
 connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines()),
 source_sha256={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in data['source_sha256']},multi_account=settings['multi_account'],tls=settings.get('tls',{}).get('enabled'))
print(json.dumps(result))
'''


def remote(code, payload):
    command = 'cd /opt/tio-emulator && .venv/bin/python -c ' + shlex.quote(code)
    result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/tio_server'),
        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', HOST, command],
        input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True,
        timeout=90)
    if result.returncode:
        raise RuntimeError('Remote operation failed: '+result.stderr[-3000:])
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('inspect','selftest','remote-selftest','create'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists(),'Output already exists'
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
    if args.command=='inspect':
        result=remote(INSPECT,dict(source_sha256=hashes))
        result['source_parity']=result['source_sha256']==hashes
    elif args.command=='selftest':
        sys.path.insert(0,str(ROOT))
        from server.accounts import Accounts
        from tio.characters import CharacterStore
        from tio.protocol.character_create import CharacterCreateRequest
        from tio.locations import LocationStore
        import sqlite3
        ns={};exec(APPLY,ns)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.sqlite3'
            Accounts(path).create('existinguser','OnlyLocalTestPassword123')
            CharacterStore(path).create('existinguser',CharacterCreateRequest(b'Existinguser',0,(1,0,0,0)))
            LocationStore(path)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE paid_services(account TEXT NOT NULL,service INTEGER NOT NULL,level INTEGER NOT NULL,PRIMARY KEY(account,service))')
                db.execute('CREATE TABLE item_sequences(account TEXT PRIMARY KEY,next_id INTEGER NOT NULL)')
                before=ns['fingerprint'](db)
            pairs=[(n,'LocalTestPassword12345') for n in ('test1','test2')]
            try:ns['apply'](path,pairs,fail=True)
            except RuntimeError:pass
            else:raise AssertionError('Fault injection did not fail')
            with closing(sqlite3.connect(path)) as db:assert ns['fingerprint'](db)==before
            result=ns['apply'](path,pairs)
            try:ns['apply'](path,pairs)
            except AssertionError:pass
            else:raise AssertionError('Duplicate accounts were accepted')
            result=dict(passed=True,rollback_verified=True,duplicate_rejected=True,existing_rows_preserved=result['existing_rows_preserved'],characters=len(result['states']),fighters=sum(len(s['pets']) for s in result['states']))
    elif args.command=='remote-selftest':
        inspected=json.loads((ROOT/'reports/user-test-accounts/inspection-final.json').read_text())
        result=remote(REMOTE_SELFTEST,dict(source_sha256=inspected['source_sha256']))
    else:
        checked=json.loads((ROOT/'reports/user-test-accounts/remote-selftest.json').read_text())
        assert checked['passed'] and checked['production_database_changed'] is False
        private=ROOT/'.secrets'/'user-test-accounts-20261010.json'
        assert not private.exists(),'Credentials already exist; inspect before retrying'
        pairs=[(n,secrets.token_urlsafe(12)) for n in ('test1','test2')]
        private.parent.mkdir(parents=True,exist_ok=True)
        with private.open('x',encoding='utf-8') as f:json.dump(dict(host=HOST,pairs=pairs),f,indent=2)
        result=remote(CREATE,dict(source_sha256=checked['remote_source_sha256'],pairs=pairs))
        result['credentials_path']=str(private)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    summary={k:v for k,v in result.items() if k!='states'}
    if 'states' in result:summary['characters']=[dict(login=s['login'],name=s['character'],band=s['band'],fighters=len(s['pets'])) for s in result['states']]
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
