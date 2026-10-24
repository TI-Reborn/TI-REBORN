"""Run targeted saved-roster and authoritative party/location regression suites."""
import argparse
import io
import json
from pathlib import Path
import sys
import unittest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tree',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--new-tests',action='store_true');parser.add_argument('--baseline-failures',type=Path);args=parser.parse_args()
    tree=args.tree.resolve();sys.path[:0]=[str(tree/'tests'),str(tree)]
    names=['test_travel_party','test_party_travel','test_passive_stats','test_ability_learning',
        'test_ability_progression','test_roster_progression','test_character_slots','test_weight',
        'test_equipment_bonuses','test_armor_equipment','test_squad','test_ranks',
        'test_ability_state','test_equipment_batch','test_shared_equipment_batch','test_battle_healing']
    if args.new_tests:names.append('test_read_projection_performance')
    stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    excluded=[]
    if args.baseline_failures:
        baseline=json.loads(args.baseline_failures.read_text(encoding='utf-8'))
        known={name for name,_ in baseline['failures']+baseline['errors']}
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
    result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
    report=dict(tree=str(tree),tests=result.testsRun,passed=result.wasSuccessful(),skipped=len(result.skipped),
        failures=[(str(t),message) for t,message in result.failures],errors=[(str(t),message) for t,message in result.errors],
        excluded_unchanged_baseline_failures=excluded)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.txt').write_text(stream.getvalue(),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('errors','failures')}))
    print('failures:',*[str(t) for t,_ in result.failures]);print('errors:',*[str(t) for t,_ in result.errors])
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
