"""Scoped gameplay updates: guarded sources, fresh hosted backups, no save upload.

Reuses the established deployment transaction and rollback policy. The caller
must provide an inspected baseline and successful checks of the exact revision.
"""
import argparse
import base64
import hashlib
import json
import inspect
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from tools import deploy_stage4_economy as guarded

ROOT=Path(__file__).resolve().parents[1]


def pristine_sc_catalog(db,rules):
    """Allow only server-owned initial lots/clock closure; never player bids."""
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'sc_auction_lots' not in tables:return
    for name in ('sc_auction_bots','sc_auction_receipts'):
        if db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]:raise RuntimeError('SC player operations prevent catalogue exception')
    offers={r['key']:r for r in rules['offers']}
    from tio.sc_auction import prize
    from tio.protocol.item_list import encode_item_list
    cursor=db.execute('SELECT * FROM sc_auction_lots');columns=[r[0] for r in cursor.description]
    lots={r['id']:r for row in cursor for r in (dict(zip(columns,row)),)}
    if len(lots)>rules['maximum_live_lots']+len(offers):raise RuntimeError('Unexpected initial SC catalogue size')
    for lot in lots.values():
        offer=offers.get(lot['offer_key'])
        if (offer is None or lot['bidder'] is not None or lot['bids'] or lot['message'] is not None
                or lot['expires_at'] is not None or lot['state'] not in ('active','unsold')
                or lot['price']!=lot['start_price'] or lot['ends']!=lot['started']+lot['duration']):
            raise RuntimeError('SC catalogue contains player or changed price state')
        expected=dict(currency=offer['currency'],start_price=offer['start_price'],fee=offer['bid_fee'],
            step=offer['price_step'],duration=offer['duration'],extension=offer['extension'],automatic=int(offer['automatic']))
        if any(lot[k]!=v for k,v in expected.items()):raise RuntimeError('SC catalogue does not match validated policy')
        if lot['item_packet']!=encode_item_list(0,(prize(offer),)):raise RuntimeError('SC system prize changed')
    history={}
    for lot,account,action,amount,automatic in db.execute('SELECT lot,account,action,amount,automatic FROM sc_auction_history'):
        if lot not in lots or account or automatic or action not in ('created','closed') or amount!=lots[lot]['start_price']:
            raise RuntimeError('SC history contains a player operation')
        history[lot,action]=history.get((lot,action),0)+1
    for lot,row in lots.items():
        if history.get((lot,'created'))!=1 or history.get((lot,'closed'),0)!=int(row['state']=='unsold'):
            raise RuntimeError('Unexpected SC catalogue history')

def source_path(folder,name):
    """Explicit bounded candidates preserve local-only work in shared files."""
    metadata=folder/'candidate-overrides.json'
    overrides=json.loads(metadata.read_text()) if metadata.exists() else {}
    if name not in overrides:return ROOT/name
    p=(folder/overrides[name]).resolve()
    if not p.is_relative_to(folder/'runtime') or p.is_symlink() or not valid_path(name):raise ValueError('Unsafe scoped candidate')
    return p


def valid_path(name):
    p=PurePosixPath(name)
    return (bool(p.parts) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name
            and (p.parts[0] in ('tio','server','tools') and p.suffix=='.py'
                 or p.parts[0]=='config' and len(p.parts)==2 and p.suffix=='.json'
                 or name in ('evidence/items_diagnostic.xml','evidence/skills_diagnostic.xml',
                             'evidence/zones_diagnostic.xml','evidence/customization_diagnostic.xml')))


def validate(name,raw):
    if not valid_path(name):raise ValueError('Unexpected runtime path')
    if name.endswith('.py'):compile(raw,name,'exec')
    elif name.endswith('.json'):json.loads(raw)
    else:
        if len(raw)>4*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('Unexpected XML size or declaration')
        ElementTree.fromstring(raw)


