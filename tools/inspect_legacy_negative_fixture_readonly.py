"""Read only: inspect owned D roster against the pre-GUI negative fixture backup."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP

FOLDER = ROOT / 'reports/gameplay-completion/legacy-status-20261011/gui'
REMOTE = OWNERSHIP + r'''
from datetime import datetime,timezone
from contextlib import closing
import hashlib,subprocess
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.city_catalogs import decode_pet_shop
target=names[3]
assert target=='qs3110ad96d'
baseline=pathlib.Path(data['fixture_backup']).resolve()
assert baseline.parent==pathlib.Path('/root') and baseline.name.startswith('tio-before-legacy-negative-qa-')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def safe(value):
 if isinstance(value,bytes):return {'bytes':len(value),'sha256':sha(value)}
 return value
def rows(db,table):
 quoted='"'+table.replace('"','""')+'"'
 cols=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
 if not cols:return None
 key=next((c for c in ('account','login') if c in cols),None)
 if key is None:return {'columns':cols,'account_rows':None}
 return {'columns':cols,'account_rows':[{c:safe(v) for c,v in zip(cols,r)} for r in db.execute('SELECT * FROM '+quoted+' WHERE "'+key+'"=?',(target,))]}
def pets(db):
 out=[]
 for identity,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(target,)):
  f=decode_pet_info(raw,human_equipment=bool(human)).fields
  out.append(dict(pet_id=identity,human=bool(human),name=f['0x8c4489'].decode('cp1251'),resource=f['0x8c446f'],
   level=f['0x8c4aef'],xp=f['0x8c4b05'],selected=f['0x8c44a6'],hp=f['0x8c4ab1'],max_hp=f['0x8c4a07'],
   pet_sha256=sha(raw),inventory_sha256=sha(inventory)))
 return out
def offers_in(db):
 out=[]
 for town,resource,identity,raw in db.execute('SELECT town_id,resource,candidate_id,packet FROM random_hire_offers WHERE account=? ORDER BY candidate_id',(target,)):
  offer=decode_pet_shop(raw)[0]
  out.append(dict(town=town,resource=resource,candidate_id=identity,name=offer.name.decode('cp1251'),price_credits=offer.price_credits,packet_sha256=sha(raw)))
 return out
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db,closing(sqlite3.connect('file:'+str(baseline/'reservation.sqlite3')+'?mode=ro',uri=True)) as old:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
 old.execute('PRAGMA query_only=ON');old.execute('BEGIN')
 tables={t for t, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 chosen=('wallets','hired_candidates','characters','character_roster_creation','character_tutorials','locations','ability_states')
 own={t:rows(db,t) for t in chosen if t in tables}
 before={t:rows(old,t) for t in chosen if t in tables}
 journal_tables=[t for t in sorted(tables) if any(s in t for s in ('journal','event','receipt','audit')) and t!='accounts']
 journal={t:rows(db,t) for t in journal_tables}
 journal={t:r for t,r in journal.items() if r and r['account_rows']}
 offers=offers_in(db) if 'random_hire_offers' in tables else []
 previous_offers=offers_in(old) if 'random_hire_offers' in tables else []
 preservation={}
 with closing(sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True)) as foreign:
  foreign.execute('PRAGMA query_only=ON');foreign.execute('BEGIN')
  for table, in foreign.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
   if table not in tables:continue
   quoted='"'+table.replace('"','""')+'"'
   cols=[r[1] for r in foreign.execute('PRAGMA table_info('+quoted+')')]
   key=next((c for c in ('account','login') if c in cols),None)
   if key is None:continue
   original=sorted(map(repr,foreign.execute('SELECT * FROM '+quoted)))
   current=sorted(map(repr,db.execute('SELECT * FROM '+quoted+' WHERE "'+key+'" NOT IN ('+','.join('?' for _ in names)+')',names)))
   preservation[table]=dict(rows=len(original),exactly_preserved=original==current)
  foreign_count=foreign.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
 fresh_preservation={}
 for table, in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
  if table not in tables:continue
  quoted='"'+table.replace('"','""')+'"'
  cols=[r[1] for r in old.execute('PRAGMA table_info('+quoted+')')]
  key=next((c for c in ('account','login') if c in cols),None)
  if key is None:continue
  query='SELECT * FROM '+quoted+' WHERE "'+key+'" NOT IN ('+','.join('?' for _ in names)+')'
  original=set(map(repr,old.execute(query,names)));current=set(map(repr,db.execute(query,names)))
  fresh_preservation[table]=dict(before_rows=len(original),current_rows=len(current),removed_or_changed_rows=len(original-current),added_or_changed_rows=len(current-original),exactly_preserved=original==current)
 result=dict(read_only=True,observed_utc=datetime.now(timezone.utc).isoformat(),ownership_verified=True,account=target,
  current_pets=pets(db),pre_fixture_pets=pets(old),current=own,pre_fixture=before,current_offers=offers,pre_fixture_offers=previous_offers,
  scoped_event_tables=journal,fixture_backup=str(baseline),accounts_count=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
  original_foreign_accounts=foreign_count,foreign_tables_preservation=preservation,
  foreign_account_rows_preserved=all(r['exactly_preserved'] for r in preservation.values()),
  fresh_pre_fixture_foreign_tables=fresh_preservation,fresh_pre_fixture_foreign_account_rows_preserved=all(r['exactly_preserved'] for r in fresh_preservation.values()),
  battle_members=rows(db,'battle_checkpoint_members'),integrity=db.execute('PRAGMA quick_check').fetchone()[0])
rawlog=subprocess.check_output(['journalctl','-u','tio-server','--since',data['journal_since'],'-o','json','--no-pager'],text=True)
selected=[]
for line in rawlog.splitlines():
 try:event=json.loads(line)
 except ValueError:continue
 message=event.get('MESSAGE','')
 if not isinstance(message,str):continue
 # Event names are safe; runtime deliberately never logs packet/credential bytes.
 for name in ('hire_committed','hire_rejected','dismiss_committed','city_session_started','accepted','client_disconnected','session_stopped'):
  if message==name or message.endswith(' '+name):
   selected.append({'timestamp_us':event.get('__REALTIME_TIMESTAMP'),'event':name,'pid':event.get('_PID')});break
result['service_event_timeline']=selected
result['service_event_account_attribution']='Runtime event logger emits event names only, without account/session identity; timeline cannot attribute hires to D by itself.'
result['creation_timestamp_availability']='owned_pets and hired_candidates have no created timestamp; durable hire marker plus wallet delta proves hire path, not its exact time.'
result['fixture_preparation_utc']=datetime.fromtimestamp((baseline/'negative-fixture.json').stat().st_mtime,timezone.utc).isoformat()
result['source_callsite_evidence']={}
for path,tokens in {
 'tools/loopback_exchange.py':("packet[:1]==b'\\x63'",'self.hiring.hire(','hire_committed',"packet==b'\\x61'",'self.hiring.available('),
 'tio/roster_progression.py':('def hire(','UPDATE wallets SET credits=credits-','INSERT INTO owned_pets','INSERT INTO hired_candidates','DELETE FROM random_hire_offers','def grant_starters','if not created:return','def profile('),
 'server/runtime.py':('never send packet/credential bytes','class Events','LOG.log(level'),
}.items():
 raw=pathlib.Path(path).read_bytes();lines=raw.decode().splitlines()
 result['source_callsite_evidence'][path]=dict(sha256=sha(raw),calls=[{'line':i,'source':line.strip()} for i,line in enumerate(lines,1) if any(token in line for token in tokens)])
print(json.dumps(result))
'''

def main():
    fixture = FreshSurroundingsQA.load_private(ROOT / 'reports/arena-surroundings/private/qs3110ad96.json')
    receipt = json.loads((FOLDER / 'negative-fixture.json').read_text(encoding='utf-8'))
    result = fixture.remote(REMOTE, {**fixture.ownership_payload(), 'fixture_backup': receipt['backup'], 'journal_since': '2026-10-11 19:55:00 UTC'})
    destination = FOLDER / 'd-negative-fixture-after-world-readonly.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'evidence': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                      'account': result['account'], 'current_pets': result['current_pets'], 'wallet': result['current']['wallets'],
                      'hired_candidates': result['current']['hired_candidates'], 'foreign_account_rows_preserved': result['foreign_account_rows_preserved']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
