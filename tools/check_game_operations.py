"""Validate a scoped refactor against the inspected hosted runtime snapshot."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILES=('server/game_operations.py','server/service_operations.py','server/city_services.py',
       'server/services_runtime.py','server/services_v2.py')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,default=ROOT/'work/game-operations-20261015/remote-source')
    parser.add_argument('--candidate',type=Path,default=ROOT/'work/game-operations-20261015/candidate')
    args=parser.parse_args()
    if not args.candidate.exists():shutil.copytree(args.baseline,args.candidate)
    manifest={}
    for name in FILES:
        source=ROOT/name;before=args.baseline/name;target=args.candidate/name
        manifest[name]=dict(before=sha256(before.read_bytes()).hexdigest() if before.is_file() else None,
                            after=sha256(source.read_bytes()).hexdigest())
        shutil.copy2(source,target)
    report=ROOT/'reports/game-operations-20261015';report.mkdir(parents=True,exist_ok=True)
    (report/'patch-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    sys.path[:0]=[str(args.candidate.resolve()),str(ROOT/'tests')]
    suites=['test_game_operations','test_service_operations','test_city_services',
            'test_services','test_city_services_integration']
    suite=unittest.defaultTestLoader.loadTestsFromNames(suites)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    (report/'automated-checks.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        runtime_baseline=str(args.baseline.resolve()),candidate=str(args.candidate.resolve())),indent=2)+'\n',encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':main()
