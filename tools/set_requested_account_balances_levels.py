"""Scoped hosted update requested for admin/Sasamasa and player_two."""
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote

INSPECT=r'''
from contextlib import closing
import hashlib,json,pathlib,sqlite3,subprocess,sys,tomllib
from tio.character_identity import alias,owner_for_slot
from tio.protocol.pet_info import decode_pet_info
data=json.load(sys.stdin)
config=pathlib.Path('/etc/tio-server/server.toml')
path=pathlib.Path(tomllib.loads(config.read_text())['data_directory'])/'reservation.sqlite3'
assert path==pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
 db.execute('BEGIN')
 state=[]
 for login in ('admin','player_two'):
  assert db.execute('SELECT 1 FROM accounts WHERE login=?',(login,)).fetchone(),'Requested account missing'
  mappings=[(1,login)]+db.execute('SELECT slot,owner FROM character_identities WHERE login=? ORDER BY slot',(login,)).fetchall()
  characters=[]
  for slot,owner in mappings:
   row=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(owner,)).fetchone()
   if not row:continue
   assert owner_for_slot(db,login,slot)==owner==alias(login,slot)
   wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(owner,)).fetchone()
   assert wallet,'Existing team wallet required'
   pets=[]
   for pet_id,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(owner,)):
    f=decode_pet_info(raw,human_equipment=bool(human)).fields
    pets.append(dict(id=pet_id,human=bool(human),name=f['0x8c4489'].decode('cp1251'),resource=f['0x8c446f'],level=f['0x8c4aef'],xp=f['0x8c4b05'],hp=f['0x8c4ab1'],max_hp=f['0x8c4a07'],capacity=f['0x8c4b57'],pet_sha256=hashlib.sha256(raw).hexdigest(),inventory_sha256=hashlib.sha256(inventory).hexdigest()))
   checkpoints=db.execute('SELECT count(*) FROM battle_checkpoint_members WHERE account=?',(owner,)).fetchone()[0]
   pending_gold=db.execute('SELECT COALESCE(sum(gold),0) FROM bank_gold_payables WHERE account=?',(owner,)).fetchone()[0] if db.execute("SELECT 1 FROM sqlite_master WHERE name='bank_gold_payables'").fetchone() else 0
   characters.append(dict(slot=slot,owner=owner,name=row[0].decode('cp1251'),wallet=list(wallet),pets=pets,checkpoints=checkpoints,pending_gold=pending_gold))
  state.append(dict(login=login,characters=characters))
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 result=dict(accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],states=state,integrity=integrity,
  idle={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_settlement_jobs')})
result.update(service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip(),
 connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines()),
 sources={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in ('tio/level_progression.py','tio/weapon_proficiency.py','tio/weight.py','tio/protocol/pet_info.py','config/level_progression.json','config/weapon_proficiency.json','config/weight.json')})
print(json.dumps(result))
'''

