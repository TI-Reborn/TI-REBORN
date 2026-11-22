"""Stage/check the two server files, then use the existing guarded deployer."""
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

WORK = ROOT/'work/player-errors-20261103'
OUT = ROOT/'reports/player-errors-20261103'
FILES = ('server/team_arena.py', 'tio/protocol/securities.py')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('validate', 'deploy'))
    args = parser.parse_args()
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    files = {}
    for name in FILES:
        before = (WORK/'baseline'/name).read_bytes()
        after = (WORK/'candidate-hosted'/name).read_bytes()
        files[name] = dict(before=sha(before), after=sha(after), raw=base64.b64encode(after).decode())
    deployer = (ROOT/'tools/deploy_game_operations_remote.py').read_text(encoding='utf-8')
    footer = "if __name__=='__main__':main()"
    assert deployer.count(footer) == 1
    deployer = deployer.replace(footer,
                                "SCOPES['city-request-fixes']=frozenset("+repr(FILES)+")\n"+footer)
    assert "SCOPES['city-request-fixes']" in deployer
    request = dict(mode=args.mode, files=files, maintenance_restart=True, deployer=deployer)
    if args.mode == 'validate':
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            archive.add(WORK/'candidate-hosted/tests', arcname='tests',
                        filter=lambda i: None if '__pycache__' in Path(i.name).parts else i)
            for name in ('animation.xml', 'items.xml'):
                archive.add(ROOT/'reports/dog-encounters/client'/name,
                            arcname='reports/dog-encounters/client/'+name)
        request.update(tests=base64.b64encode(buffer.getvalue()).decode(), modules=[
            'test_city_listing_cadence', 'test_pool_listing_performance', 'test_securities_request_denials',
            'test_shared_team_arena', 'test_team_heartbeat', 'test_battle_crash_recovery',
            'test_wager_list_removal'])
    script = TEMPLATE.replace('warehouse-counters', 'city-request-fixes').replace('20261018', '20261103')
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
