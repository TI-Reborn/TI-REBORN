"""Guarded clan-warfare code deployment preserving every hosted account/save."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

from tools import deploy_stage4_economy as guarded

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/clan-warfare'
NEW_FILES={'tio/alliances.py','tio/territories.py','tio/clan_ratings.py',
    'tio/assault_map.py','tio/assault_battle.py','tio/protocol/alliances.py',
    'tio/protocol/assault.py','tio/protocol/clan_ratings.py',
    'server/assault_arena.py','server/alliance_service.py','server/territory_service.py',
    'tools/manage_territories.py','config/territories.json','config/assault_maps.json'}
ALLOWED=NEW_FILES|{'tio/clans.py','tio/mine_claims.py','tio/battle_rewards.py',
    'tio/warehouse_queries.py','tio/locations.py','tio/cities.py','tio/team_scene.py',
    'tio/battle_snapshot.py','tio/protocol/clans.py','tio/protocol/presence.py',
    'tio/protocol/public_profile.py','tio/protocol/town_info.py',
    'tio/protocol/player_auction.py','server/clan_service.py','server/presence.py',
    'server/public_profile.py','server/team_arena.py','server/battle_reconnect.py',
    'server/battle_journal.py','server/battle_failures.py','server/mine_arena.py','server/multi.py',
    'tools/loopback_exchange.py','tools/survival_scene.py','evidence/zones_diagnostic.xml'}


def validate_candidate(name,raw):
    if name.endswith('.py'):compile(raw,name,'exec')
    elif name=='evidence/zones_diagnostic.xml':
        if len(raw)>2*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('Unexpected zones XML declarations or size')
        if ElementTree.fromstring(raw).tag!='towns':raise ValueError('Unexpected zones XML root')
    else:json.loads(raw)


def remote_program():
    old="allowed={'tio/wallets.py','tio/battle_rewards.py','tio/reward_policy.py','tio/ranks.py','tio/level_progression.py','config/level_progression.json','server/team_arena.py','tools/loopback_exchange.py'}"
    if guarded.DEPLOY.count(old)!=1:raise RuntimeError('Reviewed deployment program changed')
    code=guarded.DEPLOY.replace(old,'allowed=set('+repr(sorted(ALLOWED))+')')
    old_syntax="    if name.endswith('.py'):compile(raw,name,'exec')\n    else:json.loads(raw)"
    if code.count(old_syntax)!=1:raise RuntimeError('Reviewed candidate validator changed')
    new_syntax="""    if name.endswith('.py'):compile(raw,name,'exec')
    elif name=='evidence/zones_diagnostic.xml':
        if len(raw)>2*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise RuntimeError('Unexpected zones XML declarations or size')
        import xml.etree.ElementTree as ET
        if ET.fromstring(raw).tag!='towns':raise RuntimeError('Unexpected zones XML root')
    else:json.loads(raw)"""
    code=code.replace(old_syntax,new_syntax)
    code=code.replace('tio-stage4-economy','tio-clan-warfare').replace('tio-before-stage4-economy-',
        'tio-before-clan-warfare-').replace('.stage4-','.clan-warfare-')
    compile(code,'clan_warfare_deployment','exec')
    return code


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','deploy'))
    parser.add_argument('--files',nargs='+')
    parser.add_argument('--attempt',type=int,default=1)
    args=parser.parse_args()
    if not 1<=args.attempt<=100:parser.error('Expected bounded deployment attempt')
    folder=FOLDER if args.attempt==1 else FOLDER/('revision'+str(args.attempt))
    folder.mkdir(parents=True,exist_ok=True)
    manifest=folder/'deployment-manifest.json'
    code=remote_program()
    if args.action=='prepare':
        selected=sorted(set(args.files or ()))
        if not selected or not set(selected)<=ALLOWED:parser.error('Unexpected runtime files')
        if manifest.exists():parser.error('Preserve existing deployment manifest')
        baseline=json.loads((FOLDER/'remote-baseline.json').read_text(encoding='utf-8'))
        backup_path=folder/'pre-update-backup.json'
        if not backup_path.exists():backup_path=FOLDER/'pre-update-backup.json'
        complete=json.loads(backup_path.read_text(encoding='utf-8'))
        actual=guarded.remote(guarded.INSPECT,{'files':selected})
        entries={}
        for name,entry in actual.items():
            raw=(ROOT/name).read_bytes();after=hashlib.sha256(raw).hexdigest()
            if entry['sha256'] is None and name not in NEW_FILES:
                raise RuntimeError('Unexpected missing hosted file: '+name)
            if entry['sha256']==after:raise RuntimeError('Unchanged candidate: '+name)
            validate_candidate(name,raw)
            entries[name]={'before':entry['sha256'],'after':after}
            if entry['source'] is not None:
                saved=folder/'deployment-remote-before'/name
                saved.parent.mkdir(parents=True,exist_ok=True)
                with saved.open('x',encoding='utf-8',newline='') as output:output.write(entry['source'])
        data=dict(files=entries,guards=baseline['guards'],complete_backup=complete['backup'],
            complete_backup_files={n:e['sha256'] for n,e in complete['files'].items()},
            deployment_program_sha256=hashlib.sha256(code.encode()).hexdigest())
        with manifest.open('x',encoding='utf-8') as output:output.write(json.dumps(data,indent=2)+'\n')
        print(json.dumps(dict(prepared_files=selected,complete_backup=complete['backup'])))
    else:
        target=folder/'deployment.json'
        if target.exists():parser.error('Preserve existing deployment report')
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.pop('deployment_program_sha256')!=hashlib.sha256(code.encode()).hexdigest():
            raise RuntimeError('Deployment program changed after review')
        if not data['files'] or not set(data['files'])<=ALLOWED:raise ValueError('Unexpected candidate')
        for name,entry in data['files'].items():
            raw=(ROOT/name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['after']:raise RuntimeError('Candidate changed')
            entry['content']=base64.b64encode(raw).decode('ascii')
        report=guarded.remote(code,data)
        with target.open('x',encoding='utf-8') as output:output.write(json.dumps(report,indent=2)+'\n')
        if report.get('status')=='attention':raise RuntimeError('Live state prevents rollback; see report')
        print(json.dumps({n:report[n] for n in ('timestamp_utc','backup','service',
            'accounts_preserved','wallets_preserved','all_existing_tables_unchanged','source_parity')}))


if __name__=='__main__':main()
