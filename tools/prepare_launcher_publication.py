"""Inspect and optionally back up the hosted launcher publication before review.

Only the explicit --backup operation creates private remote backup files. It
reuses the existing online SQLite/code/config backup and fully restores the
PostgreSQL dump into a temporary database through the deployed backup checker.
No publication, game socket, account mutation or service restart occurs.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_site_backups_remote import REMOTE as BACKUP_REMOTE

PRELUDE = r'''
from datetime import datetime, timezone
from pathlib import Path
import hashlib, importlib.util, json, os, shutil, subprocess
os.umask(0o077)
def digest_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()
def file_state(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Unexpected publication file')
    info=path.stat()
    return {'sha256':digest_file(path),'bytes':info.st_size,'mode':info.st_mode&0o777,'uid':info.st_uid,'gid':info.st_gid}
def service(name):
    value=subprocess.run(['/usr/bin/systemctl','show',name,'-p','MainPID','-p','NRestarts','-p','ActiveState'],capture_output=True,text=True,check=True).stdout
    return dict(line.split('=',1) for line in value.splitlines() if '=' in line)
spec=importlib.util.spec_from_file_location('portal_backup','/opt/tio-portal/portal_backup.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
def download_row():
    query="SELECT jsonb_build_object('row',(SELECT to_jsonb(d) FROM \"DownloadVersion\" d WHERE id='main'),'download_rows',(SELECT count(*) FROM \"DownloadVersion\"),'web_users',(SELECT count(*) FROM \"User\"))"
    output=checker._command(['psql','-X','--no-psqlrc','--no-align','--tuples-only','--set=ON_ERROR_STOP=1','--dbname=tionline_web','--command='+query],'public metadata',runner=subprocess.run,stdout=subprocess.PIPE)
    return json.loads(output.stdout)
def baseline():
    launcher=Path('/var/www/tio-client/downloads/TIO-Launcher.exe')
    manifest=Path('/var/www/tio-client/updates/manifest.json')
    versioned=Path('/var/www/tio-client/downloads/TIO-Launcher-0.1.4.exe')
    return {'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
      'launcher':file_state(launcher),'client_manifest':file_state(manifest),
      'client_version':json.loads(manifest.read_text())['version'],
      'versioned_target_exists':versioned.exists() or versioned.is_symlink(),
      'metadata':download_row(),'portal_release':str(Path('/opt/tio-portal/current').resolve(strict=True)),
      'services':{name:service(name) for name in ('tio-server','tio-game-api','tio-portal')},
      'configuration':{name:file_state(name) for name in ('/etc/tio-server/server.toml','/etc/tio-portal/portal.env','/etc/nginx/snippets/tio-updates.conf')}}
before=baseline()
'''


def remote_source(backup=False):
    if not backup:
        return PRELUDE + "print(json.dumps(before))\n"
    core = BACKUP_REMOTE.replace("prefix='tio-before-site-backups-'", "prefix='tio-before-launcher-'")
    core = core.replace("subprocess.run(['runuser','-u','postgres','--','pg_dump','--format=custom','--dbname=tionline_web'],stdout=output,check=True)",
        "checker._command(['pg_dump','--format=custom','--dbname=tionline_web'],'pre-publication dump',runner=subprocess.run,stdout=output)")
    core = core.replace("subprocess.run(['pg_restore','--list',str(dump)],stdout=subprocess.DEVNULL,check=True)",
        "restored_counts=checker.validate_dump(dump)")
    # Insert publication assets before calculating the private backup receipt.
    marker = "result={'created_utc':"
    if marker not in core or core.count("print(json.dumps(result))") != 1:
        raise ValueError('Existing backup helper structure changed; review adapter')
    additions = r'''
for name in ('TIO-Launcher.exe',):
    source=Path('/var/www/tio-client/downloads')/name
    target=folder/name
    with source.open('rb') as input_stream,target.open('xb') as output:
        shutil.copyfileobj(input_stream,output,1024*1024);output.flush();os.fsync(output.fileno())
    if file_state(target)['sha256']!=before['launcher']['sha256']:raise ValueError('Launcher changed during backup')
manifest_target=folder/'client-manifest.json'
with Path('/var/www/tio-client/updates/manifest.json').open('rb') as input_stream,manifest_target.open('xb') as output:
    shutil.copyfileobj(input_stream,output);output.flush();os.fsync(output.fileno())
if file_state(manifest_target)['sha256']!=before['client_manifest']['sha256']:raise ValueError('Client manifest changed during backup')
(folder/'publication-before.json').write_text(json.dumps(before,indent=2)+'\n')
after=baseline()
for key in ('launcher','client_manifest','client_version','versioned_target_exists','metadata','portal_release','services','configuration'):
    if before[key]!=after[key]:raise ValueError('Publication baseline changed during backup')
'''
    core = core.replace(marker, additions + "\n" + marker)
    core = core.replace("'website_dump_structure_verified':True,", "'website_dump_structure_verified':True,'website_full_isolated_restore':True,'website_restored_tables':restored_counts,")
    core = core.replace("print(json.dumps(result))", "result['publication_baseline']=before\nprint(json.dumps(result))")
    return PRELUDE + core


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.report.exists() or args.report.is_symlink():parser.error('Refusing to replace an existing report')
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
        '-o','ConnectTimeout=15','root@185.184.42.88','/usr/bin/python3 -'],
        input=remote_source(args.backup),text=True,capture_output=True)
    if result.returncode:
        raise RuntimeError('Remote launcher inspection/backup failed; private subprocess output suppressed')
    data=json.loads(result.stdout)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as output:output.write(json.dumps(data,indent=2)+'\n')
    print(json.dumps({'report':str(args.report.resolve()),'backup':data.get('backup'),
                     'baseline':data.get('publication_baseline',data),'publication_executed':False}))


if __name__=='__main__':main()
