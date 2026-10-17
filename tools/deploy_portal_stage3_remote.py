"""Publish a prebuilt portal release while preserving hosted saves and config."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import subprocess

REMOTE=r'''
import hashlib,json,os,posixpath,pwd,grp,subprocess,tarfile,time,urllib.request,shlex,signal
from pathlib import Path
configuration=CONFIGURATION
backup=Path(configuration['backup'])
if not (backup/'backup-manifest.json').is_file():raise RuntimeError('Missing pre-update backup')
if not (backup/'reservation.sqlite3').is_file() or not (backup/'website.dump').is_file():raise RuntimeError('Missing database backups')
current=Path('/opt/tio-portal/current')
previous=current.resolve(strict=True)
if str(previous)!=configuration['previous_release']:raise RuntimeError('Portal release changed after inspection')
archive=Path(configuration['archive'])
if hashlib.sha256(archive.read_bytes()).hexdigest()!=configuration['sha256']:raise RuntimeError('Release checksum mismatch')
target=Path('/opt/tio-portal/releases')/configuration['release_id']
target.mkdir(mode=0o755)
with tarfile.open(archive,'r:gz') as source:
    for member in source.getmembers():
        parts=Path(member.name).parts
        if member.name.startswith('/') or '..' in parts or any(part=='.env' or part.startswith('.env.') for part in parts):
            raise RuntimeError('Unsafe release member')
        if member.issym() or member.islnk():
            link=posixpath.normpath(posixpath.join(posixpath.dirname(member.name),member.linkname))
            if link.startswith('../') or link.startswith('/'):raise RuntimeError('Unsafe release link')
    source.extractall(target,filter='data')
if not (target/'server.js').is_file():raise RuntimeError('Missing standalone entry point')
for folder,dirs,files in os.walk(target,followlinks=False):
    os.chmod(folder,0o755)
    for name in files:
        path=Path(folder)/name
        if not path.is_symlink():os.chmod(path,0o644)
# The hardened service permits writes to .next/cache. Custom build directories
# resolve their cache there, retaining the existing filesystem restriction.
legacy_cache=target/'.next/cache';legacy_cache.mkdir(parents=True,exist_ok=True);legacy_cache.chmod(0o700)
os.chown(legacy_cache,pwd.getpwnam('tio-web').pw_uid,grp.getgrnam('tio-web').gr_gid)
cache=target/configuration['dist_dir']/'cache'
if configuration['dist_dir']!='.next':
    if cache.exists():
        if cache.is_symlink() or any(cache.iterdir()):raise RuntimeError('Unexpected packaged cache contents')
        cache.rmdir()
    cache.symlink_to('../.next/cache',target_is_directory=True)

# Verify the complete Linux release on a separate loopback port before switching
# the live pointer. Credentials stay in the child environment and private log.
environment=dict(os.environ)
for line in Path('/etc/tio-portal/portal.env').read_text().splitlines():
    if line and not line.startswith('#') and '=' in line:
        key,value=line.split('=',1);parsed=shlex.split(value)
        environment[key]=parsed[0] if parsed else ''
environment.update(PORT='3002',HOSTNAME='127.0.0.1',NODE_ENV='production',NEXT_TELEMETRY_DISABLED='1')
log=target/'preflight-private.log'
with log.open('xb') as output:
    log.chmod(0o600)
    process=subprocess.Popen(['runuser','-u','tio-web','--','/opt/tio-node/bin/node','server.js'],cwd=target,
        env=environment,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        for attempt in range(25):
            if process.poll() is not None:raise RuntimeError('Release preflight exited; inspect private preflight log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:3002/api/health',timeout=2) as response:data=json.load(response)
                if data.get('status')=='ok':break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('Release preflight health failed; inspect private preflight log')
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(5)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(5)
def point(path):
    temporary=current.with_name('current-'+configuration['release_id'])
    temporary.symlink_to(path,target_is_directory=True)
    temporary.replace(current)
def healthy():
    for attempt in range(25):
        try:
            with urllib.request.urlopen('http://127.0.0.1:3000/api/health',timeout=2) as response:
                data=json.load(response)
            if data.get('status')=='ok':return True
        except Exception:pass
        time.sleep(1)
    return False
point(target)
try:
    subprocess.run(['systemctl','restart','tio-portal'],check=True)
    if not healthy():raise RuntimeError('New portal failed health check')
except BaseException:
    point(previous)
    subprocess.run(['systemctl','restart','tio-portal'],check=True)
    healthy()
    raise
game=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
result={'release':str(target),'previous_release':str(previous),'archive_sha256':configuration['sha256'],
        'backup':str(backup),'private_health':'ok','database_migrations':False,'game_restart_requested':False,
        'linux_release_preflight':'ok',
        'game_service':dict(line.split('=',1) for line in game.strip().splitlines())}
print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--backup-report',type=Path,required=True)
    parser.add_argument('--release-id',required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--dist-dir',default='.next')
    args=parser.parse_args()
    import re
    if not re.fullmatch(r'tireborn-[a-zA-Z0-9_-]+',args.release_id):parser.error('Invalid release identifier')
    if not re.fullmatch(r'\.next(?:-[a-z0-9-]+)?',args.dist_dir):parser.error('Invalid build directory')
    if args.report.exists():parser.error('Refusing to replace an existing deployment report')
    prior=json.loads(args.backup_report.read_text(encoding='utf-8'))
    digest=hashlib.sha256(args.archive.read_bytes()).hexdigest()
    remote_archive='/root/tio-site-stage3-'+secrets.token_hex(8)+'.tar.gz'
    key=str(Path.home()/'.ssh/tio_server')
    subprocess.run(['scp','-i',key,'-o','BatchMode=yes',str(args.archive),'root@185.184.42.88:'+remote_archive],check=True,capture_output=True)
    settings={'archive':remote_archive,'sha256':digest,'backup':prior['backup'],
              'previous_release':prior['previous_portal_release'],'release_id':args.release_id,'dist_dir':args.dist_dir}
    script=REMOTE.replace('CONFIGURATION',repr(settings),1)
    result=subprocess.run(['ssh','-i',key,'-o','BatchMode=yes','root@185.184.42.88','python3 -'],
                          input=script,text=True,capture_output=True,check=True)
    data=json.loads(result.stdout)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data))


if __name__=='__main__':main()
