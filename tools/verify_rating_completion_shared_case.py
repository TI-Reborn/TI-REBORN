"""Run one approved stale ABI assertion correction on exact frozen runtime."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from verify_public_runtime_regression import extract,sha

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-followup/stage4-ratings'
FINAL=FOLDER/'final/public-regression-candidate'
TEST='test_shared_team_arena.SharedTeamTests.test_hidden_opponent_remains_alive_without_disclosing_position_or_hp'


def main():
    output=FOLDER/'shared-abi-correction.json'
    if output.exists():raise ValueError('Preserve previous correction proof')
    old=(FINAL/'test-snapshot/tests/test_shared_team_arena.py').read_text(encoding='utf-8')
    correction="""            from tio.protocol.night_vision_state import decode_night_vision_state
            refresh=view.refresh()
            self.assertEqual(refresh,(b'\\xf7\\x01\\x00\\x00',b'\\xf9\\x01\\x00\\x00'))
            self.assertEqual(decode_night_vision_state(refresh[1]),())"""
    expected=old.replace("            self.assertEqual(view.refresh(),(b'\\xf7\\x01\\x00\\x00',))",correction)
    actual=(ROOT/'tests/test_shared_team_arena.py').read_text(encoding='utf-8')
    if expected==old or actual!=expected:raise ValueError('Additional unreviewed shared test changes')
    baseline=json.loads((FINAL/'local-isolated.json').read_text(encoding='utf-8'))
    bundle=(FINAL/'local-test-bundle.tar.gz').read_bytes()
    if sha(bundle)!=baseline['test_bundle_sha256']:raise ValueError('Changed frozen bundle')
    pins=baseline['test_runtime_sha256'];env=dict(os.environ)
    for key in tuple(env):
        if any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','STRIPE','SERVICE_KEY')):env.pop(key)
    env['PYTHONDONTWRITEBYTECODE']='1'
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='tio-rating-abi-correction-') as directory:
        stage=Path(directory);extract(bundle,stage)
        hashes=lambda:{name:sha((stage/name).read_bytes()) for name in pins}
        if hashes()!=pins:raise ValueError('Frozen runtime mismatch')
        (stage/'tests/test_shared_team_arena.py').write_text(actual,encoding='utf-8',newline='\n')
        runner="""import sys,unittest,json
sys.path.insert(0,'tests')
suite=unittest.TestLoader().loadTestsFromName(%r)
assert suite.countTestCases()==1
r=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps(dict(testsRun=r.testsRun,failures=len(r.failures),errors=len(r.errors),skips=len(r.skipped))))
sys.exit(not r.wasSuccessful())
"""%TEST
        (stage/'single-case.py').write_text(runner,encoding='utf-8')
        p=subprocess.run([str(ROOT/'data/registration-check-env/Scripts/python.exe'),'-X','utf8','single-case.py'],
                         cwd=stage,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60,
                         creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        unchanged=hashes()==pins
    report=dict(passed=p.returncode==0 and unchanged,testsRun=1,test=TEST,seconds=round(time.monotonic()-start,3),
                stdout=p.stdout,stderr=p.stderr,sourceUnchanged=unchanged,originalBundleSha256=sha(bundle),
                beforeTestSha256=sha(old.encode()),afterTestSha256=sha(actual.encode()),
                reason='Published stage9 owner-private F9 empty state accompanies F7, confirmed by decoding F9',
                repeatedPassedCases=0,hostedRuntimeModified=False,hostedPlayerDataOpened=False,graphicalClientAcceptance=False)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],testsRun=1,sourceUnchanged=unchanged)))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
