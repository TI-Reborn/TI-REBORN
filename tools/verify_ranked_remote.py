"""Run focused tests in an isolated copy of the actual hosted code."""
from pathlib import Path
import json,shutil,subprocess,sys,tarfile,tempfile

def main():
    root=Path('/opt/tio-emulator');candidate=Path(tempfile.mkdtemp(prefix='tio-ranked-candidate-',dir='/root'))
    for name in ('tio','server','tools','config'):
        shutil.copytree(root/name,candidate/name,ignore=shutil.ignore_patterns('__pycache__','*.sqlite3'))
    (candidate/'evidence').symlink_to(root/'evidence',target_is_directory=True)
    for path in ('/root/tio-ranked-patch.tar.gz','/root/tio-ranked-tests.tar.gz'):
        with tarfile.open(path) as tar:tar.extractall(candidate,filter='data')
    modules=('test_ranked','test_shared_team_arena','test_battle_crash_recovery',
             'test_public_profile','test_player_statistics','test_world_bootstrap','test_town_info')
    sys.path[:0]=[str(candidate),str(candidate/'tests'),str(candidate/'tools')]
    import unittest
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in modules)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report=dict(candidate=str(candidate),tests=result.testsRun,passed=result.wasSuccessful(),modules=modules)
    (candidate/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    if not result.wasSuccessful():raise SystemExit(1)

if __name__=='__main__':main()
