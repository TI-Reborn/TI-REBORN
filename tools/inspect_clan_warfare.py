"""Read-only hosted clan-warfare baseline; no account or credential payloads."""
import hashlib
import json
from pathlib import Path

from tools.deploy_stage4_economy import remote
from tools.inspect_shared_mines import REMOTE

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/clan-warfare'
SOURCES=(
    'tio/clans.py','tio/mine_claims.py','tio/battle_rewards.py',
    'tio/warehouse_queries.py','tio/locations.py','tio/cities.py',
    'tio/protocol/clans.py','tio/protocol/presence.py','tio/protocol/public_profile.py',
    'server/clan_service.py','server/team_arena.py','server/battle_journal.py',
    'server/battle_reconnect.py','server/mine_arena.py','server/multi.py',
    'tio/team_scene.py','tio/battle_snapshot.py','tools/loopback_exchange.py',
)


def main():
    target=FOLDER/'remote-baseline.json'
    if target.exists():raise RuntimeError('Preserve existing hosted inspection')
    actual=remote(REMOTE,{'files':SOURCES})
    for name,entry in actual['files'].items():
        source=entry.pop('source')
        if source is not None:
            saved=FOLDER/'remote-before'/name
            saved.parent.mkdir(parents=True,exist_ok=True)
            with saved.open('x',encoding='utf-8',newline='') as output:output.write(source)
        local=ROOT/name
        entry['local_sha256']=hashlib.sha256(local.read_bytes()).hexdigest() if local.is_file() else None
    FOLDER.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as output:output.write(json.dumps(actual,indent=2)+'\n')
    print(json.dumps({k:actual[k] for k in ('timestamp_utc','integrity',
        'unfinished_battle_rows','established_game_connections','services')}))


if __name__=='__main__':main()
