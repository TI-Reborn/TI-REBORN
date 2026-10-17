"""Save hosted databases and previous code/config before a portal/backup update.

Runs online backups without restarting gameplay. Secrets remain in the private
remote backup; the local report contains only paths, sizes and checksums.
"""
import argparse
import json
from pathlib import Path
import subprocess


REMOTE = r'''
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, os, sqlite3, subprocess, tarfile, tempfile
os.umask(0o077)
folder=Path(tempfile.mkdtemp(prefix='tio-before-site-backups-',dir='/root'))
image=folder/'reservation.sqlite3'
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as source, closing(sqlite3.connect(image)) as destination:
    source.backup(destination)
    if destination.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
        raise RuntimeError('SQLite backup integrity failed')
    tables=[r[0] for r in destination.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
    rows={}
    for table in tables:
        quoted='"'+table.replace('"','""')+'"'
        columns=len(destination.execute('PRAGMA table_info('+quoted+')').fetchall())
        digest=hashlib.sha256();count=0
        for row in destination.execute('select * from '+quoted+' order by '+','.join(str(i+1) for i in range(columns))):
            digest.update(repr(tuple(row)).encode('utf-8')+b'\n');count+=1
        rows[table]={'rows':count,'sha256':digest.hexdigest()}
dump=folder/'website.dump'
with dump.open('xb') as output:
    subprocess.run(['runuser','-u','postgres','--','pg_dump','--format=custom','--dbname=tionline_web'],stdout=output,check=True)
subprocess.run(['pg_restore','--list',str(dump)],stdout=subprocess.DEVNULL,check=True)
def filtered(member):
    if '__pycache__' in member.name.split('/') or member.name.endswith('.pyc'):
        return None
    return member
with tarfile.open(folder/'game-code.tar.gz','w:gz') as archive:
    game=Path('/opt/tio-emulator')
    for name in ('server','tio','tools','config','deploy','registration','requirements.txt','pyproject.toml'):
        path=game/name
        if path.exists():archive.add(path,arcname=name,filter=filtered)
portal=Path('/opt/tio-portal/current').resolve(strict=True)
with tarfile.open(folder/'portal-code.tar.gz','w:gz') as archive:
    archive.add(portal,arcname=portal.name,filter=lambda m: None if '/.next/cache' in m.name else m)
with tarfile.open(folder/'operational-config.tar.gz','w:gz') as archive:
    for name in ('/etc/tio-server','/etc/tio-portal','/etc/nginx','/etc/letsencrypt','/opt/tio-portal/backup_portal.sh'):
        path=Path(name)
        if path.exists():archive.add(path,arcname=name.lstrip('/'))
    for path in sorted(Path('/etc/systemd/system').glob('tio-*')):
        archive.add(path,arcname=str(path).lstrip('/'))
def digest_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()
result={'created_utc':datetime.now(timezone.utc).isoformat(),'backup':str(folder),'sqlite_integrity':'ok',
        'game_table_fingerprints':rows,'website_dump_structure_verified':True,
        'previous_portal_release':str(portal),'game_restarted':False,
        'files':{path.name:{'bytes':path.stat().st_size,'sha256':digest_file(path)} for path in sorted(folder.iterdir()) if path.is_file()}}
(folder/'backup-manifest.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():
        parser.error('Refusing to replace an existing backup report')
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
                           '-o','ConnectTimeout=15','root@185.184.42.88','python3 -'],
                          input=REMOTE,text=True,capture_output=True,check=True)
    data=json.loads(result.stdout)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'backup':data['backup'],'sqlite_integrity':data['sqlite_integrity'],
                      'previous_portal_release':data['previous_portal_release'],
                      'files':{name:value['bytes'] for name,value in data['files'].items()}}))


if __name__=='__main__':
    main()
