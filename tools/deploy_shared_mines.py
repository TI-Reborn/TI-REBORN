"""Prepare/review guarded shared-mines code deployment; deploy requires explicit operator action.

Reuses the reviewed Stage4 transaction, backup, socket guards, restart checks,
and rollback journal. Uploads public runtime code only; never player data.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import deploy_stage4_economy as guarded
FOLDER = ROOT/'reports/shared-mines'
ALLOWED = {
    'tio/mining.py','tio/mining_service.py','tio/mine_map.py','tio/clans.py',
    'tio/crystal_market.py','tio/protocol/mining.py','tools/mining_scene.py',
    'server/mine_arena.py','server/team_arena.py','server/multi.py',
    'server/battle_journal.py','server/battle_reconnect.py',
    'tools/loopback_exchange.py','tio/battle_snapshot.py','config/mining.json',
    'tio/mine_claims.py','tools/manage_mine_claims.py',
    'tio/battle_rewards.py','tio/arena_service.py','server/battle_events.py',
}
NEW_FILES = {'server/mine_arena.py','tio/mine_claims.py','tools/manage_mine_claims.py'}


def remote_program():
    original = "allowed={'tio/wallets.py','tio/battle_rewards.py','tio/reward_policy.py','tio/ranks.py','tio/level_progression.py','config/level_progression.json','server/team_arena.py','tools/loopback_exchange.py'}"
    if guarded.DEPLOY.count(original)!=1:
        raise RuntimeError('Reviewed deployment implementation changed; review before adapting')
    code = guarded.DEPLOY.replace(original,'allowed=set('+repr(sorted(ALLOWED))+')')
    code = code.replace('tio-stage4-economy','tio-shared-mines').replace('tio-before-stage4-economy-','tio-before-shared-mines-').replace('.stage4-','.shared-mines-')
    compile(code,'shared_mines_deployment','exec')
    return code


def candidate_entries(files, actual):
    if not files or not set(files)<=ALLOWED:
        raise ValueError('Select reviewed shared-mines runtime/config files only')
    entries={}
    for name in sorted(files):
        before=actual[name]['sha256']
        if before is None and name not in NEW_FILES:
            raise RuntimeError('Unexpected missing hosted runtime file: '+name)
        raw=(ROOT/name).read_bytes();after=hashlib.sha256(raw).hexdigest()
        if name.endswith('.py'):compile(raw,name,'exec')
        else:json.loads(raw)
        if before==after:raise RuntimeError('Unchanged selected candidate: '+name)
        entries[name]={'before':before,'after':after}
    return entries


def complete_backup_for(folder):
    """Prefer this revision's fresh backup without changing older references."""
    path=folder/'pre-update-backup.json'
    if not path.exists():path=FOLDER/'pre-update-backup.json'
    return json.loads(path.read_text(encoding='utf-8'))


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
    if args.action=='prepare':
        selected=sorted(set(args.files or ()))
        if not selected or not set(selected)<=ALLOWED:parser.error('Unexpected candidate files')
        if manifest.exists():parser.error('Manifest already exists; preserve previous evidence')
        baseline=json.loads((FOLDER/'remote-baseline.json').read_text(encoding='utf-8'))
        complete=complete_backup_for(folder)
        actual=guarded.remote(guarded.INSPECT,{'files':selected})
        entries=candidate_entries(selected,actual)
        for name,entry in actual.items():
            if entry['source'] is None:continue
            target=folder/'deployment-remote-before'/name
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('x',encoding='utf-8',newline='') as out:out.write(entry['source'])
        data=dict(files=entries,guards=baseline['guards'],complete_backup=complete['backup'],
                  complete_backup_files={n:v['sha256'] for n,v in complete['files'].items()})
        # Also pin the exact reviewed deployment program, not just code uploads.
        data['deployment_program_sha256']=hashlib.sha256(remote_program().encode()).hexdigest()
        with manifest.open('x',encoding='utf-8') as out:out.write(json.dumps(data,indent=2)+'\n')
        print(json.dumps(dict(prepared_files=selected,complete_backup=complete['backup'])))
    else:
        target=folder/'deployment.json'
        if target.exists():parser.error('Deployment already recorded')
        data=json.loads(manifest.read_text(encoding='utf-8'))
        code=remote_program()
        if data.pop('deployment_program_sha256')!=hashlib.sha256(code.encode()).hexdigest():
            raise RuntimeError('Deployment program changed after review')
        if not data['files'] or not set(data['files'])<=ALLOWED:raise ValueError('Unexpected prepared candidate')
        for name,entry in data['files'].items():
            raw=(ROOT/name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['after']:raise RuntimeError('Candidate changed after review')
            entry['content']=base64.b64encode(raw).decode('ascii')
        report=guarded.remote(code,data)
        with target.open('x',encoding='utf-8') as out:out.write(json.dumps(report,indent=2)+'\n')
        if report.get('status')=='attention':raise RuntimeError('Rollback deferred to preserve new live battle state; see report')
        print(json.dumps({n:report[n] for n in ('timestamp_utc','backup','service','accounts_preserved',
              'wallets_preserved','all_existing_tables_unchanged','source_parity')}))


if __name__=='__main__':main()
