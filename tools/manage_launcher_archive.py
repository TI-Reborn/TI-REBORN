"""Inspect, prepare or publish a compressed package of the exact hosted release.

Builds on the server from immutable published blobs. Never uploads local client
data. Publication requires a verified fresh backup from prepare_launcher_publication
and only adds an optional archive descriptor to the existing manifest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import fcntl, hashlib, json, os, shutil, subprocess, tempfile
from pathlib import Path
os.umask(0o077)
base=Path('/var/www/tio-client/updates'); path=base/'manifest.json'
def sha(p):
    with Path(p).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def services():
    return {n:subprocess.check_output(['systemctl','show',n,'-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
            for n in ('tio-server','tio-game-api','tio-portal')}
raw=path.read_bytes(); manifest=json.loads(raw); baseline=hashlib.sha256(raw).hexdigest()
if baseline!=request['baseline']:raise ValueError('Hosted manifest changed')
before=services()
if request['action']=='inspect':
    result=dict(version=manifest['version'],files=len(manifest['files']),bytes=sum(f['size'] for f in manifest['files']),
        unique_blobs=len({f['sha256'] for f in manifest['files']}),disk_free=shutil.disk_usage(base).free,
        manifest_sha256=baseline,archive=manifest.get('archive'),services=before,remote_mutations=0,
        nginx=Path('/etc/nginx/snippets/tio-updates.conf').read_text())
elif request['action']=='prepare':
    folder=Path(tempfile.mkdtemp(prefix='tio-client-archive-',dir='/root'))
    (folder/'previous-manifest.json').write_bytes(raw)
    descriptor=builder['build'](manifest,base/'blobs',folder/'client.zip')
    updated={**manifest,'archive':descriptor}
    new=json.dumps(updated,ensure_ascii=False,indent=2).encode()+b'\n'
    (folder/'manifest.json').write_bytes(new)
    result=dict(folder=str(folder),baseline_sha256=baseline,manifest_sha256=hashlib.sha256(new).hexdigest(),
        archive=descriptor,version=manifest['version'],files=len(manifest['files']),
        bytes=sum(f['size'] for f in manifest['files']),unique_blobs=len({f['sha256'] for f in manifest['files']}))
    (folder/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
elif request['action']=='rollback':
    receipt=request['prepared']; backup=Path(request['backup']['backup'])
    if backup.parent!=Path('/root') or not backup.name.startswith('tio-before-launcher-') or backup.is_symlink():raise ValueError('Invalid backup')
    previous=backup/'client-manifest.json'
    if sha(previous)!=receipt['baseline_sha256'] or baseline!=receipt['manifest_sha256']:raise ValueError('Rollback baseline changed')
    old=json.loads(previous.read_text())
    if manifest!={**old,'archive':receipt['archive']}:raise ValueError('Rollback would alter other records')
    with open('/root/tio-client-archive-publication.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fd,name=tempfile.mkstemp(prefix='.manifest-rollback-',dir=base)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(previous.read_bytes());out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),0o644)
            if sha(path)!=baseline:raise ValueError('Manifest changed before rollback')
            os.replace(name,path)
            fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if os.path.exists(name):os.unlink(name)
    result=dict(rolled_back=True,manifest_sha256=sha(path),archive_blob_retained=True,service_restarts=0,database_restored=False)
elif request['action']=='publish':
    receipt=request['prepared']; folder=Path(receipt['folder']); backup=Path(request['backup']['backup'])
    if folder.parent!=Path('/root') or not folder.name.startswith('tio-client-archive-') or folder.is_symlink():raise ValueError('Invalid stage')
    if backup.parent!=Path('/root') or not backup.name.startswith('tio-before-launcher-') or backup.is_symlink():raise ValueError('Invalid backup')
    saved=json.loads((backup/'backup-manifest.json').read_text())
    if saved['sqlite_integrity']!='ok' or not saved['website_full_isolated_restore']:raise ValueError('Backup verification required')
    if sha(backup/'client-manifest.json')!=baseline:raise ValueError('Backup does not contain current manifest')
    if json.loads((folder/'receipt.json').read_text())!=receipt or receipt['baseline_sha256']!=baseline:raise ValueError('Prepared receipt mismatch')
    if sha(folder/'manifest.json')!=receipt['manifest_sha256']:raise ValueError('Candidate manifest changed')
    updated=json.loads((folder/'manifest.json').read_text()); descriptor=receipt['archive']
    if updated!={**manifest,'archive':descriptor} or descriptor['filesSha256']!=builder['files_digest'](manifest):raise ValueError('File records changed')
    archive=folder/'client.zip'
    if sha(archive)!=descriptor['sha256'] or archive.stat().st_size!=descriptor['size']:raise ValueError('Prepared ZIP changed')
    with open('/root/tio-client-archive-publication.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        target=base/'blobs'/descriptor['sha256']
        if target.exists():
            if target.is_symlink() or sha(target)!=descriptor['sha256']:raise ValueError('Immutable archive collision')
        else:
            fd,name=tempfile.mkstemp(prefix='.archive-',dir=base/'blobs')
            try:
                with os.fdopen(fd,'wb') as out,archive.open('rb') as src:
                    shutil.copyfileobj(src,out);out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),0o644)
                os.link(name,target)
            finally:os.unlink(name)
        fd=os.open(base/'blobs',os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        # Manifest-last commit. Guard against concurrent resource publication.
        fd,name=tempfile.mkstemp(prefix='.manifest-archive-',dir=base)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write((folder/'manifest.json').read_bytes());out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),0o644)
            if sha(path)!=baseline:raise ValueError('Manifest changed before commit')
            os.replace(name,path)
            fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if os.path.exists(name):os.unlink(name)
    result={**receipt,'published':True,'backup':str(backup),'service_restarts':0}
else:raise ValueError('Unknown action')
if services()!=before:raise ValueError('Service state changed')
print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inspect','prepare','publish','rollback'])
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--prepared',type=Path)
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():raise FileExistsError(args.report)
    request=dict(action=args.action,baseline=args.baseline)
    if args.action in ('publish','rollback'):
        if args.prepared is None or args.backup is None:parser.error('Publish needs prepared and backup reports')
        request.update(prepared=json.loads(args.prepared.read_text()),backup=json.loads(args.backup.read_text()))
    builder=(ROOT/'launcher/build_archive.py').read_text(encoding='utf-8')
    source='request='+repr(request)+"\nbuilder={'__name__':'launcher_archive_builder'}\nexec(compile("+repr(builder)+",'archive-builder','exec'),builder)\n"+REMOTE
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',
        'root@185.184.42.88','python3 -'],input=source,text=True,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'Remote archive operation failed')
    data=json.loads(result.stdout);args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as out:out.write(json.dumps(data,indent=2)+'\n')
    print(json.dumps(data))


if __name__=='__main__':main()
