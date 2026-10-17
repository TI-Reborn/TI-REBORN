"""Record combined automated checks against an exact frozen runtime revision."""
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'tools')]


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--revision',type=int,default=1)
    args=parser.parse_args()
    if not 1<=args.revision<=10:parser.error('Expected bounded verification revision')
    folder=ROOT/'reports/stage7';suffix='' if args.revision==1 else '-revision'+str(args.revision)
    target=folder/('local-validation'+suffix+'.json');log=folder/('local-validation'+suffix+'.log')
    if target.exists() or log.exists():raise ValueError('Preserve previous verification evidence')
    files=json.loads((folder/'runtime-files.json').read_text())
    def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}
    before=hashes();start=time.monotonic()
    with log.open('x',encoding='utf-8') as output,redirect_stdout(output),redirect_stderr(output):
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
        result=unittest.TextTestRunner(stream=output,verbosity=1).run(suite)
    after=hashes()
    report=dict(observed_utc=datetime.now(timezone.utc).isoformat(),passed=result.wasSuccessful() and before==after,
        tests=result.testsRun,skips=len(result.skipped),errors=len(result.errors),failures=len(result.failures),
        seconds=round(time.monotonic()-start,3),source_sha256=after,source_unchanged=before==after,
        kind='combined local automated suite; no graphical-client or hosted acceptance')
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','tests','skips','errors','failures','seconds','source_unchanged')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
