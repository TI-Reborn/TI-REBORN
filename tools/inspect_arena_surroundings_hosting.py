"""Capture a fresh read-only hosted baseline; no accounts, uploads or deployment."""
from arena_surroundings_deployment import *
import base64

INSPECTION = r'''
from pathlib import Path
from contextlib import closing
import base64,hashlib,json,sqlite3,subprocess,sys
root=Path('/opt/tio-emulator');live=Path('/var/www/tio-client/updates/manifest.json')
def command(*args):return subprocess.check_output(args,text=True).strip()
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
manifest=live.read_bytes();files=json.load(sys.stdin)
fragment=Path(command('systemctl','show','tio-server','--property=FragmentPath','--value'))
connections=command('ss','-Htn','state','established','( sport = :28512 or sport = :28513 )')
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 database=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
  accounts=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
  checkpoints=db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],
  pending=db.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0])
print(json.dumps(dict(service=command('systemctl','is-active','tio-server'),
 pid=command('systemctl','show','tio-server','--property=MainPID','--value'),
 established_connections=len(connections.splitlines()) if connections else 0,database=database,
 fragment_path=str(fragment),fragment_sha256=digest(fragment),
 configuration_sha256=digest(Path('/etc/tio-server/server.toml')),
 sources={name:dict(sha256=digest(root/name),content_base64=base64.b64encode((root/name).read_bytes()).decode() if (root/name).exists() else None) for name in files},
 manifest_base64=base64.b64encode(manifest).decode(),manifest_sha256=hashlib.sha256(manifest).hexdigest(),
 client_version=json.loads(manifest)['version'])))
'''


def main():
    data = remote_read(INSPECTION, BASELINE_FILES)
    if data['service'] != 'active' or data['database']['integrity'] != 'ok':
        raise RuntimeError('Hosted service/database baseline is unhealthy')
    if data['client_version'] != OLD_VERSION:
        raise RuntimeError('Live client version differs; rebase the release explicitly')
    manifest = base64.b64decode(data.pop('manifest_base64'))
    if sha(manifest) != data['manifest_sha256']:
        raise RuntimeError('Inspection manifest content mismatch')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'previous-client-manifest.json').write_bytes(manifest)
    before = {}
    for name, record in data['sources'].items():
        before[name] = record['sha256']
        content = record.pop('content_base64')
        if content is not None:
            raw = base64.b64decode(content)
            if sha(raw) != record['sha256']:
                raise RuntimeError('Inspection source mismatch: ' + name)
            target = OUT / 'remote-before' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    write_json(OUT / 'before-hashes.json', before)
    write_json(OUT / 'inspection.json', data)
    print(json.dumps(dict(service=data['service'], client_version=data['client_version'],
        established_connections=data['established_connections'], database=data['database'],
        source_files=len(before), read_only=True)))


if __name__ == '__main__':
    main()
