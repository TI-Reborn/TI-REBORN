"""Record resolved fixture setup failures while preserving original test reports."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'reports/gameplay-completion/legacy-lobbies-20261011'


def main():
    first = json.loads((FOLDER/'validation-failed-2.json').read_text())
    retry = json.loads((FOLDER/'validation.json').read_text())
    log = Path(first['log']).read_text(encoding='utf-8')
    again = Path(retry['log']).read_text(encoding='utf-8')
    failures = re.findall(r'^ERROR: (\w+) \(([^)]+)\)',log,re.M)
    if (len(failures)!=5 or any(not name.startswith('test_arena.') for _,name in failures)
            or log.count('FileNotFoundError:')!=5 or 'FAILED (errors=5)' not in log
            or 'Ran 106 tests' not in log or 'Ran 8 tests' not in again or not again.rstrip().endswith('OK')
            or not retry['passed'] or not first['source_unchanged'] or not retry['source_unchanged']
            or first['source_sha256']!=retry['source_sha256']):
        raise ValueError('Only the exact missing native fixtures may be resolved')
    for name in first['test_modules']:
        before=Path(first['candidate_directory'])/'tests'/f'{name}.py'
        if before.read_bytes()!=(ROOT/'tests'/f'{name}.py').read_bytes():
            raise ValueError('Reviewed successful test source changed')
    result=dict(retry,test_modules=first['test_modules'],
                checks=dict(unique_tests=106,initial_passed=101,fixture_retry_tests=8,
                            fixture_setup_errors_resolved=5,remaining_failures=0),
                initial_log=first['log'],retry_log=retry['log'])
    with (FOLDER/'overall-validation.json').open('x',encoding='utf-8') as out:
        json.dump(result,out,indent=2)
    print(json.dumps({'passed':True,'unique_tests':106,'remaining_failures':0}))


if __name__=='__main__':
    main()
