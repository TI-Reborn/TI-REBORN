"""Run focused checks locally or in a fresh isolated hosted source copy."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from inspect_training_base_20261018 import ROOT,REPORT,WORK,remote

MODULES=['test_training_arena','test_training_on_demand','test_world_runtime',
         'test_assault_interface_integration','test_assault_location_admission','test_assault_public']

REMOTE='''import hashlib,json,os,shutil,subprocess,tarfile,tempfile,time
from pathlib import Path
live=Path('/opt/tio-emulator')
baseline=json.loads(Path('/root/baseline-sha256.json').read_text())
for name,expected in baseline.items():assert hashlib.sha256((live/name).read_bytes()).hexdigest()==expected,name
stage=Path(tempfile.mkdtemp(prefix='tio-training-validation-',dir='/opt'))
for name in ('server','tio','tools','config','evidence'):shutil.copytree(live/name,stage/name,ignore=shutil.ignore_patterns('__pycache__'))
with tarfile.open('/root/patch.tar.gz') as archive:
 for name in ('server/training_arena.py','server/contracts_service.py'):(stage/name).write_bytes(archive.extractfile(name).read())
with tarfile.open('/root/tests.tar.gz') as archive:archive.extractall(stage,filter='data')
env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')}
started=time.monotonic()
result=subprocess.run([str(live/'.venv/bin/python'),'-m','unittest',*MODULES,'-q'],cwd=stage,env=env,capture_output=True,text=True,timeout=180)
print(json.dumps(dict(passed=result.returncode==0,seconds=round(time.monotonic()-started,3),stage=str(stage),log=result.stdout+result.stderr,isolated_database=True)))
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--remote',action='store_true');args=parser.parse_args()
    if args.remote:
        result=remote('MODULES='+repr(MODULES)+'\n'+REMOTE)
        label='remote-isolated-checks'
    else:
        env={**__import__('os').environ,'PYTHONPATH':str(WORK/'candidate')+';'+str(WORK/'candidate/tests')}
        started=time.monotonic()
        run=subprocess.run([sys.executable,'-m','unittest',*MODULES,'-q'],cwd=WORK/'candidate',env=env,text=True,capture_output=True,timeout=180)
        result=dict(passed=run.returncode==0,seconds=round(time.monotonic()-started,3),log=run.stdout+run.stderr,isolated_database=True)
        label='automated-checks'
    (REPORT/(label+'.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result));sys.exit(0 if result['passed'] else 1)


if __name__=='__main__':main()