UPDATE=r'''
from contextlib import closing
from dataclasses import replace
import hashlib,json,pathlib,shutil,sqlite3,subprocess,sys,tarfile,tempfile,tomllib
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.owned_pets import OwnedPetStore
from tio.level_progression import FLOORS,RULES,normalize
from tio.weapon_proficiency import ProficiencyRules,CAPS
from tio.weight import base_capacity
data=json.load(sys.stdin)
targets=data['targets']
assert [(t['login'],t['owner'],t['pet_id'],t['name']) for t in targets]==[('admin','admin',1,'Sasamasa'),('player_two','player_two',1,'PlayerTwo')]
path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
config=pathlib.Path('/etc/tio-server/server.toml')
assert pathlib.Path(tomllib.loads(config.read_text())['data_directory'])/path.name==path
assert {p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in data['sources']}==data['sources'],'Inspected source changed'
def idle():
 assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
 assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip(),'Game clients connected'
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
  for table in ('battle_checkpoints','battle_settlement_jobs'):assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,'Battle processing present'
def protected(db):
 result={}
 for table,sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
  quoted='"'+table.replace('"','""')+'"'
  query='SELECT * FROM '+quoted
  args=()
  if table=='wallets':query+=' WHERE account NOT IN (?,?)';args=tuple(t['owner'] for t in targets)
  if table=='owned_pets':query+=' WHERE NOT ((account=? AND pet_id=?) OR (account=? AND pet_id=?))';args=tuple(v for t in targets for v in (t['owner'],t['pet_id']))
  rows=db.execute(query,args).fetchall()
  result[table]=dict(schema=sql,rows=len(rows),sha256=hashlib.sha256(json.dumps(sorted(map(repr,rows))).encode()).hexdigest())
 return result
def update(db,*,fail=False):
 before=protected(db);states=[]
 for t in targets:
  assert db.execute('SELECT 1 FROM accounts WHERE login=?',(t['login'],)).fetchone()
  wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(t['owner'],)).fetchone()
  assert list(wallet or ())==t['wallet_before'],'Wallet changed after inspection'
  row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(t['owner'],t['pet_id'])).fetchone()
  assert row,'Target fighter missing'
  human,raw,inventory=bool(row[0]),bytes(row[1]),bytes(row[2])
  assert hashlib.sha256(raw).hexdigest()==t['pet_sha256'],'Fighter changed after inspection'
  old=decode_pet_info(raw,human_equipment=human);f=dict(old.fields)
  assert f['0x8c4489'].decode('cp1251')==t['name'] and f['0x8c43eb']==t['pet_id']
  old_level=f['0x8c4aef'];assert 1<=old_level<=4,'Requested change would lower level'
  resource=f['0x8c446f']
  assert f['0x8c4b05']<FLOORS[4],'Saved experience is above requested level'
  cap,total=ProficiencyRules().caps(4,human)
  f.update({'0x8c4aef':4,'0x8c4b05':max(f['0x8c4b05'],FLOORS[3]),
   '0x8c4a07':max(f['0x8c4a07']+(4-old_level)*RULES['hp_per_level'],RULES['initial_hp'][str(resource)]+3*RULES['hp_per_level']),
   '0x8c4b57':base_capacity(resource,4)})
  f.update(dict(zip(CAPS,(cap,total,cap))))
  packet=encode_pet_info(replace(old,fields=f))
  decoded=decode_pet_info(packet,human_equipment=human).fields
  allowed={'0x8c4aef','0x8c4b05','0x8c4a07','0x8c4b57',*CAPS}
  assert {k:v for k,v in old.fields.items() if k not in allowed}=={k:v for k,v in decoded.items() if k not in allowed}
  assert normalize(packet,human)==packet,'Progression would alter the updated save'
  assert OwnedPetStore.validate(packet,inventory,human)==t['pet_id']
  assert db.execute('UPDATE wallets SET credits=1000000,gold=1000000 WHERE account=?',(t['owner'],)).rowcount==1
  if fail:raise RuntimeError('Isolated transaction rollback test')
  assert db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,t['owner'],t['pet_id'])).rowcount==1
  saved=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(t['owner'],t['pet_id'])).fetchone()
  assert bytes(saved[1])==packet and bytes(saved[2])==inventory and bool(saved[0])==human
  assert db.execute('SELECT credits,gold FROM wallets WHERE account=?',(t['owner'],)).fetchone()==(1000000,1000000)
  states.append(dict(login=t['login'],owner=t['owner'],fighter=t['name'],level_before=old_level,level_after=4,
   xp_before=old.fields['0x8c4b05'],xp_after=decoded['0x8c4b05'],
   wallet_before=list(wallet),credits=1000000,gold=1000000,hp=decoded['0x8c4ab1'],max_hp=decoded['0x8c4a07'],
   inventory_sha256=hashlib.sha256(inventory).hexdigest(),pet_sha256=hashlib.sha256(packet).hexdigest()))
 assert protected(db)==before,'Other saved data changed'
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 return dict(states=states,other_rows_preserved=True,inventory_and_skills_preserved=True,integrity='ok')

idle()
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-requested-balances-levels-',dir='/root'))
folder.chmod(0o700)
with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(folder/path.name)) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
(folder/path.name).chmod(0o600)
with tarfile.open(folder/'previous-code-config.tar.gz','w:gz') as archive:
 for p in data['sources']:archive.add(p,arcname='code/'+p)
 archive.add(config,arcname='config/server.toml')
 archive.add('/etc/systemd/system/tio-server.service',arcname='systemd/tio-server.service')
(folder/'previous-code-config.tar.gz').chmod(0o600)
with tempfile.TemporaryDirectory(prefix='tio-requested-balances-check-') as testdir:
 pathlib.Path(testdir).chmod(0o700)
 trialpath=pathlib.Path(testdir)/path.name;shutil.copy2(folder/path.name,trialpath)
 with closing(sqlite3.connect(trialpath)) as db:
  initial={t['owner']:db.execute('SELECT credits,gold FROM wallets WHERE account=?',(t['owner'],)).fetchone() for t in targets}
  try:
   with db:
    db.execute('BEGIN IMMEDIATE');update(db,fail=True)
  except RuntimeError:pass
  else:raise AssertionError('Rollback test did not fail')
  assert initial=={t['owner']:db.execute('SELECT credits,gold FROM wallets WHERE account=?',(t['owner'],)).fetchone() for t in targets}
  with db:
   db.execute('BEGIN IMMEDIATE');trial=update(db)
idle()
with closing(sqlite3.connect(path)) as db,db:
 db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
 result=update(db)
result.update(backup=str(folder),isolated_copy_checked=True,rollback_verified=True,graphical_clients_used=False,
 source_sha256=data['sources'],service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip())
proof=folder/'change.json';proof.write_text(json.dumps(result,indent=2));proof.chmod(0o600)
print(json.dumps(result))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('inspect','update','verify'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    if args.command=='update':
        inspected=json.loads((ROOT/'reports/requested-admin-player-two/inspection.json').read_text(encoding='utf-8'))
        targets=[]
        for login,name in (('admin','Sasamasa'),('player_two','PlayerTwo')):
            state=next(s for s in inspected['states'] if s['login']==login)
            found=[(c,p) for c in state['characters'] for p in c['pets'] if p['name']==name]
            assert len(found)==1,'Ambiguous named fighter'
            character,pet=found[0]
            assert character['owner']==login and pet['id']==1
            assert not character['checkpoints'] and not character['pending_gold']
            targets.append(dict(login=login,owner=character['owner'],pet_id=pet['id'],name=name,wallet_before=character['wallet'],pet_sha256=pet['pet_sha256']))
        result=remote(UPDATE,dict(targets=targets,sources=inspected['sources']))
    else:
        result=remote(INSPECT,{})
        if args.command=='verify':
            changed=json.loads((ROOT/'reports/requested-admin-player-two/change.json').read_text(encoding='utf-8'))
            for expected in changed['states']:
                state=next(s for s in result['states'] if s['login']==expected['login'])
                character=next(c for c in state['characters'] if c['owner']==expected['owner'])
                pet=next(p for p in character['pets'] if p['id']==1)
                assert character['wallet']==[1000000,1000000]
                assert pet['name']==expected['fighter'] and pet['level']==4 and pet['xp']==7355
                assert pet['pet_sha256']==expected['pet_sha256'] and pet['inventory_sha256']==expected['inventory_sha256']
            assert result['integrity']=='ok' and 'ActiveState=active' in result['service']
            result['verified']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if args.command=='verify':
        print(json.dumps(dict(verified=True,integrity=result['integrity'],service=result['service'],states=[dict(login=s['login'],wallet=s['characters'][0]['wallet'],fighter=s['characters'][0]['pets'][0]['name'],level=s['characters'][0]['pets'][0]['level']) for s in result['states']]),indent=2))
    else:print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
