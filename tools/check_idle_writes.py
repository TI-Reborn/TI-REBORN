"""Targeted contract/party/economic acceptance against an isolated source tree."""
import argparse
import io
import json
from pathlib import Path
import sys
import unittest


def main():
    p=argparse.ArgumentParser();p.add_argument('--tree',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--new-tests',action='store_true');p.add_argument('--baseline-failures',type=Path);args=p.parse_args()
    tree=args.tree.resolve();sys.path[:0]=[str(tree/'tests'),str(tree)]
    names=['test_pve_contracts','test_travel_party','test_party_travel','test_sc_auction',
        'test_private_market','test_private_market_refresh','test_player_auction',
        'test_contracts_service','test_contracts_combat','test_contracts_local_tcp','test_read_projection_performance']
    if args.new_tests:names.append('test_idle_write_performance')
    suite=unittest.defaultTestLoader.loadTestsFromNames(names);excluded=[]
    if args.baseline_failures:
        baseline=json.loads(args.baseline_failures.read_text(encoding='utf-8'))
        known={name.partition(' (index=')[0] for name,_ in baseline['failures']+baseline['errors']}
        def flatten(value):
            for item in value:
                if isinstance(item,unittest.TestSuite):yield from flatten(item)
                else:yield item
        included=[]
        for test in flatten(suite):
            if str(test) in known:excluded.append(str(test))
            else:included.append(test)
        assert set(excluded)==known
        suite=unittest.TestSuite(included)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
    report=dict(tree=str(tree),tests=result.testsRun,passed=result.wasSuccessful(),skipped=len(result.skipped),
        failures=[(str(t),msg) for t,msg in result.failures],errors=[(str(t),msg) for t,msg in result.errors],excluded_unchanged_baseline_failures=excluded)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');args.output.with_suffix('.txt').write_text(stream.getvalue(),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('failures','errors')}))
    print('failures:',*[str(t) for t,_ in result.failures]);print('errors:',*[str(t) for t,_ in result.errors])
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
