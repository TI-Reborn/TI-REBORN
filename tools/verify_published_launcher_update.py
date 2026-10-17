"""Read-only trusted HTTPS and hosted-state verification of a launcher release.

Streams executable bytes into SHA256 without saving downloads. Creates one new
local evidence report. SSH runs only SELECTs, SQLite integrity checks, file reads
and systemctl show; never alters services, player data or remote files.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import ssl
import subprocess
import urllib.parse
import urllib.request

ORIGIN='https://ti-reborn.com'
LEGACY_ORIGIN='https://185.184.42.88'
MAX_BINARY=200*1024*1024
MAX_TEXT=3*1024*1024


def origin(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('Only ordinary HTTPS origins are permitted')
    return parsed.scheme,parsed.hostname,parsed.port or 443


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,file_pointer,code,message,headers,new_url):
        if origin(request.full_url)!=origin(new_url):raise ValueError('HTTPS redirect outside the requested origin')
        return super().redirect_request(request,file_pointer,code,message,headers,new_url)


def fetch(url,binary=False):
    expected_origin=origin(url)
    context=ssl.create_default_context();context.keylog_filename=None
    opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),SameOriginRedirect())
    request=urllib.request.Request(url,headers={'Cache-Control':'no-cache','Pragma':'no-cache',
                                              'User-Agent':'TIO-launcher-self-update-verification'})
    with opener.open(request,timeout=120) as response:
        if response.status!=200 or origin(response.url)!=expected_origin:
            raise ValueError('Expected a successful same-origin HTTPS response')
        digest=hashlib.sha256();count=0;chunks=[]
        for chunk in iter(lambda:response.read(1024*1024),b''):
            count+=len(chunk)
            if count>(MAX_BINARY if binary else MAX_TEXT):raise ValueError('Public response exceeds its size bound')
            digest.update(chunk)
            if not binary:chunks.append(chunk)
        return {'status':response.status,'url':response.url,'bytes':count,'sha256':digest.hexdigest(),
                'content_type':response.headers.get('Content-Type'),'cache_control':response.headers.get('Cache-Control')},b''.join(chunks)


def validate_package(package):
    if not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)',package.get('version','')):
        raise ValueError('Expected a numeric launcher version')
    if not re.fullmatch('[0-9a-f]{64}',package.get('sha256','')):
        raise ValueError('Expected the reviewed SHA256')
    if type(package.get('size')) is not int or not 1024*1024<=package['size']<=MAX_BINARY:
        raise ValueError('Expected a bounded executable size')
    return {'schema':1,'version':package['version'],'sha256':package['sha256'],'size':package['size']}


REMOTE_READ_ONLY=r'''
from contextlib import closing
from pathlib import Path
import hashlib,importlib.util,json,sqlite3,subprocess
def file_state(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Unexpected verification file')
    info=path.stat()
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'sha256':digest,'bytes':info.st_size,'mode':info.st_mode&0o777,'uid':info.st_uid,'gid':info.st_gid}
def service(name):
    output=subprocess.check_output(['/usr/bin/systemctl','show',name,'-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
    return dict(line.split('=',1) for line in output.splitlines() if '=' in line)
spec=importlib.util.spec_from_file_location('portal_backup','/opt/tio-portal/portal_backup.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
query='SELECT jsonb_build_object(\'row\',(SELECT to_jsonb(d) FROM "DownloadVersion" d WHERE id=\'main\'),\'download_rows\',(SELECT count(*) FROM "DownloadVersion"),\'web_users\',(SELECT count(*) FROM "User"))'
metadata=checker._command(['psql','-X','--no-psqlrc','--no-align','--tuples-only','--set=ON_ERROR_STOP=1','--dbname=tionline_web','--command='+query],
                         'read-only publication verification',runner=subprocess.run,stdout=subprocess.PIPE)
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as database:
    integrity=database.execute('PRAGMA integrity_check').fetchall()
    account_count=database.execute('SELECT count(*) FROM accounts').fetchone()[0]
manifest=Path('/var/www/tio-client/updates/manifest.json')
print(json.dumps({'client_manifest':file_state(manifest),'client_version':json.loads(manifest.read_text())['version'],
                 'launcher':file_state('/var/www/tio-client/downloads/TIO-Launcher.exe'),
                 'services':{name:service(name) for name in ('tio-server','tio-game-api','tio-portal')},
                 'configuration':{name:file_state(name) for name in ('/etc/tio-server/server.toml','/etc/tio-portal/portal.env','/etc/nginx/snippets/tio-updates.conf')},
                 'portal_release':str(Path('/opt/tio-portal/current').resolve(strict=True)),
                 'metadata':json.loads(metadata.stdout),'sqlite_integrity':'ok' if integrity==[('ok',)] else 'failed',
                 'game_accounts':account_count,'remote_mutations':0,'service_restarts':0}))
'''


def remote_checks():
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',
                           'root@185.184.42.88','/usr/bin/python3 -'],input=REMOTE_READ_ONLY,text=True,capture_output=True,timeout=90)
    if result.returncode:raise RuntimeError('Read-only SSH verification failed; private output suppressed')
    return json.loads(result.stdout)


def verify(package,backup):
    expected=validate_package(package);version=expected['version'];versioned='/downloads/TIO-Launcher-'+version+'.exe'
    baseline=backup['publication_baseline'];checks={};downloads={};self_manifests={};pages={}
    cache_key=expected['sha256'][:12]+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    for path in (versioned,'/downloads/TIO-Launcher.exe?verify='+cache_key):
        record,_=fetch(ORIGIN+path,binary=True)
        record['matches_reviewed_candidate']=record['sha256']==expected['sha256'] and record['bytes']==expected['size']
        checks['download:'+path]=record['matches_reviewed_candidate'];downloads[path]=record
    for site in (LEGACY_ORIGIN,ORIGIN):
        record,raw=fetch(site+'/downloads/launcher-manifest.json?verify='+cache_key)
        value=json.loads(raw);record['manifest']=value;record['matches_reviewed_manifest']=value==expected
        checks['self_manifest:'+site]=record['matches_reviewed_manifest'];self_manifests[site]=record
    metadata_response,raw=fetch(ORIGIN+'/api/client/version?verify='+cache_key)
    metadata=json.loads(raw)
    checks['public_metadata']=(metadata.get('launcherVersion')==version and metadata.get('launcherUrl')==versioned
                               and metadata.get('fileSizeBytes')==expected['size'])
    checks['public_game_metadata_preserved']=metadata.get('gameVersion')==baseline['metadata']['row']['gameVersion']
    for locale in ('ru','en'):
        record,raw=fetch(ORIGIN+'/'+locale+'/download?verify='+cache_key);html=raw.decode('utf-8')
        record.update({'current_version_visible':version in html,'versioned_download_visible':versioned in html,
                       'self_update_copy_visible':('automatically' in html.lower() if locale=='en' else 'автоматически' in html.lower()),
                       'version_014_still_visible':'0.1.4' in html})
        checks['download_page:'+locale]=record['current_version_visible'] and record['versioned_download_visible']
        # Static guide deployment is separate from the dynamic launcher metadata.
        record['static_instruction_status']='current' if record['self_update_copy_visible'] else 'stale_previous_release'
        pages[locale]=record
    client_response,raw=fetch(ORIGIN+'/updates/manifest.json?verify='+cache_key)
    client_version=json.loads(raw)['version']
    checks['public_client_manifest_preserved']=(client_response['sha256']==baseline['client_manifest']['sha256']
                                               and client_response['bytes']==baseline['client_manifest']['bytes']
                                               and client_version==baseline['client_version'])
    remote=remote_checks()
    checks['remote_launcher']=(remote['launcher']['sha256']==expected['sha256'] and remote['launcher']['bytes']==expected['size'])
    checks['remote_client_manifest_preserved']=remote['client_manifest']==baseline['client_manifest'] and remote['client_version']==baseline['client_version']
    checks['services_same_processes']=remote['services']==baseline['services'] and all(s['ActiveState']=='active' for s in remote['services'].values())
    checks['configuration_preserved']=remote['configuration']==baseline['configuration']
    checks['portal_release_preserved']=remote['portal_release']==baseline['portal_release']
    checks['sqlite_integrity']=remote['sqlite_integrity']=='ok'
    expected_accounts=backup['game_table_fingerprints']['accounts']['rows']
    checks['game_account_count_preserved']=remote['game_accounts']==expected_accounts
    checks['web_account_count_preserved']=remote['metadata']['web_users']==baseline['metadata']['web_users']
    checks['download_row_count_preserved']=remote['metadata']['download_rows']==baseline['metadata']['download_rows']
    checks['remote_launcher_metadata']=(remote['metadata']['row']['launcherVersion']==version
                                       and remote['metadata']['row']['launcherUrl']==versioned
                                       and remote['metadata']['row']['fileSizeBytes']==expected['size'])
    remote['expected_game_accounts']=expected_accounts
    return {'status':'passed' if all(checks.values()) else 'failed','verified_utc':datetime.now(timezone.utc).isoformat(),
            'trusted_https':True,'same_origin_redirects_only':True,'tls_key_logging':False,'downloaded_executables_saved':False,
            'expected':expected,'checks':checks,'downloads':downloads,'self_update_manifests':self_manifests,
            'public_metadata':metadata,'metadata_response':metadata_response,'download_pages':pages,
            'static_instruction_limitations':[locale for locale,page in pages.items() if page['static_instruction_status']!='current'],
            'public_client_manifest':{**client_response,'version':client_version},'hosted_state':remote,
            'real_game_client_validation':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.report.exists() or args.report.is_symlink():raise FileExistsError('Refusing to replace verification evidence')
    package=json.loads(args.package.read_text(encoding='utf-8'))
    backup=json.loads((args.package.parent/'preupdate-backup.json').read_text(encoding='utf-8'))
    if package.get('backup')!=backup.get('backup'):raise ValueError('Package and backup differ')
    report=verify(package,backup)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as output:output.write(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':report['status'],'report':str(args.report.resolve()),'checks':report['checks'],
                      'static_instruction_limitations':report['static_instruction_limitations'],
                      'game_accounts':report['hosted_state']['game_accounts'],'services':report['hosted_state']['services']}))
    if report['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
