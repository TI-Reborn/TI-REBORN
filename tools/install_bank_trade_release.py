"""Install the checked combined release, using protected remote backups only."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import json,subprocess

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/bank-trade-release-20261015'
KEY=str(Path.home()/'.ssh/tio_server')
SSH=['ssh','-i',KEY,'-o','BatchMode=yes','-o','ConnectTimeout=8','root@185.184.42.88']

def main():
    checked=json.loads((REPORT/'automated-checks.json').read_text())
    assert checked['passed'] and checked['tests']==191 and not checked['skipped']
    archive=REPORT/'bank-trade-release.tar.gz'
    digest=sha256(archive.read_bytes()).hexdigest()
    assert digest==checked['archive_sha256']
    tag='bank-trade-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    package='/root/tio-'+tag;backup='/root/tio-before-game-operations-'+tag
    subprocess.run(SSH+['umask 077 && mkdir '+package],check=True,capture_output=True,timeout=20)
    subprocess.run(['scp','-i',KEY,'-o','BatchMode=yes',str(archive),
        str(REPORT/'runtime-before-sha256.json'),str(ROOT/'tools/deploy_game_operations_remote.py'),
        'root@185.184.42.88:'+package+'/'],check=True,capture_output=True,timeout=45)
    receipt=dict(package=package,backup=backup,archive_sha256=digest,scope='bank-trade')
    (REPORT/'package.json').write_text(json.dumps(receipt,indent=2))
    command='/opt/tio-emulator/.venv/bin/python '+package+'/deploy_game_operations_remote.py'+\
        ' --scope bank-trade --maintenance-restart --archive '+package+'/bank-trade-release.tar.gz'+\
        ' --sha256 '+digest+' --baseline '+package+'/runtime-before-sha256.json --backup '+backup
    result=subprocess.run(SSH+[command],capture_output=True,text=True,timeout=180)
    if result.returncode:
        (REPORT/'deployment-error.log').write_text(result.stderr)
        raise RuntimeError('Deployment failed; inspect private local deployment-error.log')
    report=json.loads(result.stdout)
    (REPORT/'deployment.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':main()
