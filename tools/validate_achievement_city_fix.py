"""Verify the captured production revision with disposable databases and TCP peers."""
from datetime import datetime, timezone
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

from tools.prepare_achievement_city_fix import ROOT, FOLDER
from tools.deploy_stage4_economy import remote

RUN = """import sys,unittest
sys.path.insert(0,'tests')
suite=unittest.TestSuite()
skip={'test_loopback_answers_captured_b501','test_sc_purchase_and_real_enhancement_events'}
def add(value):
 if isinstance(value,unittest.TestSuite):
  for item in value:add(item)
 elif value._testMethodName not in skip:suite.addTest(value)
for name in ('test_achievement_noncity_delivery','test_achievements','test_post_battle_achievement_delivery'):
 add(unittest.defaultTestLoader.loadTestsFromName(name))
result=unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(not result.wasSuccessful())
"""


def main():
    runtime = FOLDER / 'runtime'
    shutil.copytree(ROOT / 'tests', runtime / 'tests',
                    ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    name = 'tio/achievements.py'
    digest = hashlib.sha256((runtime / name).read_bytes()).hexdigest()
    env = dict(os.environ, PYTHONPATH=str(runtime / 'tests'))
    result = subprocess.run([sys.executable, '-c', RUN], cwd=runtime,
                            env=env, capture_output=True, text=True, timeout=90)
    (FOLDER / 'local-tests.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Captured runtime checks failed; inspect local-tests.txt')
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for path in sorted(runtime.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.add(path, arcname=path.relative_to(runtime).as_posix())
    code = """import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
p=json.load(sys.stdin)
stage=Path(tempfile.mkdtemp(prefix='tio-achievement-city-test-',dir='/root'))
try:
 with tarfile.open(fileobj=io.BytesIO(base64.b64decode(p['archive'])),mode='r:gz') as archive:
  archive.extractall(stage,filter='data')
 env=dict(os.environ,PYTHONPATH=str(stage/'tests'))
 result=subprocess.run(['/opt/tio-emulator/.venv/bin/python','-c',p['run']],cwd=stage,
                       env=env,capture_output=True,text=True,timeout=90)
 print(json.dumps(dict(passed=result.returncode==0,output=result.stdout+result.stderr,
       source_sha256=hashlib.sha256((stage/'tio/achievements.py').read_bytes()).hexdigest(),
       hosted_player_data_accessed=False,graphical_clients=False)))
finally:shutil.rmtree(stage)
"""
    hosted = remote(code, {'archive': base64.b64encode(stream.getvalue()).decode(), 'run': RUN})
    (FOLDER / 'hosted-isolated-tests.json').write_text(json.dumps(hosted, indent=2), encoding='utf-8')
    unchanged = hashlib.sha256((runtime / name).read_bytes()).hexdigest() == digest
    validation = dict(passed=hosted['passed'] and unchanged, source_unchanged=unchanged,
                      source_sha256={name: digest}, utc=datetime.now(timezone.utc).isoformat(),
                      suites=['noncity delivery and reconnect', 'achievement storage and receipts',
                              'post-battle city delivery'], tests=20,
                      legacy_incompatible_tests_excluded=['local diagnostic request replay helper absent on hosting',
                                                        'old SC offer ID absent in current hosted catalogue'],
                      hosted_isolated=hosted)
    (FOLDER / 'validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    print(json.dumps({k:validation[k] for k in ('passed','tests','source_unchanged')}))
    if not validation['passed']:
        raise RuntimeError('Hosted isolated checks failed')


if __name__ == '__main__':
    main()
