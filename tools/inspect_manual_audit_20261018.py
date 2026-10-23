"""Read-only evidence capture for the original manual comparison."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/manual-audit-20261018'
REPORT = ROOT / 'reports/manual-audit-20261018'
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@185.184.42.88']


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    target = WORK/'hosted'
    target.mkdir(exist_ok=False)
    result = subprocess.run(SSH + ["tar --exclude=__pycache__ --exclude='*.pyc' -czf - -C /opt/tio-emulator server tio tools config evidence"], capture_output=True, check=True, timeout=180)
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:gz') as archive:
        archive.extractall(target, filter='data')
    hashes = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
    (REPORT/'hosted-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    source = '''import json,sqlite3,subprocess,datetime,tomllib
from pathlib import Path
from contextlib import closing
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
 data=dict(captured_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),integrity=db.execute('PRAGMA integrity_check').fetchone()[0])
 data['tables']={t:db.execute('SELECT count(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
 data['schema']={t:[list(r) for r in db.execute('PRAGMA table_info("'+t.replace('"','""')+'")')] for t in tables}
data['service']=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts','-p','ExecMainStartTimestamp'],text=True)
data['manifest_version']=json.loads(Path('/var/www/tio-client/updates/manifest.json').read_text())['version']
cfg=tomllib.loads(Path('/etc/tio-server/server.toml').read_text())
def safe(o):
 if isinstance(o,dict): return {k:('[redacted]' if any(s in k.lower() for s in ('password','secret','token','key','credential')) else safe(v)) for k,v in o.items()}
 return o
data['configuration']=safe(cfg)
print(json.dumps(data))
'''
    result = subprocess.run(SSH + ['cd /opt/tio-emulator && .venv/bin/python -'], input=source, capture_output=True, encoding='utf-8', timeout=180, check=True)
    state = json.loads(result.stdout)
    (REPORT/'hosted-inspection.json').write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    old = ROOT/'work/crystal-quotes-20261018/candidate'
    differences = [n for n,h in hashes.items() if not (old/n).is_file() or hashlib.sha256((old/n).read_bytes()).hexdigest()!=h]
    print(json.dumps(dict(captured_utc=state['captured_utc'],integrity=state['integrity'],service=state['service'],manifest_version=state['manifest_version'],files=len(hashes),differences_from_last_candidate=differences,table_counts=state['tables']), ensure_ascii=False))


if __name__ == '__main__':
    main()
