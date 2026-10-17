"""Read-only hosted economy baseline; reports aggregate data, never credentials."""
from pathlib import Path
import hashlib
import json
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/stage4-economy'
FILES = (
    'tio/wallets.py', 'tio/battle_rewards.py', 'tio/reward_policy.py',
    'tio/level_progression.py', 'tio/ranks.py', 'tio/combat.py',
    'tio/battle_settlement.py', 'server/team_arena.py', 'server/ranked_arena.py',
    'config/level_progression.json', 'config/ranks.json', 'config/recovery.json',
    'config/ability_learning.json', 'config/world_encounters.json',
    'config/original_shop_prices.json', 'config/hiring.json',
)
REMOTE = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys
p=json.load(sys.stdin);root=Path('/opt/tio-emulator')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def run(*args):return subprocess.run(args,text=True,capture_output=True,check=True,timeout=30).stdout.strip()
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
    db.execute('BEGIN')
    integrity=db.execute('PRAGMA integrity_check').fetchall()
    if integrity != [('ok',)]:raise RuntimeError('Hosted database integrity failed')
    tables={}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        rows=sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'))
        tables[name]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
    wallets=db.execute('SELECT count(*),min(credits),max(credits),sum(credits),min(gold),max(gold),sum(gold) FROM wallets').fetchone()
    rewards=[]
    if 'battle_rewards' in tables:
        columns={r[1] for r in db.execute('PRAGMA table_info(battle_rewards)')}
        rewards=[dict(result=r[0],count=r[1],credits=r[2]) for r in db.execute('SELECT result,count(*),sum(credits) FROM battle_rewards GROUP BY result')]
    work={name:tables[name]['rows'] for name in ('battle_checkpoints','battle_settlement_jobs') if name in tables}
connections=run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
out=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),integrity='ok',tables=tables,
    wallets=dict(zip(('count','min_credits','max_credits','sum_credits','min_gold','max_gold','sum_gold'),wallets)),
    reward_aggregates=rewards,unfinished_battle_rows=work,
    established_game_connections=len(connections.splitlines()) if connections else 0,
    services={name:run('systemctl','show',name,'-p','ActiveState','-p','MainPID','-p','NRestarts','-p','ExecMainStatus') for name in ('tio-server','tio-game-api','tio-portal')},
    guards={name:sha(Path(name)) for name in ('/etc/tio-server/server.toml','/var/www/tio-client/updates/manifest.json','/var/www/tio-client/downloads/TIO-Launcher.exe')},
    files={name:dict(sha256=sha(root/name),source=(root/name).read_text() if (root/name).is_file() else None) for name in p['files']})
print(json.dumps(out))
'''


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    target = REPORT / 'remote-baseline.json'
    if target.exists():
        raise RuntimeError('Baseline already captured')
    command = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=15', 'root@185.184.42.88', 'python3 -c '+shlex.quote(REMOTE)]
    completed = subprocess.run(command, input=json.dumps({'files':FILES}),
                               text=True, encoding='utf-8', capture_output=True, timeout=90)
    if completed.returncode:
        raise RuntimeError('Read-only remote inspection failed; no remote changes made')
    actual = json.loads(completed.stdout)
    for name, entry in actual['files'].items():
        if entry['source'] is not None:
            saved = REPORT / 'remote-before' / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(entry.pop('source'), encoding='utf-8', newline='')
        else:
            entry.pop('source')
        entry['local_sha256'] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest() if (ROOT/name).is_file() else None
    target.write_text(json.dumps(actual, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key:actual[key] for key in ('timestamp_utc','integrity','wallets','reward_aggregates','unfinished_battle_rows','established_game_connections','services')}))


if __name__ == '__main__':
    main()
