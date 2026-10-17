"""Capture the live code and freeze a scoped achievement delivery fix."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import tarfile

from tools.deploy_stage4_economy import SSH, INSPECT, remote

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-completion/achievement-city-disconnect-20261014'


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    runtime = FOLDER / 'runtime'
    if runtime.exists():
        raise RuntimeError('Preserve the prior captured runtime')
    captured = subprocess.run(SSH + [
        "tar --exclude='__pycache__' -czf - -C /opt/tio-emulator server tio tools config evidence"
    ], capture_output=True, check=True, timeout=60)
    with tarfile.open(fileobj=io.BytesIO(captured.stdout), mode='r:gz') as archive:
        archive.extractall(runtime, filter='data')
    name = 'tio/achievements.py'
    baseline = remote(INSPECT, {'files': [name]})
    guard_code = """from pathlib import Path
import hashlib,json
paths=['/etc/tio-server/server.toml','/etc/systemd/system/tio-server.service']
print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}))
"""
    guards = remote(guard_code, {})
    source = runtime / name
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != baseline[name]['sha256']:
        raise RuntimeError('Hosted source changed during capture')
    (FOLDER / 'achievements-before.py').write_bytes(raw)
    value = raw.decode('utf-8')
    old = "            db.execute('BEGIN IMMEDIATE');snapshots(db,account)\n            awards="
    new = """            db.execute('BEGIN IMMEDIATE')
            # Automatic delivery also runs after reconnect and map arrivals.
            # Non-city locations have no warehouse; keep every receipt pending
            # until the owner reaches a city, on this same authoritative unit.
            if completion.current_town(db, account, required=False) is None:
                return ()
            snapshots(db,account)
            awards="""
    if value.count(old) != 1:
        raise RuntimeError('Achievement delivery boundary changed')
    candidate = value.replace(old, new).encode('utf-8')
    compile(candidate, name, 'exec')
    source.write_bytes(candidate)
    (FOLDER / 'remote-baseline.json').write_text(json.dumps(
        {'files': baseline, 'guards': guards}, indent=2), encoding='utf-8')
    (FOLDER / 'candidate-overrides.json').write_text(json.dumps(
        {name: 'runtime/' + name}, indent=2), encoding='utf-8')
    print(json.dumps({'folder': str(FOLDER), 'before': baseline[name]['sha256'],
                      'after': hashlib.sha256(candidate).hexdigest()}))


if __name__ == '__main__':
    main()
