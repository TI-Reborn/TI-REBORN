"""Verify the approved world XML and player standings against published F8."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-completion/stage8-world'

def main():
    release=json.loads((FOLDER/'client/release.json').read_text())
    xml=FOLDER/'client/candidate/zones.xml'
    if hashlib.sha256(xml.read_bytes()).hexdigest()!=release['candidate_sha256']:
        raise ValueError('Approved world XML changed')
    binary=ROOT/'reports/gameplay-completion/stage6-economy/client/candidate/silver.dll'
    sha='7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b'
    with tempfile.TemporaryDirectory(prefix='tio-world-native-') as temporary:
        out=Path(temporary)
        jobs=[('verify_world_catalog_native.py',['--xml',str(xml),'--output',str(out/'world.json')]),
              ('verify_player_top100_native.py',['--binary',str(binary),'--sha',sha,'--output',str(out/'ratings.json')])]
        for name,args in jobs:
            result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools'/name),*args],cwd=ROOT,capture_output=True,text=True,timeout=90)
            if result.returncode:raise RuntimeError('Native verification failed: '+name)
        world=json.loads((out/'world.json').read_text())
        standings=json.loads((out/'ratings.json').read_text())
        print(json.dumps(dict(passed=world['passed'],world_towns=len(world['loader_cases']),
            visibility_cases=len(world['town_cases']),standings_requests=len(standings['requests']),
            standings_cases=len(standings['cases']),published_dll_sha256=sha,
            world_client_release=release['world_client_release'],graphical_client_acceptance=False)))

if __name__=='__main__':main()
