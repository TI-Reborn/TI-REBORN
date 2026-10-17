"""Independent read-only SSH/HTTPS verification of a reviewed HD UI package.

Verifies the exact full manifest, immutable resources, preserved TI/launcher,
unchanged code/config/services, durable backup inventories and SQLite account
identity/credential preservation. Never publishes or restores hosted state.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import publish_ui_hd_assets_remote as publisher
from tools.verify_ui_modernization_publication import REMOTE as PREVIOUS_READ_ONLY
from tools.publish_ui_modernization_remote import VALIDATION as PREVIOUS_VALIDATION

REMOTE = PREVIOUS_READ_ONLY.split('\nMANIFEST_SHA=')[0] + '\nfrom pathlib import PurePosixPath\nimport struct,zlib\nfrom xml.etree import ElementTree\n' + (
    f'MANIFEST_SHA={publisher.MANIFEST_SHA!r}\nPREVIOUS_VERSION={publisher.PREVIOUS_VERSION!r}\nVERSION={publisher.VERSION!r}\nBASELINE_RECORDS={publisher.BASELINE_RECORDS}\n'
    f'SILVER_SHA={publisher.SILVER_SHA!r}\nSILVER_BYTES={publisher.SILVER_BYTES}\nTI_SHA={publisher.TI_SHA!r}\nTI_BYTES={publisher.TI_BYTES}\nAUTH_SPANS={publisher.AUTH_SPANS!r}\n'
) + PREVIOUS_VALIDATION.split('def preserved_native')[0] + publisher.VALIDATION + r'''

def verify(p):
 if set(p)!={'package_blob','package_sha256','before_manifest','after_manifest','receipt','inspected_guards'}:raise ValueError('Unknown read-only package verification request')
 package=package_identity(base64.b64decode(p['package_blob'],validate=True),p['package_sha256'])
 old=base64.b64decode(p['before_manifest'],validate=True);new=base64.b64decode(p['after_manifest'],validate=True)
 scope=manifest_transition(old,new,package);receipt=p['receipt'];expected_guards=p['inspected_guards']
 identities={item['path']:dict(sha256=item['sha256'],size=item['size'],kind=item['kind']) for item in package['files']}
 if receipt.get('passed') is not True or receipt.get('operation')!='publish' or receipt.get('version')!=VERSION or receipt.get('previous_version')!=PREVIOUS_VERSION or receipt.get('package_sha256')!=p['package_sha256'] or receipt.get('manifest_sha256')!=sha(new) or receipt.get('candidates')!=identities or receipt.get('guards')!=expected_guards:raise RuntimeError('Receipt differs from independently reviewed package/baseline')
 if receipt.get('changed')!=scope['changed'] or receipt.get('added')!=scope['added'] or receipt.get('accounts_before',0)<202 or receipt.get('accounts_in_backup',0)<202:raise RuntimeError('Receipt scope/account baseline differs')
 directory(LIVE);directory(LIVE/'blobs');directory(PRIVATE)
 if regular(LIVE/'manifest.json').read_bytes()!=new or state(LIVE/'manifest.json')!=dict(sha256=sha(new),size=len(new),uid=0,gid=0,mode=0o644):raise RuntimeError('Actual hosted full manifest differs')
 if guards()!=expected_guards:raise RuntimeError('Actual launcher/code/config/services differ from final inspected guards')
 folder=Path(receipt.get('backup',''))
 if folder.parent!=PRIVATE or not re.fullmatch('tio-before-ui-hd-assets-[a-zA-Z0-9_-]+',folder.name):raise ValueError('Unexpected hosted private backup path')
 private_directory(folder);private_directory(folder/'previous-blobs')
 if json.loads(regular(folder/'publication.json').read_bytes())!=receipt:raise RuntimeError('Local and hosted durable publication receipt differ')
 backup_receipt=json.loads(regular(folder/'backup-manifest.json').read_bytes())
 lookup={x['path']:x for x in json.loads(old)['files']}
 prior_blobs={lookup[name]['sha256'] for name in identities if name in lookup}
 expected_files={'reservation.sqlite3','previous-manifest.json','previous-code.tar.gz','previous-config.tar.gz','before.json',*('previous-blobs/'+h for h in prior_blobs)}
 if set(backup_receipt.get('files',{}))!=expected_files or backup_receipt.get('sqlite_integrity')!='ok' or backup_receipt.get('accounts_in_backup')!=receipt['accounts_in_backup']:raise RuntimeError('Incomplete private backup inventory')
 for name,value in backup_receipt['files'].items():
  if state(folder/name)!=value or value.get('uid')!=0 or value.get('gid')!=0 or value.get('mode')!=0o600:raise RuntimeError('Private backup content/metadata differs')
 if regular(folder/'previous-manifest.json').read_bytes()!=old or json.loads(regular(folder/'before.json').read_bytes())!=expected_guards:raise RuntimeError('Backup manifest/guard baseline differs')
 expected_journal=dict(version=VERSION,package_sha256=p['package_sha256'],candidates=identities,before_manifest_sha256=sha(old),after_manifest_sha256=sha(new),backup=str(folder),patch_scope=receipt.get('patch_scope'))
 if json.loads(regular(folder/'publication-journal.json').read_bytes())!=expected_journal:raise RuntimeError('Durable publication journal differs')
 details={}
 for item in package['files']:
  name=item['path'];raw=regular(LIVE/'blobs'/item['sha256']).read_bytes();source=None
  if name in lookup:
   previous=lookup[name];source=regular(folder/'previous-blobs'/previous['sha256']).read_bytes()
   if (sha(source),len(source))!=(previous['sha256'],previous['size']):raise RuntimeError('Previous reviewed resource backup differs')
  details[name]=blob_identity(item,raw,source if item['kind']=='native' else None)
  if state(LIVE/'blobs'/item['sha256'])!=dict(sha256=item['sha256'],size=item['size'],uid=0,gid=0,mode=0o644):raise RuntimeError('Published immutable resource metadata differs')
 scope['resources']=details
 if receipt.get('patch_scope')!=scope:raise RuntimeError('Receipt resource geometry/native deltas differ')
 if state(LIVE/'blobs'/TI_SHA)!=dict(sha256=TI_SHA,size=TI_BYTES,uid=0,gid=0,mode=0o644):raise RuntimeError('Pinned unchanged TI blob differs')
 code_count=archive_matches(folder/'previous-code.tar.gz',expected_guards['game_code'])
 config_count=archive_matches(folder/'previous-config.tar.gz',{key.lstrip('/'):value for key,value in expected_guards['configuration'].items()})
 saved,saved_health=database(folder/'reservation.sqlite3');live,health=database(DB)
 if saved_health['accounts']!=receipt['accounts_in_backup'] or len(saved)<202 or not saved<=live:raise RuntimeError('Hosted account identity/credentials disappeared since backup')
 if guards()!=expected_guards or regular(LIVE/'manifest.json').read_bytes()!=new:raise RuntimeError('Hosted guards/manifest changed during independent verification')
 return dict(passed=True,remote_mutations=0,version=VERSION,package_sha256=p['package_sha256'],manifest_sha256=sha(new),candidates=identities,
  changed=scope['changed'],added=scope['added'],preserved_records=scope['preserved_records'],before_records=scope['before_records'],after_records=scope['after_records'],
  backup=str(folder),backup_file_checksums_verified=len(expected_files),backup_code_files_verified=code_count,backup_config_files_verified=config_count,
  backup_accounts=len(saved),accounts_after=len(live),account_identities_and_credentials_preserved=True,health=health,
  guards_unchanged=True,services_unchanged=True,ti_preserved=True,launcher_preserved=True,screen11_payload_preserved=True,database_written=False,
  graphical_validation=False,verified_utc=datetime.now(timezone.utc).isoformat())

if __name__=='__main__':
 if os.geteuid()!=0:raise PermissionError('Read actual hosted state only as configured root')
 print(json.dumps(verify(json.load(sys.stdin))))
'''


def make_request(payload,receipt,inspected):
    if inspected.get('passed') is not True or inspected.get('operation')!='inspect' or inspected.get('remote_mutations')!=0 or inspected.get('package_sha256')!=payload['package_sha256'] or inspected.get('manifest_sha256')!=publisher.MANIFEST_SHA:
        raise ValueError('Use successful exact package/baseline inspect evidence')
    return dict(package_blob=payload['package_blob'],package_sha256=payload['package_sha256'],before_manifest=payload['before_manifest'],
                after_manifest=payload['after_manifest'],receipt=receipt,inspected_guards=inspected['guards'])


def invoke(request):
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',
                           'root@185.184.42.88','/usr/bin/python3 -c '+shlex.quote(REMOTE)],input=json.dumps(request),
                          text=True,capture_output=True,timeout=240)
    if result.returncode:raise RuntimeError('Independent read-only SSH verification failed; private output suppressed')
    return json.loads(result.stdout)


def verify_publication(package,package_sha,receipt_path,inspected_path):
    payload=publisher.make_payload(package,package_sha,'inspect')
    receipt=json.loads(Path(receipt_path).read_bytes());inspected=json.loads(Path(inspected_path).read_bytes())
    ssh=invoke(make_request(payload,receipt,inspected));https=publisher.verify_https(payload)
    return dict(passed=True,operation='independent_postpublication',remote_mutations=0,version=publisher.VERSION,
                package_sha256=package_sha,ssh=ssh,https=https,graphical_validation=False,
                checker_sha256=publisher.sha(Path(__file__).read_bytes()),remote_program_sha256=publisher.sha(REMOTE.encode()))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--package-sha256',required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--before-inspect',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv);path=args.report.resolve()
    if not publisher.no_symlinks(args.report) or not path.is_relative_to(publisher.DEPLOYMENT.resolve()) or path.exists():
        raise ValueError('Use a new reports/ui-hd-assets/deployment evidence path')
    result=verify_publication(args.package,args.package_sha256,args.receipt,args.before_inspect)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as output:json.dump(result,output,indent=2);output.write('\n')
    print(json.dumps(dict(passed=True,report=str(path),remote_mutations=0,version=publisher.VERSION,accounts=result['ssh']['accounts_after'])))


if __name__=='__main__':
    main()
