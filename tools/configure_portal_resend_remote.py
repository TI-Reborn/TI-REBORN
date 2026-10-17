"""Configure Resend HTTPS without putting its key in arguments or reports.

Validates sending access using Resend's simulated delivery address before editing.
Preserves the old environment in the existing private predeployment backup.
Does not restart services; the subsequent portal deployment loads the config.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

REMOTE = r'''
import hashlib,json,os,shlex,sys,urllib.request
from pathlib import Path
settings=CONFIGURATION
os.umask(0o077)
try:
    backup=Path(settings['backup'])
    if not (backup/'backup-manifest.json').is_file():raise RuntimeError('Missing backup')
    if str(Path('/opt/tio-portal/current').resolve(strict=True))!=settings['previous_release']:
        raise RuntimeError('Portal release changed')
    environment=Path('/etc/tio-portal/portal.env')
    old=environment.read_bytes()
    values={}
    for line in old.decode().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key,value=line.split('=',1);parsed=shlex.split(value)
            values[key]=parsed[0] if parsed else ''
    if values.get('SMTP_PASSWORD') or values.get('RESEND_API_KEY'):
        raise RuntimeError('Existing mail configuration must be preserved')
    test={'from':'TIREBORN <'+settings['sender']+'>','to':['delivered@resend.dev'],
          'subject':'TIREBORN mail configuration check',
          'text':'Sending configuration validation. This message contains no player data.'}
    request=urllib.request.Request('https://api.resend.com/emails',data=json.dumps(test).encode(),
        headers={'Authorization':'Bearer '+settings['api_key'],'Content-Type':'application/json',
                 'User-Agent':'TIREBORN-mail-setup/1.0',
                 'Idempotency-Key':'tireborn-mail-setup-'+hashlib.sha256(settings['backup'].encode()).hexdigest()},method='POST')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    with urllib.request.build_opener(NoRedirect).open(request,timeout=15) as response:
        content=response.read(8193)
        if len(content)>8192:raise RuntimeError('Unexpected provider response')
        accepted=json.loads(content)
        if not isinstance(accepted.get('id'),str) or not accepted['id']:raise RuntimeError('Missing provider receipt')
    saved=backup/'portal-before-resend.env'
    with saved.open('xb') as output:output.write(old)
    saved.chmod(0o600)
    updates={'EMAIL_VERIFICATION_REQUIRED':'true','RESEND_API_KEY':settings['api_key'],
             'MAIL_FROM':settings['sender']}
    # This rollout enables email first. Never weaken an already configured widget.
    if not values.get('TURNSTILE_SITE_KEY') and not values.get('TURNSTILE_SECRET_KEY'):
        updates.update(TURNSTILE_REQUIRED='false',TURNSTILE_HOSTNAME='ti-reborn.com')
    lines=[line for line in old.decode().splitlines()
           if line.split('=',1)[0] not in updates or '=' not in line]
    lines.extend(key+'='+shlex.quote(value) for key,value in updates.items())
    new=('\n'.join(lines)+'\n').encode()
    temporary=environment.with_name('portal.env.resend-new')
    with temporary.open('xb') as output:output.write(new)
    info=environment.stat();os.chown(temporary,info.st_uid,info.st_gid)
    temporary.chmod(0o600);temporary.replace(environment)
    print(json.dumps({'provider_api_acceptance':'ok','provider':'Resend','transport':'HTTPS',
        'simulated_delivery_receipt':accepted['id'],
        'email_verification_required':True,'sender':settings['sender'],
        'environment_backup':str(saved),'previous_environment_sha256':hashlib.sha256(old).hexdigest(),
        'new_environment_sha256':hashlib.sha256(new).hexdigest(),
        'real_mailbox_delivery_verified':False,'service_restart_requested':False}))
except Exception as error:
    print(json.dumps({'error_type':type(error).__name__}),file=sys.stderr)
    sys.exit(1)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file',type=Path,required=True)
    parser.add_argument('--backup-report',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--sender',default='noreply@ti-reborn.com')
    args=parser.parse_args()
    if args.report.exists():parser.error('Preserve existing configuration report')
    if not re.fullmatch(r'[a-zA-Z0-9_.+-]+@ti-reborn\.com',args.sender):parser.error('Sender must use ti-reborn.com')
    api_key=args.key_file.read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r're_[a-zA-Z0-9_-]{20,}',api_key):parser.error('A full Resend API key is required')
    backup=json.loads(args.backup_report.read_text(encoding='utf-8'))
    settings={'api_key':api_key,'sender':args.sender,'backup':backup['backup'],
              'previous_release':backup['previous_portal_release']}
    command=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
             '-o','ConnectTimeout=15','root@185.184.42.88','python3 -']
    result=subprocess.run(command,input=REMOTE.replace('CONFIGURATION',repr(settings),1),
                          text=True,capture_output=True)
    if result.returncode:
        raise RuntimeError('Resend configuration failed; no credentials are included in this error')
    report=json.loads(result.stdout)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
