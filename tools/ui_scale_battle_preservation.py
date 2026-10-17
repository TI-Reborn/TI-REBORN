"""Current-epoch preservation for the exact retained UI battle QA pair.

Archival provisioning ownership remains authoritative and unmodified. This
module does not create accounts, login, start matches or modify hosted data.
Explicit prepare creates a root-private online SQLite/code/config backup.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP, PRIVATE, require

PREFIX = 'qsa1496217'
NAMES = [PREFIX+'a', PREFIX+'b']
FIXTURE = PRIVATE/(PREFIX+'.json')
SCHEMA = 'ui-scale-battle-preservation/v1'
BACKUP_PREFIX = 'tio-before-ui-scale-battle-qa-'

# Executed both remotely and in offline SQLite tests. No row contents leave
# the process; Counter comparison preserves duplicates as well as full values.
SNAPSHOT_HELPERS = r'''
from collections import Counter
def account_rows(connection, names):
 schema=list(connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
 rows={}
 for table, in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence' ORDER BY name"):
  quoted='"'+table.replace('"','""')+'"'
  columns=[r[1] for r in connection.execute('PRAGMA table_info('+quoted+')')]
  account=next((c for c in ('account','login') if c in columns),None)
  if account is None:continue
  sql='SELECT * FROM '+quoted+' WHERE ("'+account+'" IS NULL OR "'+account+'" NOT IN ('+','.join('?' for _ in names)+'))'
  rows[table]=Counter(map(repr,connection.execute(sql,names)))
 return schema,rows
def compare_account_rows(before,after):
 assert before[0]==after[0],'Hosted database schema changed during this QA epoch'
 assert before[1].keys()==after[1].keys(),'Account-table scope changed during this QA epoch'
 for table,rows in before[1].items():
  assert rows==after[1][table],'Current-epoch foreign account data changed in '+table
 return {table:sum(rows.values()) for table,rows in before[1].items()}
'''

# The server clocks its shared catalogue every .5 seconds, independently of
# accounts. A long native GUI test can cross an unsold lot deadline. Accept
# only a complete, bounded, byte-exact replay of the actual stock tick into
# an in-memory copy; no player row, old history row or arbitrary lot edit is
# exempted. This helper belongs only to the retained UI QA pair/epoch.
CATALOGUE_CLOCK_HELPERS = r'''
def catalogue_clock(before,after,epoch,now,auction):
 from contextlib import contextmanager
 def table(c,name):
  return list(c.execute('SELECT * FROM '+name+' ORDER BY 1'))
 def indexed(c,name):
  cursor=c.execute('SELECT * FROM '+name+' ORDER BY id')
  columns=[x[0] for x in cursor.description]
  return {r[0]:dict(zip(columns,r)) for r in cursor}
 original=indexed(before,'sc_auction_history');current=indexed(after,'sc_auction_history')
 assert original.keys()<=current.keys(),'An existing SC history row was removed'
 assert all(original[k]==current[k] for k in original),'An existing SC history row changed'
 added={k:v for k,v in current.items() if k not in original}
 old_lots=indexed(before,'sc_auction_lots');live_lots=indexed(after,'sc_auction_lots')
 if not added:
  assert old_lots==live_lots,'SC lots changed without a catalogue clock event'
  return Counter(),dict(added_history_rows=0,actual_stock_tick_replay=True,player_operations_exempted=0)
 assert 0<=now-epoch<=3600,'Catalogue clock proof is limited to this one-hour QA epoch'
 assert len(added)<=64,'Catalogue clock delta exceeds the bounded QA epoch'
 assert min(added)>max(original,default=0),'SC history append reused an old identity'
 assert all(r['account']=='' and r['automatic']==0 and r['action'] in ('created','closed') and
            epoch<=r['occurred']<=now for r in added.values()),'SC delta includes player activity or an invalid clock event'
 touched={r['lot'] for r in added.values()}
 assert old_lots.keys()<=live_lots.keys(),'An SC lot was removed'
 assert all(old_lots[k]==live_lots[k] for k in old_lots if k not in touched),'An unrelated SC lot changed'
 assert set(live_lots)-set(old_lots)<=touched,'An SC lot was created without matching clock history'
 for key in touched:
  assert key in live_lots,'SC clock history has an unknown lot'
  lot=live_lots[key]
  assert (lot['bidder'] is None and lot['bids']==0 and lot['message'] is None and lot['expires_at'] is None and
          lot['state'] in ('active','unsold') and lot['price']==lot['start_price']), 'SC clock touched player-owned lot state'
  references=[r for r in old_lots.values() if r['offer_key']==lot['offer_key']]
  assert references and lot['item_packet']==max(references,key=lambda r:r['generation'])['item_packet'], 'SC clock prize differs from the original epoch catalogue'
  if key in old_lots:
   prior=old_lots[key]
   assert (prior['state']=='active' and prior['bidder'] is None and prior['bids']==0 and prior['message'] is None and
           prior['expires_at'] is None and prior['price']==prior['start_price']), 'SC clock altered an existing player lot'
  assert not before.execute('SELECT 1 FROM sc_auction_bots WHERE lot=?',(key,)).fetchone(), 'A catalogue clock lot has a prepaid player bot'
 for name in ('sc_auction_bots','sc_auction_receipts'):
  assert table(before,name)==table(after,name),'SC player operations changed during catalogue clock proof'
 timestamps=sorted({r['occurred'] for r in added.values()})
 # The stock auto-bid branch can consult an account through store.path.
 # Reject any such player branch before redirecting tick to the in-memory
 # transaction, so replay cannot open another database even for a read.
 for lot in old_lots.values():
  if lot['state']=='active' and lot['automatic'] and any(lot['ends']-1<=stamp<lot['ends'] for stamp in timestamps):
   assert lot['bidder'] is None and not before.execute('SELECT 1 FROM sc_auction_bots WHERE lot=?',(lot['id'],)).fetchone(), 'SC clock replay overlaps a player auto-bid window'
 replay=sqlite3.connect(':memory:');before.backup(replay)
 @contextmanager
 def memory_transaction(path):
  assert path==':ui-scale-offline-catalogue-replay:'
  yield replay
 saved_transaction=auction.transaction
 try:
  auction.transaction=memory_transaction
  store=object.__new__(auction.SCAuctionStore)
  store.path=':ui-scale-offline-catalogue-replay:';store.rules=auction.policy()
  def reject_random_choice(_):raise AssertionError('A catalogue clock replay attempted a player bot bid')
  store.choose=reject_random_choice
  for timestamp in timestamps:store.tick(now=timestamp)
 finally:
  auction.transaction=saved_transaction
 for name in ('sc_auction_lots','sc_auction_history','sc_auction_bots','sc_auction_receipts'):
  assert table(replay,name)==table(after,name),'Stock SC timer replay differs in '+name
 replay.close()
 cursor=after.execute('SELECT * FROM sc_auction_history');raw=[r for r in cursor if r[0] in added]
 return Counter(map(repr,raw)),dict(added_history_rows=len(added),
  actions=dict(Counter(r['action'] for r in added.values())),touched_lots=len(touched),
  actual_stock_tick_replay=True,all_original_history_rows_unchanged=True,all_other_lots_unchanged=True,
  player_operations_exempted=0,caller_attribution='stock-clock-transition; individual caller not instrumented')

def compare_epoch_rows(old,live,names,meta):
 import sys,time
 sys.path.insert(0,'/opt/tio-emulator')
 from tio import sc_auction as auction
 assert pathlib.Path(auction.__file__).resolve()==pathlib.Path('/opt/tio-emulator/tio/sc_auction.py')
 epoch=int(datetime.datetime.fromisoformat(meta['created_utc']).timestamp())
 appended,clock=catalogue_clock(old,live,epoch,int(time.time()),auction)
 before=account_rows(old,names);after=account_rows(live,names)
 assert 'sc_auction_history' in after[1]
 assert not appended-after[1]['sc_auction_history'],'Clock rows do not belong to the protected history scope'
 after[1]['sc_auction_history'].subtract(appended)
 checked=compare_account_rows(before,after)
 clock['stock_source_sha256']=meta['sources']['/opt/tio-emulator/tio/sc_auction.py']
 clock['timer_source_sha256']=meta['sources']['/opt/tio-emulator/server/economy_runtime.py']
 clock['server_loop_source_sha256']=meta['sources']['/opt/tio-emulator/server/multi.py']
 clock['policy_sha256']=meta['sources']['/opt/tio-emulator/config/sc_auction.json']
 return checked,clock
'''

REMOTE_HELPERS = r'''
import hashlib,os,shutil,subprocess,tarfile,tempfile,datetime
EXPECTED_NAMES=['qsa1496217a','qsa1496217b']
assert names==EXPECTED_NAMES,'Only the exact retained UI QA pair is permitted'
def digest(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def healthy_idle():
 assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
 assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).strip(),'A player is online; epoch preparation aborted'
 with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as connection:
  assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  for table in ('battle_checkpoint_members','battle_checkpoints','battle_settlement_jobs'):
   assert connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0,'A battle/settlement is active; epoch preparation aborted'
def sources():
 root=pathlib.Path('/opt/tio-emulator');result={}
 for name in ('server','tio','config'):
  directory=root/name
  assert directory.is_dir(),'Hosted code/config directory missing'
  for path in sorted(directory.rglob('*')):
   if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.pyo'):
    result[str(path)]=digest(path)
 for path in sorted(root.glob('*.py')):
  result[str(path)]=digest(path)
 project=root/'pyproject.toml'
 if project.is_file():result[str(project)]=digest(project)
 config=pathlib.Path('/etc/tio-server/server.toml');assert config.is_file()
 fragment=pathlib.Path(subprocess.check_output(['systemctl','show','tio-server','-p','FragmentPath','--value'],text=True).strip()).resolve()
 assert fragment.is_file() and fragment.parent in (pathlib.Path('/etc/systemd/system'),pathlib.Path('/lib/systemd/system'),pathlib.Path('/usr/lib/systemd/system'))
 result[str(config)]=digest(config);result[str(fragment)]=digest(fragment)
 return result
def epoch_record(request):
 destination=pathlib.Path(request['backup']).resolve()
 assert destination.parent==pathlib.Path('/root') and destination.name.startswith('tio-before-ui-scale-battle-qa-')
 raw=(destination/'epoch.json').read_bytes()
 assert hashlib.sha256(raw).hexdigest()==request['metadata_sha256'],'Epoch receipt hash differs'
 meta=json.loads(raw)
 assert meta['schema']=='ui-scale-battle-preservation/v1' and meta['names']==EXPECTED_NAMES
 assert meta['ownership_backup']==str(folder),'Archival fixture ownership backup differs'
 assert meta['ownership_proof_sha256']==digest(folder/'qa-owned.json')
 assert meta['ownership_database_sha256']==digest(folder/'reservation.sqlite3')
 assert meta['database_sha256']==digest(destination/'reservation.sqlite3'),'Epoch database backup changed'
 assert meta['archive_sha256']==digest(destination/'previous-code-config.tar.gz'),'Epoch code/config backup changed'
 assert meta['sources']==sources(),'Hosted code/config changed during this QA epoch'
 return destination,meta
'''

PREPARE = OWNERSHIP + REMOTE_HELPERS + SNAPSHOT_HELPERS + r'''
healthy_idle();before_sources=sources()
destination=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-ui-scale-battle-qa-',dir='/root'))
destination.chmod(0o700)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as live,sqlite3.connect(destination/'reservation.sqlite3') as saved:
 live.backup(saved)
 assert saved.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 snapshot=account_rows(saved,names)
(destination/'reservation.sqlite3').chmod(0o600)
with tarfile.open(destination/'previous-code-config.tar.gz','w:gz') as archive:
 for path in before_sources:
  archive.add(path,arcname=path.lstrip('/'),recursive=False)
(destination/'previous-code-config.tar.gz').chmod(0o600)
shutil.copy2('/etc/tio-server/server.toml',destination/'server.toml')
(destination/'server.toml').chmod(0o600)
healthy_idle();assert sources()==before_sources,'Hosted code/config changed while taking epoch backup'
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as live:
 checked=compare_account_rows(snapshot,account_rows(live,names))
meta=dict(schema='ui-scale-battle-preservation/v1',names=names,ownership_backup=str(folder),
 ownership_proof_sha256=digest(folder/'qa-owned.json'),ownership_database_sha256=digest(folder/'reservation.sqlite3'),
 database_sha256=digest(destination/'reservation.sqlite3'),archive_sha256=digest(destination/'previous-code-config.tar.gz'),
 sources=before_sources,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
raw=(json.dumps(meta,sort_keys=True,indent=2)+'\n').encode()
(destination/'epoch.json').write_bytes(raw);(destination/'epoch.json').chmod(0o600)
print(json.dumps(dict(schema=meta['schema'],backup=str(destination),metadata_sha256=hashlib.sha256(raw).hexdigest(),
 created_utc=meta['created_utc'],database_sha256=meta['database_sha256'],archive_sha256=meta['archive_sha256'],
 owned_names=names,source_files=len(before_sources),integrity='ok',existing_account_rows_preserved=checked,
 archival_ownership_unchanged=True,online=0,checkpoint=None,match_started=False)))
'''

PRESERVATION = OWNERSHIP + REMOTE_HELPERS + SNAPSHOT_HELPERS + CATALOGUE_CLOCK_HELPERS + r'''
destination,meta=epoch_record(data['epoch'])
with sqlite3.connect('file:'+str(destination/'reservation.sqlite3')+'?mode=ro',uri=True) as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 checked,clock=compare_epoch_rows(old,db,names,meta)
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?)',names).fetchone(),'Owned checkpoint remains'
 print(json.dumps(dict(integrity='ok',existing_account_rows_preserved=checked,
  epoch_backup=str(destination),epoch_metadata_sha256=data['epoch']['metadata_sha256'],
  excluded_owned_pair_on_both_sides=True,archival_ownership_unchanged=True,hosted_code_config_unchanged=True,
  autonomous_catalogue_clock=clock)))
'''

PRESERVATION_DURING_OWNED_MATCH = OWNERSHIP + REMOTE_HELPERS + SNAPSHOT_HELPERS + CATALOGUE_CLOCK_HELPERS + r'''
destination,meta=epoch_record(data['epoch'])
assert re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',data['match'])
with sqlite3.connect('file:'+str(destination/'reservation.sqlite3')+'?mode=ro',uri=True) as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 checked,clock=compare_epoch_rows(old,db,names,meta)
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 members=sorted(db.execute('SELECT account,match_id FROM battle_checkpoint_members'))
 assert members==sorted((name,data['match']) for name in names),'Retained epoch comparison requires only the exact owned match/pair'
 assert list(db.execute('SELECT match_id FROM battle_checkpoints'))==[(data['match'],)],'Unexpected retained checkpoint set'
 print(json.dumps(dict(integrity='ok',existing_account_rows_preserved=checked,
  epoch_backup=str(destination),epoch_metadata_sha256=data['epoch']['metadata_sha256'],
  excluded_owned_pair_on_both_sides=True,archival_ownership_unchanged=True,hosted_code_config_unchanged=True,
  exact_owned_retained_match=data['match'],autonomous_catalogue_clock=clock)))
'''


def validate_fixture(fixture):
    require(fixture.host == '185.184.42.88' and fixture.prefix == PREFIX and fixture.names == NAMES,
            'Epoch preservation permits only the exact retained two-account UI QA pair')
    require(Path(fixture.credential_path).resolve() == FIXTURE.resolve(),
            'Epoch preservation requires the original private fixture path')


def validate_receipt(receipt):
    require(receipt.get('schema') == SCHEMA and receipt.get('owned_names') == NAMES and
            receipt.get('archival_ownership_unchanged') is True and receipt.get('match_started') is False,
            'Unexpected UI battle epoch receipt scope')
    path = receipt.get('backup', '')
    require(re.fullmatch(r'/root/'+BACKUP_PREFIX+r'[a-zA-Z0-9_-]+', path) is not None,
            'Epoch backup must be a dedicated root-private backup')
    require(re.fullmatch('[0-9a-f]{64}', receipt.get('metadata_sha256','')) is not None,
            'Epoch receipt metadata hash is invalid')
    return receipt


def prepare(fixture, receipt_path):
    validate_fixture(fixture)
    receipt = validate_receipt(fixture.remote(PREPARE, fixture.ownership_payload()))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        old=json.loads(receipt_path.read_text(encoding='utf-8'))
        stamp=hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()[:16]
        receipt_path.with_name(receipt_path.stem+'-previous-'+stamp+'.json').write_bytes(receipt_path.read_bytes())
    receipt_path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


class CurrentEpochFixture(FreshSurroundingsQA):
    @classmethod
    def wrap(cls, fixture, receipt):
        validate_fixture(fixture);validate_receipt(receipt)
        result=cls(fixture.host,fixture.prefix,list(fixture.names),list(fixture.passwords),
                   fixture.backup,fixture.key,fixture.credential_path)
        result.epoch=receipt
        return result

    def preservation(self):
        validate_fixture(self);validate_receipt(self.epoch)
        # self.backup always remains the archival provisioning backup used by
        # all inherited mutation/credential guards; only comparison is current.
        return self.remote(PRESERVATION,{**self.ownership_payload(),'epoch':self.epoch})

    def preservation_during_owned_match(self,match):
        validate_fixture(self);validate_receipt(self.epoch)
        return self.remote(PRESERVATION_DURING_OWNED_MATCH,
                           {**self.ownership_payload(),'epoch':self.epoch,'match':match})


def self_test():
    import sqlite3
    scope={};exec(SNAPSHOT_HELPERS,scope)
    before=sqlite3.connect(':memory:');after=sqlite3.connect(':memory:')
    for db in (before,after):
        db.executescript('CREATE TABLE accounts(login TEXT,value BLOB); CREATE TABLE items(account TEXT,value BLOB);')
        db.executemany('INSERT INTO accounts VALUES (?,?)',[(NAMES[0],b'owned-a'),(NAMES[1],b'owned-b'),('foreign',b'existing')])
        db.executemany('INSERT INTO items VALUES (?,?)',[(NAMES[0],b'item-a'),(NAMES[1],b'item-b'),('foreign',b'foreign-item'),(None,b'unassigned')])
    snapshot=scope['account_rows'](before,NAMES)
    after.execute('UPDATE accounts SET value=? WHERE login=?',(b'own-change',NAMES[0]))
    after.execute('DELETE FROM items WHERE account=?',(NAMES[1],))
    checked=scope['compare_account_rows'](snapshot,scope['account_rows'](after,NAMES))
    assert checked=={'accounts':1,'items':2}
    rejected=0
    for sql,args in (('UPDATE accounts SET value=? WHERE login=?',(b'foreign-change','foreign')),
                     ('INSERT INTO accounts VALUES (?,?)',('new-foreign',b'new')),
                     ('UPDATE items SET value=? WHERE account IS NULL',(b'null-change',)),
                     ('INSERT INTO items VALUES (?,?)',('foreign',b'foreign-item'))):
        after.execute('SAVEPOINT test_case');after.execute(sql,args)
        try:scope['compare_account_rows'](snapshot,scope['account_rows'](after,NAMES))
        except AssertionError:rejected+=1
        else:raise AssertionError('Foreign row mutation was accepted')
        after.execute('ROLLBACK TO test_case');after.execute('RELEASE test_case')
    after.execute('CREATE TABLE unexpected(account TEXT)')
    try:scope['compare_account_rows'](snapshot,scope['account_rows'](after,NAMES))
    except AssertionError:rejected+=1
    else:raise AssertionError('Schema mutation was accepted')
    fixture=FreshSurroundingsQA('185.184.42.88',PREFIX,NAMES,['x','y'],'/root/tio-before-surroundings-qa-original',credential_path=str(FIXTURE))
    validate_fixture(fixture)
    for attribute,value in (('host','elsewhere'),('prefix','qs00000000'),('names',[NAMES[0],'foreign']),('credential_path',str(PRIVATE/'other.json'))):
        old=getattr(fixture,attribute);setattr(fixture,attribute,value)
        try:validate_fixture(fixture)
        except AssertionError:rejected+=1
        else:raise AssertionError('Foreign fixture scope was accepted')
        setattr(fixture,attribute,old)
    for code in (PREPARE,PRESERVATION,PRESERVATION_DURING_OWNED_MATCH):compile(code,'<epoch program>','exec')
    assert rejected==9
    clock=clock_self_test()
    return dict(result='PASS',offline_cases=12+clock['offline_cases'],foreign_changes_rejected=5,wrong_fixture_scope_rejected=4,
                owned_changes_allowed=True,rows_with_null_account_preserved=True,duplicates_preserved=True,
                schema_changes_rejected=True,network_used=False,hosted_mutations=False,catalogue_clock=clock)


def clock_self_test():
    """Execute the actual stock tick on disposable SQLite data, then attack it."""
    import sqlite3
    import tempfile
    from contextlib import closing
    from tio import sc_auction as auction
    scope={'sqlite3':sqlite3};exec(SNAPSHOT_HELPERS+CATALOGUE_CLOCK_HELPERS,scope)
    with tempfile.TemporaryDirectory(prefix='ui-scale-catalogue-proof-') as folder:
        path=Path(folder)/'disposable.sqlite3'
        store=auction.SCAuctionStore(path);store.tick(now=1000)
        old=sqlite3.connect(':memory:')
        with closing(sqlite3.connect(path)) as source:source.backup(old)
        counter,proof=scope['catalogue_clock'](old,old,1200,1400,auction)
        assert not counter and proof['added_history_rows']==0
        store.tick(now=1300)
        after=sqlite3.connect(':memory:')
        with closing(sqlite3.connect(path)) as source:source.backup(after)
        counter,proof=scope['catalogue_clock'](old,after,1200,1400,auction)
        assert proof['added_history_rows']==4 and proof['actions']=={'closed':2,'created':2}
        assert sum(counter.values())==4 and proof['player_operations_exempted']==0
        failed=0
        cases=(
            "UPDATE sc_auction_history SET account='foreign' WHERE id=4",
            "UPDATE sc_auction_history SET automatic=1 WHERE id=4",
            "UPDATE sc_auction_history SET action='bid' WHERE id=4",
            "UPDATE sc_auction_history SET amount=999 WHERE id=4",
            "UPDATE sc_auction_history SET occurred=1199 WHERE id=4",
            "UPDATE sc_auction_history SET occurred=1401 WHERE id=4",
            "UPDATE sc_auction_history SET lot=999 WHERE id=4",
            "UPDATE sc_auction_history SET amount=999 WHERE id=1",
            "DELETE FROM sc_auction_history WHERE id=1",
            "UPDATE sc_auction_lots SET price=101 WHERE id=1",
            "UPDATE sc_auction_lots SET bidder='foreign',bids=1 WHERE id=1",
            "UPDATE sc_auction_lots SET item_packet=x'1234' WHERE id=4",
            "UPDATE sc_auction_lots SET started=1301,ends=1601 WHERE id=4",
            "UPDATE sc_auction_lots SET generation=999 WHERE id=4",
            "UPDATE sc_auction_lots SET state='unsold' WHERE id=3",
            "DELETE FROM sc_auction_lots WHERE id=3",
            "INSERT INTO sc_auction_bots VALUES (1,'foreign',0,0,1,5)",
            "INSERT INTO sc_auction_receipts VALUES ('foreign','request','hash','{}',1300)",
        )
        for sql in cases:
            after.execute('SAVEPOINT attack');after.execute(sql)
            try:scope['catalogue_clock'](old,after,1200,1400,auction)
            except AssertionError:failed+=1
            else:raise AssertionError('Catalogue clock accepted an invalid transition')
            after.execute('ROLLBACK TO attack');after.execute('RELEASE attack')
        try:scope['catalogue_clock'](old,after,1200,4901,auction)
        except AssertionError:failed+=1
        else:raise AssertionError('Expired QA clock scope was accepted')
        player_old=sqlite3.connect(':memory:');player_after=sqlite3.connect(':memory:')
        old.backup(player_old);after.backup(player_after)
        for db in (player_old,player_after):
            db.execute("UPDATE sc_auction_lots SET bidder='foreign',bids=1,ends=1301 WHERE id=3")
            db.commit()
        try:scope['catalogue_clock'](player_old,player_after,1200,1400,auction)
        except AssertionError:failed+=1
        else:raise AssertionError('A foreign auto-bid read was allowed during clock replay')
        player_old.close();player_after.close()
        # A second authentic cycle is bounded and verified from the same
        # immutable epoch, rather than discarding arbitrary later history.
        store.tick(now=1600)
        later=sqlite3.connect(':memory:')
        with closing(sqlite3.connect(path)) as source:source.backup(later)
        counter,proof=scope['catalogue_clock'](old,later,1200,1700,auction)
        assert proof['added_history_rows']==10 and sum(counter.values())==10
        old.close();after.close();later.close()
    return dict(result='PASS',offline_cases=23,invalid_transitions_rejected=failed,
                actual_stock_tick_executed=True,full_lot_and_history_replay=True,
                all_old_history_rows_preserved=True,no_player_operations_exempted=True,
                network_used=False,hosted_mutations=False)
