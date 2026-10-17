"""Candidate source overlay checks without touching hosted player data."""
from pathlib import Path
import json,shutil,subprocess,tarfile,tempfile

def main():
    candidate=Path(tempfile.mkdtemp(prefix='tio-reservation-candidate-',dir='/root'))
    shutil.copytree('/opt/tio-emulator',candidate,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.venv','__pycache__','*.pyc'))
    for archive in ('/root/tio-reservation-textures-patch.tar.gz','/root/tio-reservation-textures-tests.tar.gz'):
        with tarfile.open(archive) as tar:
            assert all(m.isfile() and (candidate/m.name).resolve().is_relative_to(candidate) for m in tar.getmembers())
            tar.extractall(candidate,filter='data')
    for pattern in ('test_reservation_visuals.py','test_map_generation.py','test_cities.py'):
        run=subprocess.run(['/opt/tio-emulator/.venv/bin/python','-m','unittest','discover','-s','tests','-p',pattern,'-v'],cwd=candidate,capture_output=True,text=True)
        print(run.stdout);print(run.stderr)
        assert run.returncode==0,pattern
    print(json.dumps(dict(candidate=str(candidate),passed=True,kind='isolated fixtures on hosted source overlay; no real game clients')))

if __name__=='__main__':main()
