"""Independently verify a DPAPI copy and reviewed launcher/portal identities.

Decrypts only in memory; outputs hashes/counts, never private archived content.
No remote connection, plaintext export, database server or restore is started.
"""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import offsite_backup_windows as backup

EXPECTED='61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f'
EXPECTED_BYTES=118679712
MANIFEST='2966cadc3eff333f46d944145d7a398ab5e55a4894a2ded59fd31bf86dea25d2'


def verify(path,build_sha256):
    path=Path(path);raw=backup._read_encrypted(path)
    payload=backup.crypt(raw[len(backup.MAGIC):],decrypt=True)
    result=backup.verify_payload(payload)
    files,selected=backup._archive(payload)
    checked={}
    for name in ('client/downloads/TIO-Launcher.exe','client/downloads/TIO-Launcher-0.1.4.exe'):
        if files.get(name)!={'sha256':EXPECTED,'size':EXPECTED_BYTES}:
            raise ValueError('Recovery launcher differs from reviewed 0.1.4')
        checked[name]=files[name]
    if files['client/updates/manifest.json']['sha256']!=MANIFEST:
        raise ValueError('Recovery client manifest changed')
    build=files.get('portal/.next/BUILD_ID')
    if not build or build['sha256']!=build_sha256:
        raise ValueError('Recovery portal build differs from reviewed release8')
    return {**result,'path':str(path.resolve()),'encrypted_bytes':len(raw),'status':'verified',
            'verified_utc':datetime.now(timezone.utc).isoformat(),'plaintext_written':False,
            'launcher_version':'0.1.4','launcher_files':checked,'client_manifest_sha256':MANIFEST,
            'portal_build_id_sha256':build_sha256,'portal_release':'tireborn-20261007-8-launcher014',
            'archived_created_utc':json.loads(selected['manifest.json'])['created']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--verify',type=Path,required=True)
    parser.add_argument('--portal-build-sha256',required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists() or args.report.is_symlink():raise FileExistsError('Refusing to replace existing evidence')
    data=verify(args.verify,args.portal_build_sha256)
    with args.report.open('x',encoding='utf-8') as output:output.write(json.dumps(data,indent=2)+'\n')
    print(json.dumps(data))
