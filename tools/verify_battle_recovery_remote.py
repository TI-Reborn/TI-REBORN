"""Candidate/deployed crash checks on the VPS, isolated from hosted players."""
from pathlib import Path
import argparse,json,shlex,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/stage3-battle-recovery'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--candidate',action='store_true');args=parser.parse_args()
    code='''import pathlib,sys,tarfile,tempfile,unittest,json,time,shutil
candidate=json.load(sys.stdin)['candidate'];live=pathlib.Path('/opt/tio-emulator')
with tempfile.TemporaryDirectory(prefix='tio-recovery-tests-') as folder:
 stage=pathlib.Path(folder);fixtures=stage/'tests';fixtures.mkdir()
 with tarfile.open('/root/tio-battle-recovery-tests.tar.gz') as tar:
  for member in tar.getmembers():
   if not member.isfile() or pathlib.Path(member.name).name!=member.name or not member.name.endswith('.py'):raise ValueError('Unsafe test member')
  tar.extractall(fixtures,filter='data')
 root=live
 if candidate:
  root=stage/'source';root.mkdir()
  for name in ('server','tio','tools'):shutil.copytree(live/name,root/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  for name in ('config','evidence'):(root/name).symlink_to(live/name,target_is_directory=True)
  with tarfile.open('/root/tio-battle-recovery-patch.tar.gz') as tar:
   for member in tar.getmembers():
    if not member.isfile() or not (root/member.name).resolve().is_relative_to(root):raise ValueError('Unsafe candidate member')
   tar.extractall(root,filter='data')
 sys.path[:0]=[str(root),str(fixtures)]
 import test_shared_team_arena,test_shooting_range,test_mining,test_combat,test_multi_account,test_sc_shop,test_equipment_templates,test_battle_exchange
 for module in (test_shared_team_arena,test_shooting_range,test_mining,test_combat,test_multi_account,test_sc_shop,test_equipment_templates,test_battle_exchange):module.ROOT=root
 import test_battle_crash_recovery as crash
 import test_stage2_admission_capacity as capacity
 crash.ROOT=root
 started=time.monotonic()
 suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in (crash,capacity,test_battle_exchange,test_multi_account))
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 from benchmark_battle_checkpoints import run
 benchmark=run(root,fixtures) if result.wasSuccessful() else None
 print(json.dumps(dict(candidate=candidate,tests=result.testsRun,passed=result.wasSuccessful(),seconds=round(time.monotonic()-started,3),benchmark=benchmark,
 kind='temporary databases, isolated loopback TCP and forced exits of isolated processes only')))
 sys.exit(not result.wasSuccessful())'''
    completed=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@185.184.42.88',
        '/opt/tio-emulator/.venv/bin/python -c '+shlex.quote(code)],input=json.dumps(dict(candidate=args.candidate)),
        capture_output=True,text=True,encoding='utf-8',timeout=180)
    label='candidate' if args.candidate else 'deployed'
    (FOLDER/f'remote-{label}-tests.log').write_text(completed.stdout+completed.stderr,encoding='utf-8')
    if completed.stdout.strip():
        data=json.loads(completed.stdout.strip().splitlines()[-1]);(FOLDER/f'remote-{label}-tests.json').write_text(json.dumps(data,indent=2)+'\n')
        print(json.dumps(data))
    else:print(completed.stderr[-3000:])
    sys.exit(completed.returncode)


if __name__=='__main__':main()
