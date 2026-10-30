"""Scoped remote deployment; never uploads/restores player data. Run on VPS."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import time

ROOT=Path('/opt/tio-emulator')
DATABASE=Path('/var/lib/tio-server/reservation.sqlite3')
CONFIG=Path('/etc/tio-server/server.toml')
SCOPES={
    'services':frozenset(('server/game_operations.py','server/service_operations.py',
        'server/city_services.py','server/services_runtime.py','server/services_v2.py')),
    'bank':frozenset(('server/bank_operations.py','server/bank_gameplay.py','server/city_operations.py')),
    'trade':frozenset(('server/market_operations.py','server/player_trade.py','server/player_auction.py',
        'server/private_market.py','tio/player_auction.py','tools/loopback_exchange.py')),
}
SCOPES['bank-trade']=SCOPES['bank']|SCOPES['trade']
SCOPES['battle-screen-fixes']=frozenset(('server/team_arena.py','tio/visibility.py'))
SCOPES['bot-finishing']=frozenset(('tio/tactical_bot.py','tio/bot_finishing.py'))
SCOPES['bot-credit-rewards']=frozenset(('tio/reward_policy.py','server/team_arena.py'))
SCOPES['encounter-movement']=frozenset(('tio/battle_state.py',))
SCOPES['training-base']=frozenset(('server/training_arena.py','server/contracts_service.py'))
SCOPES['training-strings']=frozenset(('tio/protocol/assault.py',))
SCOPES['training-counter']=frozenset(('server/training_arena.py',))
SCOPES['gameplay-audit'] = frozenset((
    'server/character_operations.py',
    'server/mine_arena.py',
    'server/team_arena.py',
    'server/warehouse_capacity.py',
    'tio/armor.py',
    'tio/character_deletion.py',
    'tio/character_identity.py',
    'tio/character_lifecycle.py',
    'tio/characters.py',
    'tio/combat.py',
    'tio/enhancement.py',
    'tio/equipment.py',
    'tio/hiring.py',
    'tio/mining.py',
    'tio/protocol/character_delete.py',
    'tio/rating_visibility.py',
    'tio/roster_rules.py',
    'tio/services_completion.py',
    'tio/tactical_bot.py',
    'tio/world_completion.py',
    'tools/loopback_exchange.py',
))
SCOPES['warehouse-counter-refresh']=frozenset(('server/economy_runtime.py',))
SCOPES['shooting-range-turns'] = frozenset((
    'server/team_arena.py', 'tio/arena_service.py',
    'tio/battle_snapshot.py', 'tio/turn_repeats.py', 'tools/loopback_exchange.py',
))
SCOPES['warehouse-latency'] = frozenset((
    'server/economy_runtime.py', 'server/warehouse_capacity.py',
    'server/multi.py', 'tools/loopback_exchange.py', 'tio/weight.py',
    'tio/battle_recovery.py',
))
SCOPES['mine-warehouses']=frozenset(('tio/warehouse_completion.py',))
SCOPES['shared-warehouse']=frozenset(('tio/warehouse_completion.py','tio/warehouse_resources.py'))
SCOPES['map-speed']=frozenset(('tio/locations.py',))
SCOPES['premium-effects']=frozenset(('tio/premium.py','tio/battle_rewards.py'))
SCOPES['warehouse-counters']=frozenset(('tio/clans.py','tio/protocol/asset_count.py','tio/warehouse_resources.py','tio/warehouse_service.py','server/economy_runtime.py'))
SCOPES['ranked-cancel']=frozenset(('server/ranked_arena.py','server/team_arena.py'))
SCOPES['ranked-party-refactor'] = frozenset((
    'server/ranked_party.py', 'server/ranked_party_access.py',
    'server/ranked_arena.py', 'server/team_arena.py', 'tio/ranked_party.py',
    'tio/protocol/ranked_party.py', 'tio/protocol/ranked.py', 'tio/ranked_loadout.py',
    'tio/matchmaking.py', 'tools/survival_scene.py',
    'tio/world_completion.py',
))
SCOPES['crystal-quotes']=frozenset(('tio/mining_service.py',))
SCOPES['area-fire']=frozenset(('tio/combat.py','tio/combat_rolls.py'))
SCOPES['clan-icons']=frozenset(('server/clan_service.py','tio/protocol/clan_crests.py','tio/clan_benefits.py'))
SCOPES['clan-crest-projections']=frozenset(('server/presence.py','server/training_arena.py'))
SCOPES['performance']=frozenset(('server/team_arena.py','server/training_arena.py',
    'server/economy_runtime.py','tio/performance.py','tio/owned_pets.py',
    'tio/battle_snapshot.py','tio/db_transaction.py'))
SCOPES['performance-lists']=frozenset(('server/team_arena.py','server/wager_arena.py'))
SCOPES['performance-fastpaths']=SCOPES['performance-lists']|frozenset(('tio/battle_snapshot.py',))
SCOPES['performance-read-projections']=frozenset(('tio/owned_pets.py','tio/passive_stats.py',
    'tio/travel_party.py','tio/party_travel.py','tio/locations.py','tio/character_identity.py'))
SCOPES['performance-through-reads']=SCOPES['performance-fastpaths']|SCOPES['performance-read-projections']
SCOPES['performance-idle-writes']=frozenset(('tio/pve_contracts.py','tio/travel_party.py','tio/sc_auction.py'))
SCOPES['performance-hub-contention']=frozenset(('tio/performance.py','tio/db_transaction.py',
    'tio/territories.py','server/assault_arena.py','server/training_arena.py','server/team_arena.py'))
SCOPES['tactical-bots']=frozenset(('tio/tactical_bot.py','tio/training_bot.py','tio/matchmaking.py',
    'tio/team_scene.py','tio/visibility.py','server/team_arena.py','server/battle_events.py','config/survival.json'))
KEEP_TABLES=('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')
SCOPES['repair-from-warehouse']=frozenset(('tio/repair.py','tools/loopback_exchange.py'))
SCOPES['medical-optics'] = frozenset((
    'config/city_catalogs.json', 'config/credit_economy.json',
    'config/sc_catalog.json', 'config/medical_items.json',
    'tio/medical_items.py', 'tio/combat.py', 'tio/battle_item_effects.py',
))
SCOPES['securities-perks'] = frozenset((
    'config/ability_learning.json', 'config/bank_economy.json',
    'config/restored_abilities.json', 'evidence/skills_diagnostic.xml',
    'server/bank_gameplay.py', 'server/city_operations.py',
    'server/securities_service.py', 'tio/ability_learning.py',
    'tio/ability_prices.py', 'tio/bank_economy.py', 'tio/combat.py',
    'tio/miner_abilities.py', 'tio/passive_stats.py',
    'tio/protocol/securities.py', 'tio/restored_abilities.py',
    'tools/battle_roster_fixture.py', 'tools/build_skills_fixture.py',
    'tools/loopback_exchange.py', 'tools/survival_scene.py',
))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def run(*args,cwd=ROOT):
    return subprocess.run(args,cwd=cwd,check=True,text=True,capture_output=True,timeout=45)


def snapshot(db):
    result={}
    for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        quoted='"'+table.replace('"','""')+'"'
        rows=sorted(sha256(repr(tuple(r)).encode('utf-8')).hexdigest() for r in db.execute('SELECT * FROM '+quoted))
        result[table]=dict(rows=len(rows),sha256=sha256(''.join(rows).encode()).hexdigest())
    return result


def idle(maintenance_restart=False, *, check_travel=False):
    sockets=run('ss','-Htn','state','established',
        '( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )').stdout.strip()
    if sockets and not maintenance_restart:raise RuntimeError('Players are connected; deployment deferred')
    with closing(sqlite3.connect(DATABASE.as_uri()+'?mode=ro',uri=True)) as db:
        for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):
            if db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                raise RuntimeError('Retained gameplay exists; deployment deferred: '+table)
        if check_travel:
            idle_routes(db)


def idle_routes(db):
    # Old-speed timestamps must not coexist with a faster advertised 1A speed.
    # Completed offline routes may remain saved and require no alteration.
    for table in ('map_journeys','travel_party_journeys'):
        if db.execute('SELECT 1 FROM '+table+' WHERE arrives>? LIMIT 1',(time.time(),)).fetchone():
            raise RuntimeError('Map travel is in progress; speed deployment deferred')


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--baseline',required=True,type=Path)
    parser.add_argument('--backup',required=True,type=Path)
    parser.add_argument('--scope',choices=tuple(SCOPES),default='services')
    parser.add_argument('--prepare-only',action='store_true',help='Validate and back up without replacing code or restarting')
    parser.add_argument('--maintenance-restart',action='store_true',
        help='Explicitly authorized restart with connected players; still refuses retained battles and settlements')
    args=parser.parse_args()
    files=SCOPES[args.scope]
    if args.backup.parent!=Path('/root') or not args.backup.name.startswith('tio-before-game-operations-'):
        raise RuntimeError('Unexpected protected backup path')
    if digest(args.archive)!=args.sha256:raise RuntimeError('Candidate archive changed')
    baseline=json.loads(args.baseline.read_text())
    if any(not p.startswith(('server/','tio/','tools/','config/','evidence/'))
           or '..' in Path(p).parts or '\\' in p for p in baseline):
        raise RuntimeError('Unsafe baseline path')
    for path,expected in baseline.items():
        if digest(ROOT/path)!=expected:raise RuntimeError('Remote runtime changed: '+path)
    if run('systemctl','is-active','tio-server').stdout.strip()!='active':
        raise RuntimeError('Game service is not active')
    if not args.prepare_only:idle(args.maintenance_restart,check_travel=args.scope=='map-speed')
    stage=Path('/opt')/('tio-operation-validation-'+args.backup.name.removeprefix('tio-before-game-operations-'))
    stage.mkdir(mode=0o755)
    for name in ('server','tio','tools','config','evidence'):
        shutil.copytree(ROOT/name,stage/name,ignore=shutil.ignore_patterns('__pycache__'))
    with tarfile.open(args.archive) as archive:
        members=archive.getmembers()
        if {m.name for m in members}!=files|{'manifest.json'} or len(members)!=len(files)+1 or any(not m.isfile() for m in members):
            raise RuntimeError('Unexpected candidate member')
        manifest=json.load(archive.extractfile('manifest.json'))
        if set(manifest)!=files:raise RuntimeError('Unexpected deployment scope')
        for path,record in manifest.items():
            if digest(ROOT/path)!=record['before']:raise RuntimeError('Code changed: '+path)
            raw=archive.extractfile(path).read()
            if sha256(raw).hexdigest()!=record['after']:raise RuntimeError('Candidate changed: '+path)
            target=stage/path;target.write_bytes(raw);target.chmod(0o644)
    checked=run(str(ROOT/'.venv/bin/python'),'-m','server','--config',str(CONFIG),'--check',cwd=stage)
    # Import every changed adapter, including the lazily loaded city modules.
    run(str(ROOT/'.venv/bin/python'),'-c',
        'import '+','.join(path.removesuffix('.py').replace('/','.') for path in sorted(files) if path.endswith('.py')),cwd=stage)
    args.backup.mkdir(mode=0o700)
    config_hash=digest(CONFIG)
    with tarfile.open(args.backup/'previous-code-config.tar.gz','w:gz') as archive:
        for name in ('server','tio','tools','config','evidence'):
            archive.add(ROOT/name,arcname='code/'+name,
                filter=lambda item:None if '__pycache__' in Path(item.name).parts else item)
        archive.add('/etc/tio-server',arcname='etc/tio-server')
    (args.backup/'tio-server.service.txt').write_text(run('systemctl','cat','tio-server').stdout)
    (args.backup/'patch-manifest.json').write_text(json.dumps(manifest,indent=2))
    (args.backup/'runtime-before-sha256.json').write_text(json.dumps(baseline,indent=2))
    with (closing(sqlite3.connect(DATABASE.as_uri()+'?mode=ro',uri=True)) as source,
          closing(sqlite3.connect(args.backup/'before.sqlite3')) as target):
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise RuntimeError('Backup integrity failed')
    backup_receipt=dict(database_sha256=digest(args.backup/'before.sqlite3'),
        code_config_sha256=digest(args.backup/'previous-code-config.tar.gz'),config_sha256=config_hash,
        staged_preflight=(checked.stdout+checked.stderr).strip(),database_restoration_allowed=False)
    (args.backup/'backup-manifest.json').write_text(json.dumps(backup_receipt,indent=2))
    if args.prepare_only:
        report=dict(passed=True,scope=args.scope,preparation_only=True,installed=False,
                    staged_preflight=True,backup=str(args.backup),files_verified=len(manifest),
                    service=run('systemctl','is-active','tio-server').stdout.strip(),
                    local_player_data_uploaded=False,database_restored=False)
        (args.backup/'preparation.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report));return
    idle(args.maintenance_restart,check_travel=args.scope=='map-speed')
    for path,record in manifest.items():
        if digest(ROOT/path)!=record['before']:raise RuntimeError('Code changed before cutover: '+path)
    if digest(CONFIG)!=config_hash:raise RuntimeError('Configuration changed')
    stopped=False;applied=[]
    try:
        run('systemctl','stop','tio-server');stopped=True
        with (closing(sqlite3.connect(DATABASE.as_uri()+'?mode=ro',uri=True)) as source,
              closing(sqlite3.connect(args.backup/'at-cutover.sqlite3')) as target):
            for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):
                if source.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                    raise RuntimeError('Gameplay appeared before shutdown; code replacement cancelled')
            if args.scope=='map-speed':idle_routes(source)
            source.backup(target);before=snapshot(source)
            if target.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise RuntimeError('Cutover backup integrity failed')
        backup_receipt['at_cutover_sha256']=digest(args.backup/'at-cutover.sqlite3')
        (args.backup/'backup-manifest.json').write_text(json.dumps(backup_receipt,indent=2))
        for path,record in manifest.items():
            target=ROOT/path;saved=args.backup/'files'/path
            if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            temporary=target.with_name(target.name+'.operations-new')
            shutil.copyfile(stage/path,temporary);temporary.chmod(0o644);temporary.replace(target);applied.append(path)
            if digest(target)!=record['after']:raise RuntimeError('Installed code differs')
        run('runuser','-u','tio','--',str(ROOT/'.venv/bin/python'),'-m','server','--config',str(CONFIG),'--check')
        with closing(sqlite3.connect(DATABASE.as_uri()+'?mode=ro',uri=True)) as db:
            if before!=snapshot(db):raise RuntimeError('Player data changed during code replacement')
        run('systemctl','start','tio-server');stopped=False
        time.sleep(2)
        status=run('systemctl','is-active','tio-server').stdout.strip()
        if status!='active':raise RuntimeError('Service did not restart')
        with closing(sqlite3.connect(DATABASE.as_uri()+'?mode=ro',uri=True)) as db:
            after=snapshot(db)
            for table in KEEP_TABLES:
                if table in before and before[table]!=after.get(table):raise RuntimeError('Protected player table changed: '+table)
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok' or digest(CONFIG)!=config_hash:raise RuntimeError('Postcheck failed')
        report=dict(passed=True,scope=args.scope,backup=str(args.backup),service=status,integrity=integrity,
            maintenance_restart=args.maintenance_restart,
            files_verified=len(manifest),database_tables_preserved_before_restart=len(before),
            protected_player_tables_preserved=list(KEEP_TABLES),
            other_table_changes=[t for t in before if before[t]!=after.get(t)],
            accounts=after['accounts']['rows'],local_player_data_uploaded=False,database_restored=False)
        (args.backup/'deployment.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report))
    except BaseException:
        if not stopped:run('systemctl','stop','tio-server')
        for path in applied:
            saved=args.backup/'files'/path;target=ROOT/path
            if saved.is_file():shutil.copy2(saved,target)
            elif manifest[path]['before'] is None:target.unlink(missing_ok=True)
        run('systemctl','start','tio-server')
        (args.backup/'deployment-failed.json').write_text(json.dumps(dict(
            code_rollback=True,database_restored=False,applied=applied),indent=2))
        raise


if __name__=='__main__':main()
