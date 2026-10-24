"""Read-only hosted baseline and aggregate training health; no account writes."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/training-base-20261018'
REPORT = ROOT / 'reports/training-base-20261018'
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@185.184.42.88']


def remote(source):
    result = subprocess.run(SSH + ['cd /opt/tio-emulator && .venv/bin/python -'], input=source, capture_output=True, encoding='utf-8', timeout=240)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    return json.loads(result.stdout)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    baseline = WORK/'baseline'
    baseline.mkdir(exist_ok=False)
    result = subprocess.run(SSH + ["tar --exclude=__pycache__ --exclude='*.pyc' -czf - -C /opt/tio-emulator server tio tools config evidence"], capture_output=True, check=True)
    (WORK/'runtime-before.tar.gz').write_bytes(result.stdout)
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:gz') as archive:
        archive.extractall(baseline, filter='data')
    hashes = {p.relative_to(baseline).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in baseline.rglob('*') if p.is_file()}
    (REPORT/'baseline-sha256.json').write_text(json.dumps(hashes, indent=2))
    state = remote('''import json,sqlite3,subprocess
from contextlib import closing
from pathlib import Path
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 data=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],retained={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')})
data['service']=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
data['connections']=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
data['manifest_version']=json.loads(Path('/var/www/tio-client/updates/manifest.json').read_text())['version']
print(json.dumps(data))
''')
    state['local_differences'] = [n for n,h in hashes.items() if (ROOT/n).is_file() and hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    (REPORT/'inspection.json').write_text(json.dumps(state, indent=2))
    print(json.dumps(state))


if __name__ == '__main__':
    main()
