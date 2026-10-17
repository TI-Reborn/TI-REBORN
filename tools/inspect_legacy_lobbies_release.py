"""Read the actual hosted native release and bounded server sources."""
from pathlib import Path
import hashlib
import json
import ssl
import urllib.request

from tools import deploy_stage4_economy as remote_tools

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011'

INSPECT = r'''
from pathlib import Path
import hashlib,json,subprocess
root=Path('/opt/tio-emulator')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
files={}
for folder in ('server','tio'):
 for p in (root/folder).rglob('*.py'):
  files[p.relative_to(root).as_posix()]={'sha256':sha(p),'source':p.read_text()}
guards={str(p):sha(p) for p in (Path('/etc/tio-server/server.toml'),Path('/etc/systemd/system/tio-server.service'),Path('/var/www/tio-client/updates/manifest.json'),Path('/var/www/tio-client/downloads/TIO-Launcher.exe'),Path('/var/www/tio-client/downloads/launcher-manifest.json'))}
services={n:subprocess.run(['systemctl','show',n,'-p','MainPID','-p','ActiveState','-p','NRestarts','-p','ExecMainStatus'],text=True,capture_output=True,check=True).stdout.strip() for n in ('tio-server','tio-registration','nginx','tio-game-api','tio-portal')}
print(json.dumps({'files':files,'guards':guards,'services':services}))
'''


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    baseline = remote_tools.remote(INSPECT, {})
    target = FOLDER / 'remote-baseline.json'
    if target.exists():
        previous = json.loads(target.read_text(encoding='utf-8'))
        if previous['files'] != baseline['files'] or previous['guards'] != baseline['guards']:
            raise RuntimeError('Inspected baseline changed; preserve previous evidence')
    else:
        with target.open('x', encoding='utf-8') as out:
            json.dump(baseline, out, indent=2)
    context = ssl.create_default_context()
    base = 'https://185.184.42.88/updates/'
    with urllib.request.urlopen(base + 'manifest.json', context=context, timeout=30) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != baseline['guards']['/var/www/tio-client/updates/manifest.json']:
        raise RuntimeError('HTTPS/SSH client manifest differs')
    client = FOLDER / 'client/source'
    client.mkdir(parents=True, exist_ok=True)
    (client / 'manifest.json').write_bytes(raw)
    manifest = json.loads(raw)
    downloaded = {}
    for entry in manifest['files']:
        if entry['path'].lower() not in ('silver.dll', 'ti.exe', 'orange.dll'):
            continue
        digest = entry['sha256']
        with urllib.request.urlopen(base + 'blobs/' + digest, context=context, timeout=45) as response:
            data = response.read()
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError('Hosted blob checksum failed')
        (client / entry['path']).write_bytes(data)
        downloaded[entry['path']] = {'sha256':digest,'size':len(data)}
    differences = [n for n, e in baseline['files'].items()
                   if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=e['sha256']]
    print(json.dumps({'version':manifest['version'],'downloaded':downloaded,
                      'server_local_differences':differences,'baseline':str(target)}, indent=2))


if __name__ == '__main__':
    main()
