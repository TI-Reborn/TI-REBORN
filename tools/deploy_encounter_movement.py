"""Install the bounded tested patch using the existing backup-preserving deployer."""
import json
from pathlib import Path
import subprocess
import argparse
from check_encounter_movement import ROOT,REPORT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maintenance-restart',action='store_true')
    args=parser.parse_args()
    identity=str(Path.home()/'.ssh/tio_server')
    opts=['-i',identity,'-o','BatchMode=yes','-o','ConnectTimeout=10']
    package=json.loads((REPORT/'package.json').read_text())
    copies=((Path(package['archive']),'encounter-movement-20261017.tar.gz'),
            (REPORT/'baseline-sha256.json','encounter-movement-20261017-baseline.json'),
            (ROOT/'tools/deploy_game_operations_remote.py','deploy-encounter-movement-20261017.py'))
    for source,target in copies:
        subprocess.run(['scp',*opts,str(source),'root@185.184.42.88:/root/'+target],check=True,capture_output=True,timeout=45)
    command='python3 /root/deploy-encounter-movement-20261017.py --scope encounter-movement --archive /root/encounter-movement-20261017.tar.gz --sha256 '+package['sha256']+' --baseline /root/encounter-movement-20261017-baseline.json --backup /root/tio-before-game-operations-encounter-movement-20261017'
    if args.maintenance_restart:command+=' --maintenance-restart'
    result=subprocess.run(['ssh',*opts,'root@185.184.42.88',command],capture_output=True,text=True,encoding='utf-8',timeout=180)
    if result.returncode:
        (REPORT/'deployment-failure.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        raise RuntimeError('Scoped deployment declined or failed; see local deployment-failure.log')
    report=json.loads(result.stdout)
    (REPORT/'deployment.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
