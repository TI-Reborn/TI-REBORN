"""Read the actual VPS baseline and package only the authorized game TLS files."""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('server/config.py', 'server/runtime.py', 'server/multi.py', 'server/tls.py',
         'deploy/renew_game_tls.py')
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=8', 'root@185.184.42.88']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', type=Path, required=True)
    args = parser.parse_args(argv)
    folder = ROOT/'reports/game-tls'
    folder.mkdir(parents=True, exist_ok=True)
    code = r'''import pathlib,json,sys,hashlib,sqlite3,subprocess
root=pathlib.Path('/opt/tio-emulator');files=json.load(sys.stdin)
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
def entry(path,source=False):
 if not path.exists():return {'sha256':None,'source':None}
 raw=path.read_bytes()
 return {'sha256':hashlib.sha256(raw).hexdigest(),'source':raw.decode('utf-8') if source else None}
print(json.dumps({'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],
 'accounts':db.execute('SELECT count(*) FROM accounts').fetchone()[0],
 'files':{name:entry(root/name,True) for name in files},
 'server_config':entry(pathlib.Path('/etc/tio-server/server.toml'),True),
 'launcher':entry(pathlib.Path('/var/www/tio-client/downloads/TIO-Launcher.exe')),
 'client_manifest':entry(pathlib.Path('/var/www/tio-client/updates/manifest.json')),
 'listeners':subprocess.check_output(['ss','-ltn'],text=True),
 'service':subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()}))'''
    data = json.loads(subprocess.run(SSH+['python3 -c '+shlex.quote(code)], input=json.dumps(FILES),
                                    capture_output=True, text=True, encoding='utf-8', check=True, timeout=30).stdout)
    if data['integrity'] != 'ok' or data['service'] != 'active':
        raise RuntimeError('Actual game service/database baseline is not healthy')
    manifest = {'schema': 1, 'files': {}, 'server_config_before': data['server_config']['sha256'],
                'launcher_before': data['launcher']['sha256'],
                'launcher_after': hashlib.sha256(args.launcher.read_bytes()).hexdigest(),
                'client_manifest': data['client_manifest']['sha256']}
    for name in FILES:
        item = data['files'][name]
        if item['source'] is not None:
            target = folder/'remote-before'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item['source'], encoding='utf-8', newline='')
        manifest['files'][name] = {'before': item['sha256'], 'after': hashlib.sha256((ROOT/name).read_bytes()).hexdigest()}
    (folder/'remote-before/server.toml').write_text(data['server_config']['source'], encoding='utf-8', newline='')
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    inspection = {key: data[key] for key in ('integrity', 'accounts', 'listeners', 'service')}
    (folder/'inspection.json').write_text(json.dumps(inspection, indent=2)+'\n', encoding='utf-8')
    with tarfile.open(folder/'patch.tar.gz', 'w:gz') as bundle:
        for name in FILES:
            bundle.add(ROOT/name, arcname=name)
        bundle.add(args.launcher, arcname='TIO-Launcher.exe')
        bundle.add(folder/'manifest.json', arcname='manifest.json')
    digest = hashlib.sha256((folder/'patch.tar.gz').read_bytes()).hexdigest()
    (folder/'patch.tar.gz.sha256').write_text(digest+'  tio-game-tls-patch.tar.gz\n', encoding='ascii')
    print(json.dumps(dict(files=len(FILES), archive_sha256=digest, **inspection)))


if __name__ == '__main__':
    main()
