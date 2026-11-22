"""Validate the scoped feedback fixes and deploy without replacing saves."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.deploy_warehouse_counters_20261018 import REMOTE as TEMPLATE

WORK = ROOT/'work/player-feedback-20261104'
OUT = ROOT/'reports/player-feedback-20261104'
SCOPE = 'player-feedback-fixes'
BASELINE = 'baseline'
DEPLOY_BUFFER_BYTES = 80 * 1024**2
MODULES = ['test_player_feedback_20261104', 'test_battle_exchange',
           'test_avatars', 'test_shared_mining_state', 'test_warehouse_transfer']
FILES = ('server/team_arena.py', 'tio/arena_service.py', 'tio/battle_loot.py',
         'tio/protocol/battle_exchange.py', 'tio/protocol/battle_loot.py',
         'tio/protocol/city_item_transfer.py', 'tools/mining_scene.py',
         'tools/survival_scene.py', 'tools/loopback_exchange.py')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('validate', 'deploy'))
    parser.add_argument('--maintenance-restart', action='store_true')
    args = parser.parse_args()
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    files = {}
    for name in FILES:
        before = (WORK/BASELINE/name).read_bytes()
        after = (WORK/'candidate'/name).read_bytes()
        files[name] = dict(before=sha(before), after=sha(after), raw=base64.b64encode(after).decode())
    deployer = (ROOT/'tools/deploy_game_operations_remote.py').read_text(encoding='utf-8')
    disk_guard = f"""
    disk=os.statvfs('/')
    required=4*1024**3+{DEPLOY_BUFFER_BYTES}
    if disk.f_bavail*disk.f_frsize < required:
        raise RuntimeError('Insufficient ordinary-service disk headroom for staging and backups')
"""
    assert deployer.count('    stage.mkdir(mode=0o755)') == 1
    deployer = deployer.replace('    stage.mkdir(mode=0o755)',
                                disk_guard+'    stage.mkdir(mode=0o755)')
    footer = "if __name__=='__main__':main()"
    assert deployer.count(footer) == 1
    deployer = deployer.replace(footer,
                                'SCOPES['+repr(SCOPE)+']=frozenset('+repr(FILES)+')\n'+footer)
    assert 'SCOPES['+repr(SCOPE)+']' in deployer
    request = dict(mode=args.mode, files=files,
                   maintenance_restart=args.maintenance_restart, deployer=deployer)
    if args.mode == 'validate':
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            archive.add(WORK/'candidate/tests', arcname='tests',
                        filter=lambda i: None if '__pycache__' in Path(i.name).parts else i)
            for name in ('animation.xml', 'items.xml'):
                archive.add(ROOT/'reports/dog-encounters/client'/name,
                            arcname='reports/dog-encounters/client/'+name)
        request.update(tests=base64.b64encode(buffer.getvalue()).decode(), modules=MODULES)
    script = TEMPLATE.replace('warehouse-counters', SCOPE).replace('20261018', '20261104')
    result = subprocess.run(['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
                             '-o', 'ConnectTimeout=15', 'root@185.184.42.88', 'python3 -'],
                            input='request='+repr(request)+'\n'+script,
                            capture_output=True, encoding='utf-8', timeout=420)
    (OUT/(args.mode+'-server-diagnostics.txt')).write_text(result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Guarded server operation deferred/failed; see diagnostics')
    report = json.loads(result.stdout)
    (OUT/('server-'+args.mode+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'log'}))
    if not report.get('passed'):
        raise RuntimeError('Isolated hosted validation failed')


if __name__ == '__main__':
    main()
