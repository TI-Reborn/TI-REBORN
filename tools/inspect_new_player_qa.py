"""Read-only hosted snapshots for the two approved new-player GUI accounts.

The sole optional remote write is --seal-ownership: an exclusive root0600
qa-owned.json inside the existing pre-registration backup. No database writes,
game connections, account creation, character creation or gameplay occur here.
Credentials and credential hashes never enter public reports or command lines.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA

PREFIX = 'qsa1496217'
NAMES = [PREFIX + 'a', PREFIX + 'b']
BACKUP = '/root/tio-before-surroundings-qa-1x0mvyet'
REPORTS = ROOT / 'reports/new-player'
BASELINE = REPORTS / 'before.json'

REMOTE = r'''
import collections,hashlib,hmac,json,os,pathlib,sqlite3,sys
from tio.protocol.character_create import decode_character_create
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_list import decode_item_list
from tio.appearance import appearance_bytes
from tio.locations import center
data=json.load(sys.stdin);names=data['names'];folder=pathlib.Path(data['backup']).resolve(strict=True)
assert names==['qsa1496217a','qsa1496217b'] and str(folder)=='/root/tio-before-surroundings-qa-1x0mvyet'
assert folder.is_dir() and folder.stat().st_uid==0
assert data['baseline']['backup']==str(folder) and data['baseline']['names']==names
def readonly(path):
 db=sqlite3.connect(pathlib.Path(path).as_uri()+'?mode=ro',uri=True)
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN');return db
old=readonly(folder/'reservation.sqlite3');db=readonly('/var/lib/tio-server/reservation.sqlite3')
assert old.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")}
old_tables={r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")}
assert not any(old.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
assert old.execute('SELECT count(*) FROM accounts').fetchone()[0]==data['baseline']['accounts_before']
for table,expected in data['baseline']['tables'].items():
 assert table in old_tables and old.execute('SELECT count(*) FROM "'+table.replace('"','""')+'"').fetchone()[0]==expected['count']
credentials={}
for n in names:
 row=db.execute('SELECT salt,digest,iterations FROM accounts WHERE login=?',(n,)).fetchone()
 assert row and len(row[0])==16 and len(row[1])==32 and 100000<=row[2]<=2000000
 credentials[n]=[row[0].hex().upper(),row[1].hex().upper(),row[2]]
proof={'prefix':'qsa1496217','names':names,'credentials':credentials}
proof_path=folder/'qa-owned.json';sealed=False
if data['seal']:
 assert len(data['passwords'])==2
 for n,password in zip(names,data['passwords']):
  salt,digest,iterations=credentials[n]
  assert hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode('ascii'),bytes.fromhex(salt),iterations),bytes.fromhex(digest))
 if proof_path.exists():
  assert not proof_path.is_symlink() and json.loads(proof_path.read_text())==proof
 else:
  descriptor=os.open(proof_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
  with os.fdopen(descriptor,'w') as output:
   output.write(json.dumps(proof)+'\n');output.flush();os.fsync(output.fileno())
  sealed=True
assert not proof_path.is_symlink() and proof_path.stat().st_uid==0 and proof_path.stat().st_mode&0o777==0o600
assert json.loads(proof_path.read_text())==proof
def quote(name):return '"'+name.replace('"','""')+'"'
def account_rows(table,account,columns='*'):
 if table not in tables:return []
 cursor=db.execute('SELECT '+columns+' FROM '+quote(table)+' WHERE account=?',(account,))
 return [dict(zip((c[0] for c in cursor.description),row)) for row in cursor]
owned_matches=set()
for table in tables:
 columns=[r[1] for r in db.execute('PRAGMA table_info('+quote(table)+')')]
 if 'account' in columns and 'match_id' in columns:
  owned_matches.update(r[0] for r in db.execute('SELECT match_id FROM '+quote(table)+' WHERE account IN (?,?)',names))
preservation={};changed=[]
for table in sorted(old_tables):
 assert table in tables,'Pre-existing table is missing'
 quoted=quote(table);columns=[r[1] for r in old.execute('PRAGMA table_info('+quoted+')')]
 assert columns==[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')],'Pre-existing schema changed'
 filters=[];params=[]
 for column in columns:
  if column in ('account','login') or column.endswith('_account'):
   filters.append('('+quote(column)+' IS NULL OR '+quote(column)+' NOT IN (?,?))');params.extend(names)
 if 'match_id' in columns and owned_matches:
  filters.append('(match_id IS NULL OR match_id NOT IN ('+','.join('?' for _ in owned_matches)+'))');params.extend(sorted(owned_matches))
 before=collections.Counter(map(repr,old.execute('SELECT * FROM '+quoted)))
 after=collections.Counter(map(repr,db.execute('SELECT * FROM '+quoted+(' WHERE '+' AND '.join(filters) if filters else ''),params)))
 equal=before==after
 preservation[table]={'preexisting_rows':sum(before.values()),'remaining_nonqa_rows':sum(after.values()),'identical':equal}
 if not equal:changed.append(table)
progress={};observations={}
for n in names:
 chars=[]
 for slot,name,request in db.execute('SELECT slot,name,request FROM characters WHERE account=? ORDER BY slot',(n,)):
  created=decode_character_create(bytes(request))
  chars.append({'slot':slot,'name':bytes(name).decode('ascii'),'sex':created.options[0],'request_options':list(created.options),'request_unknown_u16':created.unknown_u16})
 pets=[]
 for owner,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(n,)):
  pet=decode_pet_info(bytes(raw),human_equipment=bool(human));f=pet.fields
  inventory_owner,items,unknown=decode_item_list(bytes(inventory));assert inventory_owner==owner==f['0x8c43eb']
  pets.append({'id':owner,'human':bool(human),'name':f['0x8c4489'].decode('cp1251'),'resource':f['0x8c446f'],
   'selected_slot':f['0x8c44a6'],'appearance':list(appearance_bytes(pet)),'level':f['0x8c4aef'],
   'hp':f['0x8c4ab1'],'max_hp':f['0x8c4a07'],'xp':f['0x8c4b05'],
   'inventory':[{'instance':i.instance_id,'template':i.template_id,'count':i.count,'equipped':i.equipped,'slot':i.slot,'durability_words':list(i.unknown_words)} for i in items]})
 onboarding=account_rows('character_onboarding',n,'completed')
 location=account_rows('character_locations',n,'town_id,x,y')
 wallet=account_rows('wallets',n,'credits,gold')
 receipts=[];outside=0
 for row in account_rows('battle_rewards',n,'match_id,result,credits,gross,rental_tax,calculation'):
  calculation=json.loads(row.pop('calculation') or '{}')
  if not set(calculation.get('opponents',()))<=set(names):outside+=1;continue
  row['calculation']=calculation;receipts.append(row)
 awards=account_rows('achievement_awards',n,'id,body')
 for row in awards:row['body']=json.loads(row['body'])
 progress[n]={'characters':chars,'onboarding':onboarding,'pets':pets,
  'location':location,'effective_default_town':3 if not location else None,
  'effective_default_position':list(center(3)) if not location else None,'wallet':wallet,
  'experience_audit':sorted(account_rows('experience_battle_audit',n),key=lambda r:(r['match_id'],r['pet_id'])),
  'rewards':sorted(receipts,key=lambda r:r['match_id']),
  'achievements':{'counters':sorted(account_rows('achievement_counters',n,'metric,value'),key=lambda r:r['metric']),
   'awards':sorted(awards,key=lambda r:r['id']),'prizes':sorted(account_rows('achievement_prizes',n,'id,position,delivered'),key=lambda r:(r['id'],r['position']))}}
 # Own identifiers are already the report key, not repeated in every audit row.
 for row in progress[n]['experience_audit']:row.pop('account',None)
 observations[n]={'character_count':len(chars),'roster_count':len(pets),'empty_roster':not pets,
  'checkpoint_members':account_rows('battle_checkpoint_members',n,'match_id,owner_id'),
  'pending_settlement_jobs':account_rows('battle_settlement_jobs',n,'match_id,attempts,next_attempt,error_type'),
  'outside_scope_reward_rows_omitted':outside}
matches=[];outside_matches=0
if 'battle_checkpoint_members' in tables:
 for match_id in sorted({r['match_id'] for n in names for r in observations[n]['checkpoint_members']}):
  members=db.execute('SELECT account FROM battle_checkpoint_members WHERE match_id=?',(match_id,)).fetchall()
  if {r[0] for r in members}!=set(names):outside_matches+=1;continue
  row=db.execute('SELECT revision,payload,checksum,status FROM battle_checkpoints WHERE match_id=?',(match_id,)).fetchone()
  assert row and hashlib.sha256(row[1].encode()).hexdigest()==row[2]
  from tio.battle_snapshot import loads
  battle=loads(row[1])[0]['battle']
  roster=battle['reward_roster']
  if {r[0] for r in roster.values()}!=set(names) or battle['bots']:outside_matches+=1;continue
  field=battle['field'];turn=battle['arena']._turns.get(battle['room'].room_id)
  assert all(actor.owner_id in roster for actor in field._actors.values())
  matches.append({'match_id':match_id,'revision':row[0],'status':row[3],'town':battle['city_id'],
   'width':field.width,'height':field.height,'bots':0,'turn_owner':turn[0] if turn else None,
   'scene':{k:v for k,v in field.scene_metadata.items() if k in ('profile','variant','seed','width','height','town_id','mode','players')},
   'actors':[{'id':a.actor_id,'account':roster[a.owner_id][0],'owner':a.owner_id,'x':a.x,'y':a.y,'hp':a.health,'max_hp':a.max_health,'ap':a.action_points} for a in sorted(field._actors.values(),key=lambda a:a.actor_id)]})
counts={table:db.execute('SELECT count(*) FROM '+quote(table)).fetchone()[0] for table in ('accounts','characters','owned_pets','battle_rewards','battle_checkpoints','battle_settlement_jobs') if table in tables}
print(json.dumps({'read_only_database':True,'database_writes':0,'ownership_sealed':sealed,
 'remote_metadata_writes':int(sealed),'credentials_or_credential_hashes_reported':False,
 'backup':str(folder),'accounts_before':data['baseline']['accounts_before'],'counts':counts,
 'owned_accounts_absent_in_backup':True,'preexisting_data_preserved':not changed,
 'changed_preexisting_tables':changed,'preservation':preservation,'new_tables':sorted(tables-old_tables),
 'owned_progress':progress,'observations':observations,'owned_two_account_matches':matches,
 'outside_scope_matches_omitted':outside_matches},ensure_ascii=False))
'''


def report_path(path: Path, *, existing: bool = False) -> Path:
    if path.is_symlink():
        raise ValueError('Report symlinks are not accepted')
    resolved = path.resolve(strict=existing)
    if not resolved.is_relative_to(REPORTS.resolve()) or resolved.suffix != '.json':
        raise ValueError('Use a JSON report inside reports/new-player')
    return resolved


def progress_changes(before, after, path=''):
    """Return only owned field paths, never previous values or private data."""
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        return [change for key in sorted(set(before) | set(after)) for change in (
            [path + '/' + key] if key not in before or key not in after else
            progress_changes(before[key], after[key], path + '/' + key))]
    if isinstance(before, list):
        if len(before) != len(after):
            return [path]
        return [change for i, (left, right) in enumerate(zip(before, after))
                for change in progress_changes(left, right, path + '/' + str(i))]
    return [] if before == after else [path]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seal-ownership', action='store_true')
    parser.add_argument('--compare', type=Path, help='Previous immutable owned-progress snapshot for relogin comparison')
    args = parser.parse_args(argv)
    output = report_path(args.output)
    if output.exists():
        raise ValueError('Snapshot output already exists; choose a fresh filename')
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    if fixture.host != '185.184.42.88' or fixture.prefix != PREFIX or fixture.names != NAMES or fixture.backup != BACKUP:
        raise ValueError('Use only the approved new-player fixture and pre-registration backup')
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    if baseline.get('backup') != BACKUP or baseline.get('names') != NAMES or baseline.get('new_accounts_created') != 0:
        raise ValueError('Expected the pre-registration new-player baseline')
    prior = None
    if args.compare:
        prior = json.loads(report_path(args.compare, existing=True).read_text(encoding='utf-8'))
        if prior.get('backup') != BACKUP or set(prior.get('owned_progress', {})) != set(NAMES):
            raise ValueError('Comparison snapshot belongs to a different QA scope')
    ast.parse(REMOTE)
    result = fixture.remote(REMOTE, dict(backup=BACKUP, names=NAMES, baseline={
        'backup':BACKUP,'names':NAMES,'accounts_before':baseline['accounts_before'],'tables':baseline['tables']},
        seal=args.seal_ownership, passwords=fixture.passwords if args.seal_ownership else []))
    result['observed_utc'] = datetime.now(timezone.utc).isoformat()
    if prior:
        changes = progress_changes(prior['owned_progress'], result['owned_progress'])
        result['progress_comparison'] = {'prior':str(args.compare),'identical':not changes,'changed_owned_fields':changes}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'output':str(output),'database_writes':0,'remote_metadata_writes':result['remote_metadata_writes'],
        'preexisting_data_preserved':result['preexisting_data_preserved'],'counts':result['counts'],
        'own_accounts':len(result['owned_progress']),'own_matches':len(result['owned_two_account_matches']),
        'progress_identical':result.get('progress_comparison',{}).get('identical')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
