"""Explicit operator entry point for the reviewed, temporary hosted QA lease."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from tools.deploy_stage4_economy import remote

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/shared-mines'
REMOTE=r'''
from pathlib import Path
import base64,hashlib,json,os,runpy,sys
os.umask(0o077);p=json.load(sys.stdin)
sys.path.insert(0,'/opt/tio-emulator')
def sha(b):return hashlib.sha256(b).hexdigest()
if p['action']=='activate':
 raw=base64.b64decode(p['source'],validate=True)
 assert sha(raw)==p['source_sha256']
 bootstrap=Path('/root/tio-shared-mines-qa-bootstrap-'+sha(raw)[:16]+'.py')
 if bootstrap.exists():assert not bootstrap.is_symlink() and bootstrap.read_bytes()==raw
 else:
  with bootstrap.open('xb') as out:out.write(raw)
  bootstrap.chmod(0o600)
 namespace=runpy.run_path(str(bootstrap))
 result=namespace['Maintenance']().activate(p['accounts'],39512,39513)
else:
 proof=p['proof'];path=Path(proof['helper_path'])
 assert path.parent.parent==Path('/root/tio-shared-mines-qa') and path.name=='maintenance.py'
 assert not path.is_symlink() and sha(path.read_bytes())==proof['helper_sha256']
 namespace=runpy.run_path(str(path))
 if p['action']=='finish':result=namespace['finish_maintenance'](proof)
 elif p['action']=='watchdog':result=namespace['finish_maintenance'](proof,watchdog=True)
 elif p['action']=='verify':result=namespace['verify_gate'](proof)
 else:raise ValueError('Unknown maintenance action')
print(json.dumps(result))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('activate','verify','finish','watchdog'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--proof',type=Path,default=FOLDER/'maintenance-proof.json')
    parser.add_argument('--prepare-proof',type=Path,default=FOLDER/'owned-prepare.json')
    args=parser.parse_args();target=args.output.resolve()
    if target.parent!=FOLDER or target.exists():parser.error('Preserve evidence; use a fresh report filename')
    payload=dict(action=args.action)
    if args.action=='activate':
        preparation=args.prepare_proof.resolve()
        if args.prepare_proof.is_symlink() or not preparation.is_relative_to(FOLDER):
            parser.error('Use a public preparation report within reports/shared-mines')
        prepared=json.loads(preparation.read_text(encoding='utf-8'))
        assert prepared['prepared_local_only'] and prepared['passed']
        # Ports are fixed loopback-only SSH forwards, never a public listener.
        import socket
        for port in (39512,39513):
            with socket.socket() as probe:probe.bind(('127.0.0.1',port))
        raw=(ROOT/'tools/shared_mines_maintenance.py').read_bytes()
        payload.update(accounts=prepared['accounts'],source=base64.b64encode(raw).decode('ascii'),
                       source_sha256=hashlib.sha256(raw).hexdigest())
    else:payload['proof']=json.loads(args.proof.read_text(encoding='utf-8'))
    report=remote(REMOTE,payload)
    with target.open('x',encoding='utf-8') as out:out.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(action=args.action,report=str(target),status=report.get('status'),
        deadline_utc=report.get('deadline_utc'),only_owned_gate_removed=report.get('only_owned_gate_removed'))))

if __name__=='__main__':main()
