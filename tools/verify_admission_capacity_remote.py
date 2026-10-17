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
FOLDER=ROOT/'reports/stage2-admission-capacity'
HOST='root@185.184.42.88'
KEY=str(Path.home()/'.ssh/tio_server')


def main():
    code='''import pathlib,sys,tarfile,tempfile,unittest,json,time
root=pathlib.Path('/opt/tio-emulator');sys.path.insert(0,str(root))
with tempfile.TemporaryDirectory(prefix='tio-admission-capacity-tests-') as folder:
 stage=pathlib.Path(folder)
 with tarfile.open('/root/tio-admission-capacity-tests.tar.gz') as archive:
  for member in archive.getmembers():
   if not member.isfile() or pathlib.Path(member.name).name!=member.name or not member.name.endswith('.py'):raise ValueError('Unsafe test member')
  archive.extractall(stage,filter='data')
 sys.path.insert(0,folder)
 import test_multi_account as tcp_fixture
 import test_sc_shop as sc_fixture
 import test_equipment_templates as template_fixture
 tcp_fixture.ROOT=root;sc_fixture.ROOT=root;template_fixture.ROOT=root
 import test_stage2_admission_capacity as checks
 import test_battle_exchange as exchange_checks
 exchange_checks.ROOT=root
 import test_shared_team_arena as shared_fixture
 shared_fixture.ROOT=root
 started=time.monotonic()
 suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in (checks,exchange_checks))
 result=unittest.TextTestRunner(verbosity=2).run(suite)
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
