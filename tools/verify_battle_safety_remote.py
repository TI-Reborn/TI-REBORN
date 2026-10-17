"""Exercise deployed sources on temporary SQLite and isolated loopback listeners.

Production accounts and the production service are never fault-injected here.
The separate public TCP profile verifier exercises the actual hosted service.
"""
from pathlib import Path
import json
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/stage1-battle-safety'
HOST='root@185.184.42.88'
KEY=str(Path.home()/'.ssh/tio_server')


def main():
    code='''import pathlib,sys,tarfile,tempfile,unittest,json,time
root=pathlib.Path('/opt/tio-emulator');sys.path.insert(0,str(root))
with tempfile.TemporaryDirectory(prefix='tio-battle-safety-tests-') as folder:
 stage=pathlib.Path(folder)
 with tarfile.open('/root/tio-battle-safety-tests.tar.gz') as archive:
  for member in archive.getmembers():
   if not member.isfile() or pathlib.Path(member.name).name!=member.name or not member.name.endswith('.py'):raise ValueError('Unsafe test member')
  archive.extractall(stage,filter='data')
 sys.path.insert(0,folder)
 import test_shared_team_arena as shared
 shared.ROOT=root
 import test_battle_failure_isolation as checks
 started=time.monotonic()
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(checks))
 print(json.dumps(dict(kind='deployed source; isolated temporary databases and loopback TCP, no production fault injection',
     tests=result.testsRun,passed=result.wasSuccessful(),seconds=round(time.monotonic()-started,3),
     failures=[str(t) for t,_ in result.failures],errors=[str(t) for t,_ in result.errors])))
 sys.exit(not result.wasSuccessful())'''
    completed=subprocess.run(['ssh','-i',KEY,'-o','BatchMode=yes',HOST,
        'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],
        capture_output=True,text=True,encoding='utf-8',timeout=120)
    (FOLDER/'remote-isolation-tests.log').write_text(completed.stdout+completed.stderr,encoding='utf-8')
    result=json.loads(completed.stdout.strip().splitlines()[-1])
    (FOLDER/'remote-isolation-tests.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));sys.exit(completed.returncode)


if __name__=='__main__':main()
