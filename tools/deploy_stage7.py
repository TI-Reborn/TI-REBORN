"""Guarded stage7 code deployment preserving every hosted account/save."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

from tools import deploy_stage4_economy as guarded

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/stage7'
NEW_FILES=set(['config/mail.json', 'config/rating_seasons.json', 'config/special_items.json', 'server/mail_service.py', 'server/team_ranked.py', 'tio/battle_hazards.py', 'tio/character_identity.py', 'tio/mail.py', 'tio/protocol/battle_mines.py', 'tio/protocol/mail.py', 'tio/rating_seasons.py', 'tio/team_ratings.py', 'tools/manage_team_seasons.py'])
ALLOWED=NEW_FILES|set(['config/city_catalogs.json', 'server/assault_arena.py', 'server/battle_events.py', 'server/battle_failures.py', 'server/battle_journal.py', 'server/battle_reconnect.py', 'server/mine_arena.py', 'server/multi.py', 'server/presence.py', 'server/team_arena.py', 'tio/arena_service.py', 'tio/battle_rewards.py', 'tio/battle_snapshot.py', 'tio/battle_state.py', 'tio/characters.py', 'tio/combat.py', 'tio/onboarding.py', 'tio/protocol/player_auction.py', 'tio/team_scene.py', 'tio/weapon_effects.py', 'tools/loopback_exchange.py'])
ALLOWED|={'tio/protocol/battle_attack.py','config/weapon_catalog.json','evidence/items_diagnostic.xml'}


def validate_candidate(name,raw):
    if name.endswith('.py'):compile(raw,name,'exec')
    elif name=='evidence/items_diagnostic.xml':
        if len(raw)>2*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('Unexpected zones XML declarations or size')
        if ElementTree.fromstring(raw).tag!='items':raise ValueError('Unexpected items XML root')
    else:json.loads(raw)


def remote_program():
    old="allowed={'tio/wallets.py','tio/battle_rewards.py','tio/reward_policy.py','tio/ranks.py','tio/level_progression.py','config/level_progression.json','server/team_arena.py','tools/loopback_exchange.py'}"
    if guarded.DEPLOY.count(old)!=1:raise RuntimeError('Reviewed deployment program changed')
    code=guarded.DEPLOY.replace(old,'allowed=set('+repr(sorted(ALLOWED))+')')
    old_syntax="    if name.endswith('.py'):compile(raw,name,'exec')\n    else:json.loads(raw)"
    if code.count(old_syntax)!=1:raise RuntimeError('Reviewed candidate validator changed')
    new_syntax="""    if name.endswith('.py'):compile(raw,name,'exec')
    elif name=='evidence/items_diagnostic.xml':
        if len(raw)>2*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise RuntimeError('Unexpected zones XML declarations or size')
        import xml.etree.ElementTree as ET
        if ET.fromstring(raw).tag!='items':raise RuntimeError('Unexpected items XML root')
    else:json.loads(raw)"""
    code=code.replace(old_syntax,new_syntax)
    code=code.replace('tio-stage4-economy','tio-stage7').replace('tio-before-stage4-economy-',
        'tio-before-stage7-').replace('.stage4-','.stage7-')
    compile(code,'stage7_deployment','exec')
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
