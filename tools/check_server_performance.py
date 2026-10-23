"""Run identical fixture suites against isolated hosted baseline/candidate trees."""
import argparse
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

def main():
    p=argparse.ArgumentParser();p.add_argument('--tree',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--new-tests',action='store_true');p.add_argument('--baseline-failures',type=Path);args=p.parse_args()
    tree=args.tree.resolve();sys.path[:0]=[str(tree/'tests'),str(tree)]
    # Old in-memory economy fixtures have no hosted HTTP/service runtime.
    # Complete routers retain real timers; protocol QA exercises those later.
    import server.services_runtime as services
    original=services.tick
    def tick(router):
        if hasattr(router,'config'):return original(router)
    names=['test_native_team_lobby_list','test_economy_runtime','test_bank_economy','test_shared_team_arena',
           'test_team_lobbies','test_training_arena','test_battle_crash_recovery','test_team_heartbeat']
    if args.new_tests:names.append('test_server_performance')
    if (tree/'tests/test_snapshot_fast_types.py').is_file() and args.new_tests:
        names.extend(('test_pool_listing_performance','test_snapshot_fast_types','test_durability'))
    stream=io.StringIO()
    with patch.object(services,'tick',tick):
        suite=unittest.defaultTestLoader.loadTestsFromNames(names)
        excluded=[]
        if args.baseline_failures:
            baseline=json.loads(args.baseline_failures.read_text(encoding='utf-8'))
            known={name for name,_ in baseline['failures']+baseline['errors']}
            def flatten(value):
                for item in value:
                    if isinstance(item,unittest.TestSuite):yield from flatten(item)
                    else:yield item
            tests=[]
            for test in flatten(suite):
                if str(test) in known:excluded.append(str(test))
                else:tests.append(test)
            assert len(excluded)==len(known)
            suite=unittest.TestSuite(tests)
        result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
    report=dict(tree=str(tree),tests=result.testsRun,failures=[(str(t),message) for t,message in result.failures],
        errors=[(str(t),message) for t,message in result.errors],skipped=len(result.skipped),passed=result.wasSuccessful(),
        excluded_unchanged_baseline_failures=excluded,
        fixture_adaptation='Skip hosted services_tick only for old fixture routers without config')
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.txt').write_text(stream.getvalue(),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('failures','errors')},default=str))
    print('failures:',*[t for t,_ in result.failures]);print('errors:',*[t for t,_ in result.errors])

if __name__=='__main__':main()
