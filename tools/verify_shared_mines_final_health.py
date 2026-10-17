"""Read-only final hosted service, source and maintenance-cleanup verification."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import ssl
from tools.deploy_stage4_economy import remote

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/shared-mines'
REMOTE = r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys
p=json.load(sys.stdin)
def run(*args):
 return subprocess.run(args,text=True,capture_output=True,check=True,timeout=30).stdout.strip()
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
root=Path('/opt/tio-emulator')
hashes={name:digest(root/name) for name in p['files']}
if hashes!=p['files']:raise ValueError('Deployed runtime source parity failed')
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 db.execute('BEGIN')
 if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('Database integrity failed')
 pending={n:db.execute('SELECT COUNT(*) FROM '+n).fetchone()[0] for n in ('battle_checkpoints','battle_settlement_jobs')}
 if any(pending.values()):raise ValueError('Pending battle state remains')
 claims=[dict(location=r[0],owner_clan=r[1],tax_percent=r[2],revision=r[3]) for r in db.execute('SELECT location,owner_clan,tax_percent,revision FROM mine_claims ORDER BY location')]
 if any(c['owner_clan'] is not None or c['tax_percent'] for c in claims):raise ValueError('Temporary QA ownership remains')
 accounts=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
 wallets=db.execute('SELECT COUNT(*) FROM wallets').fetchone()[0]
rules=json.loads(run('nft','-j','list','ruleset'))
gates=[e['table']['name'] for e in rules['nftables'] if e.get('table',{}).get('name','').startswith('tio_mines_qa_')]
dropins=list(Path('/etc/systemd/system/tio-server.service.d').glob('90-qa-*.conf'))
timer=run('systemctl','show','tio-mines-qa-'+p['lease_id']+'.timer','-p','ActiveState','--value')
if gates or dropins or timer=='active':raise ValueError('Maintenance artifacts remain active')
services={}
for unit in ('tio-server','tio-game-api','tio-portal'):
 values=dict(line.split('=',1) for line in run('systemctl','show',unit,'-p','ActiveState','-p','MainPID','-p','NRestarts','-p','ExecMainStatus').splitlines())
 if values['ActiveState']!='active' or values['ExecMainStatus']!='0':raise ValueError('Hosted service unhealthy')
 services[unit]=values
guards={name:digest(Path(name)) for name in p['guards']}
if guards!=p['guards']:raise ValueError('Unrelated hosted config or client artifact changed')
listeners=run('ss','-Hltn','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
if any(':'+str(port) not in listeners for port in (28512,28513,29512,29513)):raise ValueError('Game listener missing')
print(json.dumps(dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),passed=True,integrity='ok',
 accounts=accounts,wallets=wallets,pending=pending,claims=claims,services=services,
 source_sha256=hashes,source_parity=True,guards_unchanged=True,
 active_qa_gates=0,qa_boot_dropins=0,qa_timer_state=timer,game_listeners=4)))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment',type=Path,default=FOLDER/'deployment.json')
    parser.add_argument('--release-proof',type=Path,default=FOLDER/'maintenance-release.json')
    parser.add_argument('--proof',type=Path,default=FOLDER/'maintenance-proof.json')
    parser.add_argument('--output',type=Path,default=FOLDER/'final-health.json')
    args=parser.parse_args()
    paths=(args.output,args.deployment,args.release_proof,args.proof)
    if any(p.is_symlink() or p.resolve().parent!=FOLDER for p in paths):
        raise ValueError('Use direct public reports within reports/shared-mines')
    target=args.output.resolve()
    if target.exists():raise ValueError('Preserve previous health evidence')
    deployed=json.loads(args.deployment.read_text(encoding='utf-8'))
    baseline=json.loads((FOLDER/'remote-baseline.json').read_text(encoding='utf-8'))
    proof=json.loads(args.proof.read_text(encoding='utf-8'))
    released=json.loads(args.release_proof.read_text(encoding='utf-8'))
    if released['status']!='released' or not released['only_owned_gate_removed']:
        raise ValueError('Maintenance release must be verified first')
    hashes=deployed['source_sha256']
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest for name,digest in hashes.items()):
        raise ValueError('Local deployed source changed')
    report=remote(REMOTE,dict(files=hashes,guards=baseline['guards'],lease_id=proof['lease_id']))
    # These are public connections after isolation is removed, with strict SNI.
    context=ssl.create_default_context()
    context.keylog_filename=None
    tls=[]
    for port in (29512,29513):
        with socket.create_connection(('185.184.42.88',port),timeout=10) as sock:
            with context.wrap_socket(sock,server_hostname='ti-reborn.com') as secured:
                tls.append(dict(port=port,version=secured.version(),certificate_verified=True))
    report.update(public_tls=tls,graphical_clients_verified=False)
    with target.open('x',encoding='utf-8') as out:out.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],accounts=report['accounts'],pending=report['pending'],
        public_tls=len(tls),source_parity=report['source_parity'],report=str(target))))


if __name__=='__main__':main()
