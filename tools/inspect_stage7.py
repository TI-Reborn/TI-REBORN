"""Read-only hosted Stage7 baseline; public sources and aggregate DB counts."""
import hashlib
import json
from pathlib import Path
from tools.deploy_stage4_economy import remote
from tools.inspect_shared_mines import REMOTE

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/stage7'
SOURCES=('tio/combat.py','tio/weapon_effects.py','tio/team_scene.py','tio/battle_state.py',
    'tio/battle_snapshot.py','tio/arena_service.py','tio/protocol/known_mines.py',
    'tio/characters.py','tio/owned_pets.py','tio/onboarding.py','tio/ranked.py',
    'tio/battle_rewards.py','tio/warehouse_queries.py','tio/protocol/player_auction.py',
    'server/team_arena.py','server/ranked_arena.py','server/battle_reconnect.py',
    'server/battle_journal.py','server/battle_failures.py','server/presence.py',
    'server/public_profile.py','server/multi.py','tools/loopback_exchange.py',
    'config/item_catalog.json')

def main():
    target=FOLDER/'remote-baseline.json'
    if target.exists():raise RuntimeError('Preserve previous hosted evidence')
    data=remote(REMOTE,{'files':SOURCES})
    FOLDER.mkdir(parents=True,exist_ok=True)
    for name,entry in data['files'].items():
        source=entry.pop('source')
        if source is not None:
            path=FOLDER/'remote-before'/name;path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8',newline='') as output:output.write(source)
        local=ROOT/name
        entry['local_sha256']=hashlib.sha256(local.read_bytes()).hexdigest() if local.is_file() else None
    with target.open('x',encoding='utf-8') as output:json.dump(data,output,indent=2)
    print(json.dumps({k:data[k] for k in ('timestamp_utc','integrity','unfinished_battle_rows','established_game_connections','services')}))

if __name__=='__main__':main()
