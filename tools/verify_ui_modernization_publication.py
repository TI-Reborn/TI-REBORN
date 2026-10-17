"""Read-only independent SSH/HTTPS verification of the reviewed .12 release.

Checks the whole manifest, reviewed Silver and optional TI, untouched resource
records and the pinned unchanged TI, live guards, prior native/code/config backup
hashes and SQLite account
identity/credential preservation. No publication, rollback, service restart or
database write function exists in the remote checker.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_ui_modernization_remote as publisher


REMOTE = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import base64,hashlib,json,os,re,sqlite3,struct,subprocess,sys,tarfile
LIVE=Path('/var/www/tio-client/updates');DOWNLOADS=Path('/var/www/tio-client/downloads')
GAME=Path('/opt/tio-emulator');PRIVATE=Path('/root');DB=Path('/var/lib/tio-server/reservation.sqlite3')
CONFIGS=(Path('/etc/tio-server/server.toml'),Path('/etc/systemd/system/tio-server.service'),
 Path('/etc/nginx/snippets/tio-updates.conf'),Path('/etc/tio-portal/portal.env'))
LAUNCHER_SHA='61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f';LAUNCHER_BYTES=118679712

def sha(raw):return hashlib.sha256(raw).hexdigest()

def regular(path):
 if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():raise ValueError('Expected regular read-only evidence file')
 return path

def directory(path):
 if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_dir():raise ValueError('Expected regular evidence directory')

def private_directory(path):
 directory(path);info=path.stat()
 if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o777!=0o700:raise RuntimeError('Hosted backup directory must be private')

def state(path):
 regular(path);value=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
 info=path.stat()
 return dict(sha256=value.hexdigest(),size=info.st_size,uid=info.st_uid,gid=info.st_gid,mode=info.st_mode&0o777)

def services():
 result={}
 for name in ('tio-server','tio-game-api','tio-portal','nginx'):
  out=subprocess.check_output(['systemctl','show',name,'-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True,timeout=30)
  result[name]=dict(line.split('=',1) for line in out.splitlines() if '=' in line)
  if result[name].get('ActiveState')!='active' or result[name].get('MainPID') in (None,'0'):raise RuntimeError('Hosted service is not active')
 return result

def code_states():
 result={}
 for name in ('server','tio','tools','config','deploy','registration'):
  folder=GAME/name
  if not folder.exists():continue
  directory(folder)
  for path in sorted(folder.rglob('*')):
   if '__pycache__' in path.parts or path.suffix=='.pyc':continue
   if path.is_file() or path.is_symlink():result[path.relative_to(GAME).as_posix()]=state(path)
 for name in ('requirements.txt','pyproject.toml'):
  if (GAME/name).exists():result[name]=state(GAME/name)
 return result

def guards():
 launchers={name:state(DOWNLOADS/name) for name in ('TIO-Launcher.exe','TIO-Launcher-0.1.4.exe')}
 if any(value!=dict(sha256=LAUNCHER_SHA,size=LAUNCHER_BYTES,uid=0,gid=0,mode=0o644) for value in launchers.values()):raise RuntimeError('Launcher identity changed')
 return dict(services=services(),launchers=launchers,configuration={str(path):state(path) for path in CONFIGS},game_code=code_states())

def database(path):
 regular(path)
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15)) as db:
  db.execute('BEGIN')
  if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('SQLite integrity failed')
  # Compare private credentials in memory only; no account names or values are
  # returned or copied locally. The actual hosted primary key is login.
  rows={tuple(row) for row in db.execute('SELECT login,salt,digest,iterations FROM accounts')}
  health=dict(integrity='ok',accounts=len(rows),checkpoints=db.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],settlement_jobs=db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0])
  return rows,health

def archive_matches(path,expected):
 with tarfile.open(regular(path),'r:gz') as archive:
  members=archive.getmembers();names=[member.name for member in members]
  if len(names)!=len(set(names)):raise RuntimeError('Duplicate backup archive member')
  for name,value in expected.items():
   if name not in names:raise RuntimeError('Backup lacks inspected code/config file')
   member=archive.getmember(name)
   if not member.isfile() or member.size!=value['size'] or member.mode&0o777!=value['mode'] or member.uid!=value['uid'] or member.gid!=value['gid']:raise RuntimeError('Backup code/config metadata differs')
   with archive.extractfile(member) as stream:
    digest=hashlib.sha256()
    for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
   if digest.hexdigest()!=value['sha256']:raise RuntimeError('Backup code/config content differs')
 return len(expected)
'''+f"\nMANIFEST_SHA={publisher.MANIFEST_SHA!r}\nPREVIOUS_VERSION={publisher.PREVIOUS_VERSION!r}\nVERSION={publisher.VERSION!r}\nSOURCES={publisher.SOURCES!r}\n"+publisher.VALIDATION+r'''

def verify(p):
 if set(p)!={'before_manifest','after_manifest','updates','receipt','inspected_guards'} or set(p['updates']) not in ({'silver.dll'},{'silver.dll','ti.exe'}):raise ValueError('Expected reviewed Silver and optional TI read-only request')
 old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
 changed=manifest_transition(old,new,p['updates']);receipt=p['receipt'];expected_guards=p['inspected_guards']
 identities={name:{'sha256':value['sha256'],'bytes':value['bytes']} for name,value in p['updates'].items()}
 if receipt.get('passed') is not True or receipt.get('operation')!='publish' or receipt.get('version')!=VERSION or receipt.get('previous_version')!=PREVIOUS_VERSION or receipt.get('manifest_sha256')!=sha(new) or receipt.get('candidates')!=identities or receipt.get('changed')!=changed or receipt.get('guards')!=expected_guards:raise RuntimeError('Publication receipt differs from independent reviewed baseline')
 preserved_records=6330-len(identities)
 if receipt.get('patch_scope',{}).get('preserved_records')!=preserved_records or receipt.get('accounts_before',0)<202 or receipt.get('accounts_in_backup',0)<202:raise RuntimeError('Receipt preservation counts differ')
 directory(LIVE);directory(LIVE/'blobs');directory(PRIVATE)
 if regular(LIVE/'manifest.json').read_bytes()!=new:raise RuntimeError('Actual hosted manifest differs from reviewed12')
 if state(LIVE/'manifest.json')!=dict(sha256=sha(new),size=len(new),uid=0,gid=0,mode=0o644):raise RuntimeError('Hosted manifest metadata differs')
 if guards()!=expected_guards:raise RuntimeError('Live launcher/code/config/services differ from inspected11 guards')
 folder=Path(receipt.get('backup',''))
 if folder.parent!=PRIVATE or not re.fullmatch('tio-before-ui-modernization-[a-zA-Z0-9_-]+',folder.name):raise ValueError('Unexpected hosted backup path')
 private_directory(folder)
 stored_receipt=json.loads(regular(folder/'publication.json').read_bytes())
 if stored_receipt!=receipt:raise RuntimeError('Local and hosted durable publication receipt differ')
 backup_receipt=json.loads(regular(folder/'backup-manifest.json').read_bytes())
 expected_files={'reservation.sqlite3','previous-manifest.json','previous-code.tar.gz','previous-config.tar.gz','before.json',*identities}
 if set(backup_receipt.get('files',{}))!=expected_files or backup_receipt.get('sqlite_integrity')!='ok' or backup_receipt.get('accounts_in_backup')!=receipt['accounts_in_backup']:raise RuntimeError('Incomplete hosted backup inventory')
 for name,value in backup_receipt['files'].items():
  if state(folder/name)!=value:raise RuntimeError('Backup file differs from its stored checksum/metadata')
 if regular(folder/'previous-manifest.json').read_bytes()!=old or json.loads(regular(folder/'before.json').read_bytes())!=expected_guards:raise RuntimeError('Backup11 manifest or guard baseline differs')
 journal=json.loads(regular(folder/'publication-journal.json').read_bytes())
 if journal!=dict(version=VERSION,candidates=identities,before_manifest_sha256=sha(old),after_manifest_sha256=sha(new),backup=str(folder),patch_scope=receipt['patch_scope']):raise RuntimeError('Hosted publication journal differs')
 native={}
 for name,value in identities.items():
  source=regular(folder/name).read_bytes();raw=regular(LIVE/'blobs'/value['sha256']).read_bytes()
  if (sha(source),len(source))!=SOURCES[name] or (sha(raw),len(raw))!=(value['sha256'],value['bytes']):raise RuntimeError('Hosted prior or current native blob differs')
  identity(name,raw,value['sha256'],value['bytes']);preserved_native(name,source,raw)
  if state(LIVE/'blobs'/value['sha256'])!=dict(sha256=value['sha256'],size=value['bytes'],uid=0,gid=0,mode=0o644):raise RuntimeError('Hosted immutable native blob metadata differs')
  native[name]=dict(changed_existing_bytes=sum(x!=y for x,y in zip(source,raw)),appended_bytes=len(raw)-len(source))
 if receipt['patch_scope']!=dict(changed=changed,preserved_records=preserved_records,native=native):raise RuntimeError('Receipt native scope differs from actual prior/current bytes')
 unchanged_native={}
 for name in set(SOURCES)-set(identities):
  source_sha,source_size=SOURCES[name];path=LIVE/'blobs'/source_sha
  if state(path)!=dict(sha256=source_sha,size=source_size,uid=0,gid=0,mode=0o644):raise RuntimeError('Pinned unchanged native blob differs')
  unchanged_native[name]=dict(sha256=source_sha,bytes=source_size)
 code_count=archive_matches(folder/'previous-code.tar.gz',expected_guards['game_code'])
 config_count=archive_matches(folder/'previous-config.tar.gz',{key.lstrip('/'):value for key,value in expected_guards['configuration'].items()})
 saved,saved_health=database(folder/'reservation.sqlite3');live,health=database(DB)
 if saved_health['accounts']!=receipt['accounts_in_backup'] or len(saved)<202 or not saved<=live:raise RuntimeError('Hosted account identity or credential disappeared since backup')
 final_guards=guards()
 if final_guards!=expected_guards or regular(LIVE/'manifest.json').read_bytes()!=new:raise RuntimeError('Hosted state changed during independent verification')
 return dict(passed=True,remote_mutations=0,version=VERSION,manifest_sha256=sha(new),candidates=identities,unchanged_native=unchanged_native,other_client_records_preserved=preserved_records,
  backup=str(folder),backup_file_checksums_verified=len(expected_files),backup_code_files_verified=code_count,backup_config_files_verified=config_count,
  backup_accounts=len(saved),accounts_after=len(live),account_identities_and_credentials_preserved=True,health=health,
  guards_unchanged=True,services_unchanged=True,launcher_preserved=True,screen11_payload_preserved=True,database_written=False,
  graphical_validation=False,verified_utc=datetime.now(timezone.utc).isoformat())

if __name__=='__main__':
 if os.geteuid()!=0:raise PermissionError('Read actual hosted state only as configured root')
 print(json.dumps(verify(json.load(sys.stdin))))
'''


def make_request(payload, receipt, inspected):
    if inspected.get('passed') is not True or inspected.get('remote_mutations') != 0 or inspected.get('manifest_sha256') != publisher.MANIFEST_SHA:
        raise ValueError('Use successful independent/inspect .11 guard evidence')
    if set(payload['updates']) not in ({'silver.dll'}, {'silver.dll', 'ti.exe'}):
        raise ValueError('Independent .12 package verification requires Silver and optional TI')
    return dict(before_manifest=payload['before_manifest'], after_manifest=payload['after_manifest'],
                updates={name:dict(sha256=value['sha256'],bytes=value['bytes'],blob='') for name,value in payload['updates'].items()},
                receipt=receipt, inspected_guards=inspected['guards'])


def invoke(request):
    result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
                             '-o', 'ConnectTimeout=15', 'root@185.184.42.88', '/usr/bin/python3 -c '+shlex.quote(REMOTE)],
                            input=json.dumps(request), text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Independent read-only SSH verification failed; private output suppressed')
    return json.loads(result.stdout)


def verify_publication(candidates, receipt_path, inspected_path):
    payload = publisher.make_payload(candidates, 'inspect')
    receipt = json.loads(Path(receipt_path).read_bytes())
    inspected = json.loads(Path(inspected_path).read_bytes())
    request = make_request(payload, receipt, inspected)
    ssh = invoke(request)
    https = verify_https(payload)
    return dict(passed=True, operation='independent_postpublication', remote_mutations=0,
                version=publisher.VERSION, ssh=ssh, https=https, graphical_validation=False,
                checker_sha256=publisher.sha(Path(__file__).read_bytes()),remote_program_sha256=publisher.sha(REMOTE.encode()))


def verify_https(payload):
    report = publisher.verify_https(payload)
    unchanged_native = {}
    for name in set(publisher.SOURCES)-set(payload['updates']):
        expected_sha, expected_size = publisher.SOURCES[name]
        raw = publisher.fetch('blobs/'+expected_sha, expected_size)
        if (publisher.sha(raw), len(raw)) != (expected_sha, expected_size):
            raise ValueError('Public pinned unchanged native blob differs')
        unchanged_native[name] = dict(sha256=expected_sha, bytes=expected_size)
    return dict(report, unchanged_native=unchanged_native,
                other_client_records_preserved=6330-len(payload['updates']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver',type=Path,required=True)
    parser.add_argument('--silver-sha256',required=True)
    parser.add_argument('--silver-bytes',type=int,required=True)
    parser.add_argument('--ti',type=Path)
    parser.add_argument('--ti-sha256')
    parser.add_argument('--ti-bytes',type=int)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--before-inspect', type=Path, default=publisher.REPORT_ROOT/'baseline/remote-inspect.json')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    if any(value is not None for value in (args.ti,args.ti_sha256,args.ti_bytes)) and not all(value is not None for value in (args.ti,args.ti_sha256,args.ti_bytes)):
        parser.error('Optional TI requires its path, exact SHA256 and size together')
    report_path = args.report.resolve()
    if args.report.is_symlink() or any(parent.is_symlink() for parent in args.report.parents) or not report_path.is_relative_to(publisher.REPORT_ROOT) or report_path.exists():
        raise ValueError('Use a new reports/ui-modernization evidence path')
    candidates = {'silver.dll':(args.silver,args.silver_sha256,args.silver_bytes)}
    if args.ti is not None:
        candidates['ti.exe']=(args.ti,args.ti_sha256,args.ti_bytes)
    report = verify_publication(candidates,args.receipt,args.before_inspect)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    with report_path.open('x',encoding='utf-8') as output:
        json.dump(report,output,indent=2);output.write('\n')
    print(json.dumps(dict(passed=True,report=str(report_path),remote_mutations=0,version=publisher.VERSION,
                         candidates=report['https']['candidates'],accounts=report['ssh']['accounts_after'])))


if __name__ == '__main__':
    main()
