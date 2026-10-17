"""Stage bank-command changes over the inspected hosted source and run checks."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/bank-operations-20261015'
BASELINE=ROOT/'work/bank-operations-20261015/remote-source'
CANDIDATE=ROOT/'work/bank-operations-20261015/candidate'
FILES=('server/bank_operations.py','server/bank_gameplay.py','server/city_operations.py')

def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def main():
    if not CANDIDATE.exists():shutil.copytree(BASELINE,CANDIDATE)
    manifest={}
    for name in FILES:
        source=ROOT/name;before=BASELINE/name
        manifest[name]=dict(before=sha256(before.read_bytes()).hexdigest() if before.is_file() else None,
                            after=sha256(source.read_bytes()).hexdigest())
        shutil.copy2(source,CANDIDATE/name)
    (REPORT/'patch-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    sys.path[:0]=[str(CANDIDATE),str(ROOT/'tests'),str(ROOT),str(CANDIDATE.parent/'test-dependencies')]
    names=['test_game_operations','test_service_operations','test_city_services',
           'test_services','test_city_services_integration','test_bank_gameplay','test_city_operations',
           'test_bank_operations']
    all_tests=list(flatten(unittest.defaultTestLoader.loadTestsFromNames(names)))
    selected=all_tests
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    (REPORT/'automated-checks.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        selected=[case.id() for case in selected]),indent=2)+'\n',encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':main()
