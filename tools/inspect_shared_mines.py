"""Read-only shared-mines baseline; aggregate SQL only, no account rows/secrets."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    'tio/mining.py', 'tio/mining_service.py', 'tio/mining_ai.py', 'tio/mine_map.py',
    'tio/clans.py', 'tio/crystal_market.py', 'tio/mine_claims.py',
    'tio/protocol/mining.py', 'tio/battle_snapshot.py',
    'tio/battle_checkpoints.py', 'tio/battle_journal.py', 'tio/battle_settlement.py',
    'tio/arena_service.py', 'tio/combat.py', 'server/team_arena.py','server/mine_arena.py',
    'server/battle_journal.py','server/battle_reconnect.py','tools/manage_mine_claims.py',
    'server/multi.py', 'tools/loopback_exchange.py', 'tools/mining_scene.py',
    'config/mining.json', 'config/mine_maps.json', 'config/level_progression.json',
    'config/recovery.json',
)
REMOTE = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys

def database_counts(path):
    # Read no names, credentials, account payloads, or inventory packets.
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
            raise RuntimeError('Database integrity failed')
        tables={name:{'rows':db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]}
                for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
        work={name:tables[name]['rows'] for name in ('battle_checkpoints','battle_settlement_jobs') if name in tables}
        return dict(integrity='ok',tables=tables,unfinished_battle_rows=work)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def run(*args):
    return subprocess.run(args,text=True,capture_output=True,check=True,timeout=30).stdout.strip()

def main():
    p=json.load(sys.stdin);root=Path('/opt/tio-emulator')
    # Source paths come from the caller's fixed public-code whitelist.
    if any(n.startswith('/') or '..' in Path(n).parts or not n.endswith(('.py','.json')) for n in p['files']):
        raise ValueError('Unexpected source path')
    out=database_counts(Path('/var/lib/tio-server/reservation.sqlite3'))
    connections=run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
    out.update(timestamp_utc=datetime.now(timezone.utc).isoformat(),
        established_game_connections=len(connections.splitlines()) if connections else 0,
        services={n:run('systemctl','show',n,'-p','ActiveState','-p','MainPID','-p','NRestarts','-p','ExecMainStatus')
                  for n in ('tio-server','tio-game-api','tio-portal')},
        guards={n:sha(Path(n)) for n in ('/etc/tio-server/server.toml',
            '/etc/systemd/system/tio-server.service','/var/www/tio-client/updates/manifest.json',
            '/var/www/tio-client/downloads/TIO-Launcher.exe')},
        files={n:dict(sha256=sha(root/n),source=(root/n).read_text() if (root/n).is_file() else None) for n in p['files']})
    print(json.dumps(out))

if __name__=='__main__':main()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'reports/shared-mines/remote-baseline.json')
    args = parser.parse_args()
    target = args.output.resolve()
    folder = ROOT/'reports/shared-mines'
    if target.parent != folder or target.exists() or target.is_symlink():
        raise ValueError('Use a fresh report directly under reports/shared-mines')
    command = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=15', 'root@185.184.42.88', 'python3 -c '+shlex.quote(REMOTE)]
    result = subprocess.run(command, input=json.dumps({'files':SOURCES}), text=True,
                            encoding='utf-8', capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Read-only remote inspection failed; no remote changes made')
    actual = json.loads(result.stdout)
    source_folder = folder/(target.stem+'-sources')
    if source_folder.exists():
        raise ValueError('Previous source evidence exists; choose a new report filename')
    for name, entry in actual['files'].items():
        source = entry.pop('source')
        if source is not None:
            saved = source_folder/name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(source, encoding='utf-8', newline='')
        entry['local_sha256'] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest() if (ROOT/name).is_file() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as out:
        out.write(json.dumps(actual, indent=2)+'\n')
    print(json.dumps({key:actual[key] for key in ('timestamp_utc','integrity',
        'unfinished_battle_rows','established_game_connections','services')}))


if __name__ == '__main__':main()
