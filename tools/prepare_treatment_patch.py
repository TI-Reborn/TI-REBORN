"""Package treatment and the already-reviewed pending turn-order fix."""
from pathlib import Path
import hashlib,json,tarfile

ROOT=Path(__file__).resolve().parents[1];report=ROOT/'reports/post-battle-treatment'
files={'server/team_arena.py':ROOT/'reports/turn-order/remote-team_arena.py',
       'server/battle_reconnect.py':ROOT/'reports/turn-order/remote-battle_reconnect.py',
       'tio/protocol/battle_turn.py':ROOT/'reports/turn-order/remote-battle_turn.py',
       'tio/protocol/player_auction.py':report/'remote-player_auction.py'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest={name:dict(before=sha(old),after=sha(ROOT/name)) for name,old in files.items()}
(report/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
for filename,source in (('deploy_remote.py',ROOT/'tools/deploy_battle_turn_remote.py'),
                         ('verify_remote.py',ROOT/'reports/wall-disconnect/verify_remote.py')):
    text=source.read_text(encoding='utf-8').replace('battle-turn','post-battle-treatment').replace('wall-heartbeat','post-battle-treatment')
    (report/filename).write_text(text,encoding='utf-8')
with tarfile.open(report/'patch.tar.gz','w:gz') as tar:
    for name in files:tar.add(ROOT/name,arcname=name)
    tar.add(report/'manifest.json',arcname='manifest.json')
with tarfile.open(report/'tests.tar.gz','w:gz') as tar:
    for path in (ROOT/'tests').glob('*.py'):tar.add(path,arcname='tests/'+path.name)
print(json.dumps(manifest,indent=2))
