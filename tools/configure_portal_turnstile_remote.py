"""Configure production Turnstile without printing or passing keys in arguments.

Requires the verified email release and saves the current environment privately.
Only tio-portal restarts; configuration and service health roll back on failure.
The provider check uses an invalid response, not a real browser challenge.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


HOST = 'root@185.184.42.88'
HOSTNAME = 'ti-reborn.com'


def production_key(value):
    return (isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_-]{20,128}', value) is not None
            and re.match(r'^[123]x0{20,}', value) is None
            and not any(marker in value.upper() for marker in ('YOUR_', 'PLACEHOLDER', 'CHANGEME', 'DUMMY')))


REMOTE = r'''
import fcntl, hashlib, json, os, re, shlex, stat, subprocess, sys, time, urllib.request, urllib.parse, uuid
from datetime import datetime, timezone
from pathlib import Path
settings=CONFIGURATION
phase='predeployment verification'
changed=False; backup_file=None; environment=None; old=None; new=None; original_info=None
rollback_attempted=False; rollback_verified=False; game_before=None
os.umask(0o077)

def require(condition, message):
    if not condition: raise RuntimeError(message)

def production_key(value):
    return (isinstance(value,str) and re.fullmatch(r'[a-zA-Z0-9_-]{20,128}',value) is not None
            and re.match(r'^[123]x0{20,}',value) is None
            and not any(marker in value.upper() for marker in ('YOUR_','PLACEHOLDER','CHANGEME','DUMMY')))

def sha(value): return hashlib.sha256(value).hexdigest()

def game_identity():
    result=subprocess.run(['systemctl','show','tio-server','--property=MainPID','--property=NRestarts',
                           '--property=ActiveState','--property=ExecMainStartTimestampMonotonic'],
                          capture_output=True,text=True,timeout=10)
    require(result.returncode==0,'Cannot inspect game service')
    return dict(line.split('=',1) for line in result.stdout.strip().splitlines() if '=' in line)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

opener=urllib.request.build_opener(NoRedirect)

def read_url(url,limit,timeout=5):
    request=urllib.request.Request(url,headers={'User-Agent':'TIREBORN-Turnstile-Setup/1.0','Cache-Control':'no-cache'})
    with opener.open(request,timeout=timeout) as response:
        require(response.status==200 and response.geturl()==url,'Unexpected HTTP response')
        body=response.read(limit+1)
        require(len(body)<=limit,'HTTP response exceeded the configured bound')
        return body

def healthy():
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        try:
            result=json.loads(read_url('http://127.0.0.1:3000/api/health',8192,2))
            if result.get('status')=='ok' and result.get('database')=='ready' and result.get('gameBridge')=='ready':
                return True
        except Exception: pass
        time.sleep(1)
    return False

def restart_portal():
    result=subprocess.run(['systemctl','restart','tio-portal'],capture_output=True,timeout=35)
    require(result.returncode==0,'Portal restart failed')

def replace_environment(content,mode):
    temporary=environment.with_name('.portal-turnstile-'+uuid.uuid4().hex+'.env')
    try:
        with temporary.open('xb') as output:
            output.write(content); output.flush(); os.fsync(output.fileno())
        temporary.chmod(mode); os.chown(temporary,original_info.st_uid,original_info.st_gid)
        temporary.replace(environment)
        descriptor=os.open(str(environment.parent),os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)

lock_file=None
try:
    require(production_key(settings['site_key']) and production_key(settings['secret_key']),
            'Production widget keys are required')
    lock_descriptor=os.open('/run/lock/tio-portal-turnstile.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    lock_file=os.fdopen(lock_descriptor,'r+')
    lock_info=os.fstat(lock_file.fileno())
    require(lock_info.st_uid==0 and stat.S_IMODE(lock_info.st_mode)&0o077==0,'Unsafe configuration lock')
    fcntl.flock(lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
    backup=Path(settings['backup'])
    require(re.fullmatch(r'/root/tio-before-site-backups-[a-z0-9_]+',str(backup)) is not None
            and backup.is_dir() and not backup.is_symlink() and backup.resolve()==backup,
            'Unexpected private backup layout')
    require(backup.stat().st_uid==0 and stat.S_IMODE(backup.stat().st_mode)&0o077==0,
            'Backup directory is not private')
    manifest=backup/'backup-manifest.json'
    require(manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_uid==0
            and stat.S_IMODE(manifest.stat().st_mode)&0o077==0,'Private backup manifest is missing')
    prior=json.loads(manifest.read_text())
    require(sha(json.dumps(prior,sort_keys=True,separators=(',',':')).encode())==settings['backup_manifest_sha256'],
            'Backup report differs from the hosted manifest')
    require(prior.get('backup')==str(backup) and prior.get('sqlite_integrity')=='ok'
            and prior.get('website_dump_structure_verified') is True,'Backup evidence differs')
    current=Path('/opt/tio-portal/current').resolve(strict=True)
    require(str(current)==settings['release'],'Portal release changed after deployment')
    require(re.fullmatch(r'/opt/tio-portal/releases/tireborn-[a-zA-Z0-9_-]+',str(current)) is not None,
            'Unexpected portal release layout')
    game_before=game_identity()
    require(game_before.get('ActiveState')=='active' and int(game_before.get('MainPID','0'))>0,
            'Game service is not active')
    require(healthy(),'Existing portal health is not ready')
    environment=Path('/etc/tio-portal/portal.env')
    require(environment.is_file() and not environment.is_symlink(),'Portal environment is unavailable')
    original_info=environment.stat()
    require(original_info.st_uid==0 and stat.S_IMODE(original_info.st_mode)&0o007==0
            and stat.S_IMODE(original_info.st_mode)&0o020==0,'Portal environment permissions differ')
    old=environment.read_bytes()
    values={}; lines=old.decode('utf-8').splitlines()
    assignment=re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$')
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'): continue
        match=assignment.fullmatch(line)
        require(match is not None,'Unexpected environment syntax')
        parsed=shlex.split(match.group(2),posix=True)
        require(len(parsed)<=1,'Ambiguous environment value')
        values[match.group(1)]=parsed[0] if parsed else ''
    require(values.get('EMAIL_VERIFICATION_REQUIRED')=='true','Email verification must remain required')
    require(values.get('SITE_URL','').rstrip('/')=='https://ti-reborn.com','Trusted portal origin differs')
    require(re.fullmatch(r're_[a-zA-Z0-9_-]{20,200}',values.get('RESEND_API_KEY','')) is not None
            and re.fullmatch(r'[a-zA-Z0-9_.+-]+@ti-reborn\.com',values.get('MAIL_FROM','')) is not None,
            'Resend HTTPS configuration is not ready')

    phase='Cloudflare invalid-token verification'
    request=urllib.request.Request('https://challenges.cloudflare.com/turnstile/v0/siteverify',
        data=urllib.parse.urlencode({'secret':settings['secret_key'],'response':'TIREBORN.INVALID.SETUP.RESPONSE'}).encode(),
        headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'TIREBORN-Turnstile-Setup/1.0'},method='POST')
    with opener.open(request,timeout=12) as response:
        require(response.status==200,'Cloudflare verification did not succeed')
        body=response.read(8193)
        require(len(body)<=8192,'Unexpected provider response size')
        provider=json.loads(body)
    require(isinstance(provider,dict) and provider.get('success') is False
            and provider.get('error-codes')==['invalid-input-response'],
            'Cloudflare secret validation failed')

    phase='private environment backup'
    require(environment.read_bytes()==old,'Portal environment changed during inspection')
    backup_file=backup/('portal-before-turnstile-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]+'.env')
    with backup_file.open('xb') as output:
        output.write(old); output.flush(); os.fsync(output.fileno())
    backup_file.chmod(0o600)
    backup_descriptor=os.open(str(backup),os.O_DIRECTORY)
    try: os.fsync(backup_descriptor)
    finally: os.close(backup_descriptor)
    updates={'TURNSTILE_REQUIRED':'true','TURNSTILE_HOSTNAME':'ti-reborn.com',
             'TURNSTILE_SITE_KEY':settings['site_key'],'TURNSTILE_SECRET_KEY':settings['secret_key']}
    retained=[line for line in lines if not assignment.fullmatch(line)
              or assignment.fullmatch(line).group(1) not in updates]
    retained.extend(key+'='+shlex.quote(value) for key,value in updates.items())
    new=('\n'.join(retained)+'\n').encode('utf-8')
    phase='atomic configuration update'
    require(environment.read_bytes()==old,'Portal environment changed before installation')
    # Mark the operation before replacement so a later fsync failure also enters
    # rollback, which verifies the actual content before overwriting anything.
    changed=True
    replace_environment(new,0o600)
    phase='portal restart and health'
    restart_portal()
    require(healthy(),'Configured portal failed private health checks')
    phase='public registration and claim HTML'
    html_checked=[]
    for locale in ('ru','en'):
        for page,action in (('register','register'),('claim-existing','claim')):
            url='https://ti-reborn.com/'+locale+'/'+page
            html=read_url(url,2*1024*1024,8)
            require(settings['site_key'].encode() in html and b'captcha-slot' in html
                    and ('data-action="'+action+'"').encode() in html,'Widget configuration is absent from public HTML')
            require(settings['secret_key'].encode() not in html and values['RESEND_API_KEY'].encode() not in html,
                    'Private configuration leaked into public HTML')
            html_checked.append('/'+locale+'/'+page)
    require(environment.read_bytes()==new,'Portal environment changed after activation')
    game_after=game_identity()
    require(game_before==game_after,'Game service identity changed during portal update')
    result={'ok':True,'created_utc':datetime.now(timezone.utc).isoformat(),'release':str(current),
            'provider':'Cloudflare Turnstile','siteverify_invalid_token_check':'invalid-input-response',
            'required':True,'hostname':'ti-reborn.com','production_key_format_verified':True,
            'environment_backup':str(backup_file),'previous_environment_sha256':sha(old),
            'new_environment_sha256':sha(new),'email_verification_required_preserved':True,
            'resend_configuration_preserved':True,'private_health':'ok','public_widget_pages':html_checked,
            'portal_restart_requested':True,'game_restart_requested':False,'game_identity_unchanged':True,
            'interactive_widget_verified':False}
    print(json.dumps(result))
except Exception:
    if changed and environment is not None and old is not None and new is not None:
        rollback_attempted=True
        try:
            actual=environment.read_bytes()
            require(actual in (old,new),'Environment changed independently; refusing an unsafe rollback')
            if actual!=old: replace_environment(old,stat.S_IMODE(original_info.st_mode))
            restart_portal()
            rollback_verified=healthy() and environment.read_bytes()==old
        except Exception: rollback_verified=False
    unchanged=None
    if game_before is not None:
        try: unchanged=game_before==game_identity()
        except Exception: pass
    print(json.dumps({'ok':False,'phase':phase,'error':'Turnstile setup failed; credentials are not included',
                      'environment_backup':str(backup_file) if backup_file else None,
                      'rollback_attempted':rollback_attempted,'rollback_verified':rollback_verified,
                      'game_restart_requested':False,'game_identity_unchanged':unchanged,
                      'remote_state_requires_recheck':True}))
    sys.exit(1)
finally:
    if lock_file is not None: lock_file.close()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--backup-report', type=Path, required=True)
    parser.add_argument('--deployment-report', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Refusing to replace an existing Turnstile report')
    try:
        if args.key_file.stat().st_size > 4096:
            raise ValueError('Invalid key file')
        keys = json.loads(args.key_file.read_text(encoding='utf-8-sig'))
        if (not isinstance(keys,dict) or set(keys) != {'siteKey','secretKey'}
                or not production_key(keys['siteKey']) or not production_key(keys['secretKey'])):
            parser.error('Full production widget keys are required; test keys are rejected')
        prior = json.loads(args.backup_report.read_text(encoding='utf-8'))
        deployment = json.loads(args.deployment_report.read_text(encoding='utf-8'))
        if (not isinstance(prior,dict) or not isinstance(deployment,dict)
                or prior.get('sqlite_integrity') != 'ok' or prior.get('website_dump_structure_verified') is not True
                or deployment.get('private_health') != 'ok' or deployment.get('linux_release_preflight') != 'ok'
                or deployment.get('game_restart_requested') is not False
                or deployment.get('backup') != prior.get('backup')
                or deployment.get('previous_release') != prior.get('previous_portal_release')
                or not isinstance(deployment.get('release'),str)):
            raise ValueError('Invalid deployment evidence')
        settings = {
            'site_key':keys['siteKey'],'secret_key':keys['secretKey'],'backup':prior['backup'],
            'release':deployment['release'],
            'backup_manifest_sha256':hashlib.sha256(json.dumps(prior,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        }
        args.report.parent.mkdir(parents=True,exist_ok=True)
        with args.report.open('x',encoding='utf-8') as report:
            try:
                completed = subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
                                            '-o','ConnectTimeout=15',HOST,'python3 -'],
                                           input=REMOTE.replace('CONFIGURATION',repr(settings),1),
                                           text=True,capture_output=True,timeout=240)
                data = json.loads(completed.stdout)
                if (not isinstance(data,dict) or type(data.get('ok')) is not bool
                        or (data['ok'] and (completed.returncode != 0 or data.get('release') != settings['release']
                                           or data.get('required') is not True or data.get('hostname') != HOSTNAME
                                           or data.get('game_identity_unchanged') is not True))):
                    raise ValueError('Unverified remote result')
            except (OSError,subprocess.SubprocessError,ValueError):
                data = {'ok':False,'error':'Remote Turnstile configuration outcome could not be confirmed',
                        'remote_state_requires_recheck':True,'game_restart_requested':False}
            report.write(json.dumps(data,indent=2)+'\n')
        print(json.dumps(data))
        return 0 if data['ok'] is True else 1
    except (OSError,ValueError,TypeError,KeyError):
        parser.exit(1,'Turnstile preparation failed; no keys or private values were printed.\n')


if __name__ == '__main__':
    raise SystemExit(main())
