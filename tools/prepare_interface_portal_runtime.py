"""Permit the reviewed interface cache after validating a fresh site backup."""
import argparse
import json
from pathlib import Path
from tools.deploy_stage4_economy import remote
from tools.prepare_clan_portal_runtime import REMOTE as ESTABLISHED


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-report',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    if args.report.exists():parser.error('Preserve prior evidence')
    backup=json.loads(args.backup_report.read_text(encoding='utf-8'))
    if backup['sqlite_integrity']!='ok':raise ValueError('Verified complete backup required')
    code=ESTABLISHED.replace('clan-cache','interface-cache').replace(
        '.next-clan-release/cache','.next-interfaces-20261008/cache').replace(
        'tio-clan-portal-runtime','tio-interface-portal-runtime')
    marker='before={n:state(n)'
    guard="""p=json.load(__import__('sys').stdin)
backup=Path(p['backup'])
if backup.parent!=Path('/root') or not backup.name.startswith('tio-before-site-backups-'):raise ValueError('Private backup path required')
for name,expected in p['files'].items():
 if Path(name).name!=name or hashlib.sha256((backup/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('Complete backup changed')
"""
    if code.count(marker)!=1:raise ValueError('Established preparation boundary changed')
    code=code.replace(marker,guard+marker)
    result=remote(code,dict(backup=backup['backup'],files={n:r['sha256'] for n,r in backup['files'].items()}))
    with args.report.open('x',encoding='utf-8') as output:json.dump(result,output,indent=2)
    print(json.dumps(result))


if __name__=='__main__':main()
