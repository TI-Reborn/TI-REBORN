"""Validate exact hosted sources and deploy one shared personal warehouse."""
import argparse
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.deploy_warehouse_counters_20261018 import REMOTE as TEMPLATE

OUT=ROOT/'reports/shared-warehouse-20261023'
BASELINE=ROOT/'work/shared-warehouse-20261023/baseline'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15','root@185.184.42.88','python3 -']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('validate','deploy'))
    parser.add_argument('--maintenance-restart',action='store_true')
    args=parser.parse_args()
    names=('tio/warehouse_completion.py','tio/warehouse_resources.py')
    sha=lambda b:hashlib.sha256(b).hexdigest()
    checked=json.loads((OUT/'hosted-before.json').read_text())['hashes']
    files={}
    for name in names:
        before=(BASELINE/name).read_bytes();after=(ROOT/name).read_bytes()
        assert sha(before)==checked[name]
        files[name]=dict(before=sha(before),after=sha(after),raw=base64.b64encode(after).decode())
    request=dict(mode=args.mode,maintenance_restart=args.maintenance_restart,files=files,
        deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text())
    if args.mode=='validate':
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
            archive.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
        modules=['test_shared_warehouse','test_mine_warehouses','test_warehouse_resources','test_warehouse_transfer',
                 'test_repair_from_warehouse','test_repair_warehouse_regression']
        # These two older tests require an obsolete rental currency and a
        # research-only replay helper absent from the deployed runtime.
        excluded={'test_rental_remote_expiry_preserves_city_rows_and_emits_only_visible_snapshot',
                  'test_encrypted_dispatch_routes_every_recovered_request'}
        for name in ('test_warehouse_completion','test_warehouse_queries'):
            tree=ast.parse((ROOT/'tests'/f'{name}.py').read_text(encoding='utf-8'))
            for cls in tree.body:
                if isinstance(cls,ast.ClassDef):
                    modules.extend(f'{name}.{cls.name}.{f.name}' for f in cls.body
                        if isinstance(f,ast.FunctionDef) and f.name.startswith('test_') and f.name not in excluded)
        request.update(tests=base64.b64encode(buffer.getvalue()).decode(),modules=modules)
    script=TEMPLATE.replace('warehouse-counters','shared-warehouse').replace('20261018','20261023')
    # The service user cannot consume the ext4 root reserve.
    script=script.replace("root=Path('/opt/tio-emulator');", "assert os.statvfs('/').f_bavail*os.statvfs('/').f_frsize>4*1024**3, 'Insufficient disk headroom'\nroot=Path('/opt/tio-emulator');")
    result=subprocess.run(SSH,input='request='+repr(request)+'\n'+script,capture_output=True,text=True,encoding='utf-8',timeout=420)
    if result.returncode:
        (OUT/(args.mode+'-error.log')).write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        raise RuntimeError(result.stderr[-2500:])
    report=json.loads(result.stdout)
    (OUT/('remote-checks.json' if args.mode=='validate' else 'deployment.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not report.get('passed'):raise RuntimeError('Remote validation failed')


if __name__=='__main__':main()
