"""Check scoped market refactor over the captured current hosted runtime."""
from pathlib import Path
import argparse,hashlib,json,shutil,sys,unittest

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/trade-operations-20261015'
REPORT=ROOT/'reports/trade-operations-20261015'
FILES=('server/market_operations.py','server/player_trade.py','server/player_auction.py',
       'server/private_market.py','tio/player_auction.py','tools/loopback_exchange.py')
SUITES=['test_game_operations','test_service_operations','test_city_services','test_services',
        'test_city_services_integration','test_player_trade','test_player_trade_transport',
        'test_player_auction','test_private_market','test_private_market_refresh',
        'test_trade_window_refresh','test_sc_auction','test_sc_auction_view.SCViewTests']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-only',action='store_true')
    parser.add_argument('--regression-only',action='store_true');args=parser.parse_args()
    source=WORK/'remote-source';candidate=WORK/'candidate'
    if not args.baseline_only:
        if not candidate.exists():shutil.copytree(source,candidate)
        manifest={}
        for name in FILES:
            before=source/name;overlay=WORK/'overlay'/name
            path=overlay if overlay.is_file() else ROOT/name
            manifest[name]=dict(before=hashlib.sha256(before.read_bytes()).hexdigest() if before.is_file() else None,
                                after=hashlib.sha256(path.read_bytes()).hexdigest())
            shutil.copy2(path,candidate/name)
        (REPORT/'patch-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (REPORT/'source-map.json').write_text(json.dumps({name:str((WORK/'overlay'/name) if (WORK/'overlay'/name).is_file() else ROOT/name) for name in FILES},indent=2)+'\n')
    else:candidate=source
    sys.path[:0]=[str(candidate),str(ROOT/'tests'),str(ROOT)]
    # Runtime helper imports can prepend paths. Pin the snapshot's dispatcher
    # before test helpers import unrelated local tools from this namespace.
    import tools
    tools.__path__=[str(candidate/'tools'),str(ROOT/'tools')]
    import tools.loopback_exchange
    assert Path(tools.loopback_exchange.__file__).resolve()==(candidate/'tools/loopback_exchange.py').resolve()
    suites=SUITES+([] if args.baseline_only or args.regression_only else ['test_market_operations'])
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(suites))
    report=dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),
                errors=len(result.errors),baseline_only=args.baseline_only,suites=suites,
                dispatcher=str(Path(tools.loopback_exchange.__file__).resolve()))
    name='baseline-checks.json' if args.baseline_only else 'automated-checks.json'
    (REPORT/name).write_text(json.dumps(report,indent=2)+'\n')
    sys.exit(not result.wasSuccessful())


if __name__=='__main__':main()
