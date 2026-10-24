"""Read-only source snapshot and aggregate health for encounter movement fixes."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/encounter-movement-20261017'
REPORT = ROOT / 'reports/encounter-movement-20261017'
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@185.184.42.88']


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(SSH + ['tar --exclude=__pycache__ --exclude=\'*.pyc\' -czf - -C /opt/tio-emulator server tio tools config evidence'], capture_output=True, check=True)
    (WORK/'runtime-before.tar.gz').write_bytes(result.stdout)
    baseline = WORK/'baseline'
    baseline.mkdir(exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:gz') as archive:
        archive.extractall(baseline, filter='data')
    hashes = {p.relative_to(baseline).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in baseline.rglob('*') if p.is_file()}
    (REPORT/'baseline-sha256.json').write_text(json.dumps(hashes, indent=2))
    script = '''from contextlib import closing
import collections,json,sqlite3,subprocess
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 data=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],retained={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')})
data['service']=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()
data['connections']=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
log=subprocess.check_output(['journalctl','-u','tio-server','--since','24 hours ago','--no-pager','-o','cat'],text=True)
data['movement_rejections']={text:log.count(text) for text in ('Destination is blocked','Diagonal path cuts','Path contains a nonadjacent','Insufficient action points','battle_move_rejected','Traceback (most recent call last)')}
data['recent_move_errors']=[line.split('reason=',1)[-1][-250:] for line in log.splitlines() if 'reason=' in line and any(s in line for s in ('move','blocked','Path'))][-30:]
print(json.dumps(data))
'''
    state = subprocess.run(SSH+['python3 -'], input=script, capture_output=True, text=True, check=True)
    data=json.loads(state.stdout)
    data['runtime_files']=len(hashes)
    data['local_differences']=[n for n,h in hashes.items() if (ROOT/n).is_file() and hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    (REPORT/'inspection.json').write_text(json.dumps(data, indent=2))
    print(json.dumps(data))


if __name__ == '__main__':
    main()
