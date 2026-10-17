"""Read-only final health check for the hosted legacy-client release."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from tools import deploy_stage4_economy as remote_tools

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011'
REMOTE = r'''
from contextlib import closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess
def run(*args):
 return subprocess.run(args,text=True,capture_output=True,check=True,timeout=30).stdout.strip()
service=dict(line.split('=',1) for line in run('systemctl','show','tio-server','-p','ActiveState','-p','MainPID','-p','NRestarts','-p','ExecMainStatus').splitlines())
assert service['ActiveState']=='active' and service['ExecMainStatus']=='0'
code={name:hashlib.sha256((Path('/opt/tio-emulator')/name).read_bytes()).hexdigest() for name in ('server/team_arena.py','server/wager_arena.py')}
assert code=={'server/team_arena.py':'9f2303a8331c8bae0faa46b558a3884070ce2df0c658913a8f1b44ccf38ed773','server/wager_arena.py':'4cf769a3c6aa6784a066b4bf9bcc48966157b0fb002e884bccfb271053fd8d01'}
listeners=run('ss','-Hltn','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
assert all(':'+str(port) in listeners for port in (28512,28513,29512,29513))
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True,timeout=15)) as db:
 db.execute('BEGIN')
 integrity=db.execute('PRAGMA integrity_check').fetchall()
 assert integrity==[('ok',)]
 health={'integrity':'ok','accounts':db.execute('SELECT count(*) FROM accounts').fetchone()[0],'tables':db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],'checkpoints':db.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],'settlement_jobs':db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0]}
 assert health['accounts']>=208 and health['checkpoints']==health['settlement_jobs']==0
raw=Path('/var/www/tio-client/updates/manifest.json').read_bytes()
manifest=json.loads(raw)
assert manifest['version']=='2026.10.11.1' and hashlib.sha256(raw).hexdigest()=='3ca0411e03b00ba814c95b197ace1176377bd29635b0b805b3bd67ab3806099b'
print(json.dumps({'passed':True,'remote_mutations':0,'service':service,'listeners':listeners,'code_sha256':code,'database':health,'client_version':manifest['version'],'manifest_sha256':hashlib.sha256(raw).hexdigest()}))
'''


def main():
    target = FOLDER / 'release-health.json'
    if target.exists():
        raise ValueError('Preserve existing health evidence')
    report = remote_tools.remote(REMOTE, {})
    local_client = ROOT / 'reports/new-player/client-a/silver.dll'
    digest = hashlib.sha256(local_client.read_bytes()).hexdigest()
    assert digest == '4897eb6d6af6beb587fc9b303dc6911519d90b3414ae8cca8fd1ffb698c1f082'
    report['verified_utc'] = datetime.now(timezone.utc).isoformat()
    report['local_launcher'] = {
        'version': '0.1.6', 'window_title': 'Total Influence · Лаунчер 0.1.6',
        'client_version_observed': '2026.10.11.1',
        'ready_to_play_observed': True,
        'installed_silver_sha256': digest,
        'game_client_graphical_validation': False,
    }
    with target.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