def program(files):
    code=guarded.DEPLOY
    original="allowed={'tio/wallets.py','tio/battle_rewards.py','tio/reward_policy.py','tio/ranks.py','tio/level_progression.py','config/level_progression.json','server/team_arena.py','tools/loopback_exchange.py'}"
    if code.count(original)!=1:raise RuntimeError('Established deploy whitelist changed')
    code=code.replace(original,'allowed=set('+repr(sorted(files))+')')
    old="""complete=Path(p['complete_backup'])
if complete.parent!=Path('/root') or not complete.name.startswith('tio-before-site-backups-'):raise ValueError('Invalid private backup path')
for name,expected in p['complete_backup_files'].items():
    if Path(name).name!=name or sha(complete/name)!=expected:raise RuntimeError('Complete pre-update backup changed')
"""
    if code.count(old)!=1:raise RuntimeError('Established backup guard changed')
    code=code.replace(old,'')
    code=code.replace("prefix='tio-before-stage4-economy-'","prefix='tio-before-gameplay-completion-'")
    code=code.replace('complete_backup=str(complete)','complete_backup=str(backup)')
    old="""    if name.endswith('.py'):compile(raw,name,'exec')
    else:json.loads(raw)
"""
    new="""    if name.endswith('.py'):compile(raw,name,'exec')
    elif name.endswith('.json'):json.loads(raw)
    else:
        from xml.etree import ElementTree
        if len(raw)>4*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Unexpected XML')
        ElementTree.fromstring(raw)
"""
    if code.count(old)!=1:raise RuntimeError('Established validator changed')
    code=code.replace(old,new)
    marker="    before=fingerprint(dbpath)\n"
    full="""    import tarfile
    with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as archive:
        for directory,pattern in (('server','*.py'),('tio','*.py'),('tools','*.py'),('config','*.json')):
            for path in sorted((root/directory).rglob(pattern)):
                archive.add(path,arcname=path.relative_to(root).as_posix())
        for path in sorted((root/'evidence').glob('*_diagnostic.xml')):
            archive.add(path,arcname=path.relative_to(root).as_posix())
        for name in ('server.toml','tio-server.service'):
            archive.add(backup/name,arcname='deployment/'+name)
"""
    if code.count(marker)!=1:raise RuntimeError('Established backup boundary changed')
    code=code.replace(marker,full+marker)
    if 'tio/sc_auction.py' in files:
        marker="    if any(after.get(n)!=entry for n,entry in before.items()):raise RuntimeError('Existing hosted tables changed across restart')\n    if any(entry['rows'] for n,entry in after.items() if n not in before):raise RuntimeError('Unexpected player rows after restart')\n"
        guarded_catalog="""    permitted=set()
    sys.path.insert(0,str(root))
    policy=json.loads((root/'config/sc_auction.json').read_text())
    for path in (backup/'reservation.sqlite3',dbpath):
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:pristine_sc_catalog(db,policy)
    with closing(sqlite3.connect((backup/'reservation.sqlite3').as_uri()+'?mode=ro',uri=True)) as old, closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as new:
        old_seq=dict(old.execute('SELECT name,seq FROM sqlite_sequence'))
        new_seq=dict(new.execute('SELECT name,seq FROM sqlite_sequence'))
        catalog={'sc_auction_lots','sc_auction_history'}
        if {k:v for k,v in old_seq.items() if k not in catalog}!={k:v for k,v in new_seq.items() if k not in catalog}:raise RuntimeError('Player item/account sequences changed')
    permitted={'sc_auction_lots','sc_auction_history','sqlite_sequence'}
    if any(after.get(n)!=entry for n,entry in before.items() if n not in permitted):raise RuntimeError('Existing hosted player tables changed across restart')
    if any(entry['rows'] for n,entry in after.items() if n not in before and n not in permitted):raise RuntimeError('Unexpected player rows after restart')
    catalogue_changes=sorted(n for n in permitted if before.get(n)!=after.get(n))
"""
        if code.count(marker)!=1:raise RuntimeError('Established preservation check changed')
        code=code.replace(marker,guarded_catalog)
        code=code.replace('all_existing_tables_unchanged=len(before),','all_existing_tables_unchanged=sum(after.get(n)==v for n,v in before.items()),\n        system_catalog_tables_changed=catalogue_changes,')
        code=code.replace('def sha(path):',inspect.getsource(pristine_sc_catalog)+'\ndef sha(path):',1)
    marker='except BaseException as failure:\n'
    failure_log="""    import traceback
    (backup/'deployment-failure.log').write_text(traceback.format_exc())
"""
    if code.count(marker)!=1:raise RuntimeError('Established rollback boundary changed')
    code=code.replace(marker,marker+failure_log)
    compile(code,'remote-gameplay-deployment','exec')
    return code


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','deploy'))
    parser.add_argument('--folder',required=True,type=Path)
    parser.add_argument('--files',nargs='+')
    args=parser.parse_args();folder=args.folder.resolve()
    if not folder.is_relative_to(ROOT/'reports/gameplay-completion') or folder.is_symlink():
        parser.error('Expected a gameplay-completion report folder')
    manifest=folder/'deployment-manifest.json'
    if args.action=='prepare':
        files=sorted(set(args.files or ()))
        if not files or not all(valid_path(n) for n in files):parser.error('Specify reviewed code/config files')
        if manifest.exists():raise ValueError('Preserve the previous deployment manifest')
        baseline=json.loads((folder/'remote-baseline.json').read_text(encoding='utf-8'))
        validation=json.loads((folder/'validation.json').read_text(encoding='utf-8'))
        if not validation.get('passed') or not validation.get('source_unchanged'):
            raise ValueError('Successful frozen-revision validation required')
        actual=guarded.remote(guarded.INSPECT,{'files':files})
        entries={}
        for name in files:
            raw=source_path(folder,name).read_bytes();validate(name,raw)
            digest=hashlib.sha256(raw).hexdigest()
            if validation['source_sha256'].get(name)!=digest:raise ValueError('Validated revision changed: '+name)
            previous=baseline['files'].get(name,{}).get('sha256')
            if actual[name]['sha256']!=previous:raise ValueError('Inspected remote revision changed: '+name)
            if previous==digest:raise ValueError('Unchanged file in candidate: '+name)
            entries[name]=dict(before=previous,after=digest,content=base64.b64encode(raw).decode())
        data=dict(files=entries,guards=baseline['guards'],phase=folder.name,
                  local_player_data_uploaded=False)
        with manifest.open('x',encoding='utf-8') as output:json.dump(data,output,indent=2)
        print(json.dumps(dict(prepared_files=files)))
    else:
        target=folder/'deployment.json'
        if target.exists():raise ValueError('Preserve the prior deployment report')
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if not data['files'] or not all(valid_path(n) for n in data['files']):raise ValueError('Unsafe manifest')
        for name,entry in data['files'].items():
            raw=source_path(folder,name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['after']:raise ValueError('Prepared revision changed: '+name)
            validate(name,raw)
        report=guarded.remote(program(data['files']),data)
        with target.open('x',encoding='utf-8') as output:json.dump(report,output,indent=2)
        if not report.get('source_parity'):raise RuntimeError('Deployment requires attention; inspect report')
        print(json.dumps({k:report[k] for k in ('timestamp_utc','backup','service','accounts_preserved',
            'wallets_preserved','all_existing_tables_unchanged','source_parity')}))


if __name__=='__main__':main()
