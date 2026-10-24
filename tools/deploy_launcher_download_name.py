"""Set a stable browser filename using the freshly backed-up nginx baseline."""
import argparse
import json
from pathlib import Path
import subprocess

BLOCK = r'''# Keep immutable version URLs for self-updates while browsers save a stable name.
location ~ ^/downloads/TIO-Launcher(?:-[0-9]+\.[0-9]+\.[0-9]+)?\.exe$ {
    root /var/www/tio-client;
    default_type application/octet-stream;
    etag off;
    if_modified_since off;
    add_header Content-Disposition 'attachment; filename="TIO-Launcher.exe"';
    add_header Cache-Control "no-cache" always;
    autoindex off;
    try_files $uri =404;
}
'''

REMOTE = r'''
import hashlib,json,os,subprocess
from pathlib import Path
configuration=CONFIGURATION
target=Path('/etc/nginx/snippets/tio-updates.conf')
backup=Path(configuration['backup'])
if backup.parent!=Path('/root') or not backup.name.startswith('tio-before-launcher-'):
    raise ValueError('Expected a private launcher backup')
if target.is_symlink() or backup.is_symlink():raise ValueError('Symlinks forbidden')
before=target.read_bytes()
if hashlib.sha256(before).hexdigest()!=configuration['baseline_hash']:
    raise ValueError('Nginx configuration differs from the inspected backup')
text=before.decode()
if text.count('location /downloads/ {')!=1 or 'Content-Disposition' in text:
    raise ValueError('Unexpected downloads configuration')
after=text.replace('location /downloads/ {',configuration['block']+'location /downloads/ {').encode()
snapshot=backup/'download-name-nginx-before.conf'
with snapshot.open('xb') as stream:stream.write(before)
snapshot.chmod(0o600)
candidate=target.with_name('tio-updates.conf.download-name-new')
def services():
    return {name:subprocess.check_output(['systemctl','show',name,'-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
        for name in ('tio-server','tio-game-api','tio-portal')}
old_services=services()
try:
    with candidate.open('xb') as stream:
        stream.write(after);stream.flush();os.fsync(stream.fileno())
    candidate.chmod(0o644)
    if target.read_bytes()!=before:raise ValueError('Nginx configuration changed concurrently')
    os.replace(candidate,target)
    subprocess.run(['nginx','-t'],check=True,capture_output=True)
    subprocess.run(['systemctl','reload','nginx'],check=True,capture_output=True)
except BaseException:
    if target.read_bytes()==after:
        target.write_bytes(before)
        subprocess.run(['nginx','-t'],check=True,capture_output=True)
        subprocess.run(['systemctl','reload','nginx'],check=True,capture_output=True)
    raise
finally:candidate.unlink(missing_ok=True)
new_services=services()
if old_services!=new_services:raise ValueError('Application services changed during nginx reload')
print(json.dumps({'status':'passed','backup':str(snapshot),'before_sha256':hashlib.sha256(before).hexdigest(),
    'after_sha256':hashlib.sha256(after).hexdigest(),'nginx_syntax':'passed','nginx_reload':True,
    'application_services_unchanged':True,'filename':'TIO-Launcher.exe'}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-report',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():raise FileExistsError(args.report)
    prior=json.loads(args.backup_report.read_text())
    if prior.get('sqlite_integrity')!='ok' or prior.get('website_full_isolated_restore') is not True:
        raise ValueError('A verified fresh hosted backup is required')
    configuration={'backup':prior['backup'],'block':BLOCK,
        'baseline_hash':prior['publication_baseline']['configuration']['/etc/nginx/snippets/tio-updates.conf']['sha256']}
    source=REMOTE.replace('configuration=CONFIGURATION','configuration='+repr(configuration),1)
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
        '-o','ConnectTimeout=15','root@185.184.42.88','python3 -'],input=source,text=True,capture_output=True,timeout=60)
    if result.returncode:
        error=result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'No remote diagnostic'
        raise RuntimeError('Download filename deployment failed: '+error)
    report=json.loads(result.stdout)
    with args.report.open('x',encoding='utf-8') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
