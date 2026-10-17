"""Run focused candidate tests against the actual hosted code plus its overlay."""
from pathlib import Path
import json,shutil,subprocess,tarfile,tempfile

def extract(archive,target):
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile() or not (target/member.name).resolve().is_relative_to(target):raise RuntimeError('Unsafe member')
        tar.extractall(target,filter='data')

def main():
    candidate=Path(tempfile.mkdtemp(prefix='tio-encounter-candidate-',dir='/root'))
    shutil.copytree('/opt/tio-emulator',candidate,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.venv','__pycache__','*.pyc'))
    extract('/root/tio-dog-encounters-patch.tar.gz',candidate)
    extract('/root/tio-dog-encounters-tests.tar.gz',candidate)
    command=['/opt/tio-emulator/.venv/bin/python','-m','unittest','discover','-s','tests','-p','test_world_encounters.py','-v']
    process=subprocess.run(command,cwd=candidate,capture_output=True,text=True)
    print(process.stdout);print(process.stderr)
    if process.returncode:raise RuntimeError('Candidate encounter tests failed')
    print(json.dumps(dict(candidate=str(candidate),passed=True,kind='isolated SQLite fixtures on actual hosted code overlay; no real clients')))

if __name__=='__main__':main()
