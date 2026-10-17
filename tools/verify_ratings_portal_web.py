"""Record focused read-only portal checks without touching game data or services."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-followup/stage4-ratings/portal'
WEB=ROOT/'web'


def pins():
    paths=list(WEB.joinpath('src').rglob('*.ts'))+list(WEB.joinpath('src').rglob('*.tsx'))
    paths+=list(WEB.joinpath('tests').glob('*.ts'))+[WEB/'package.json',WEB/'tsconfig.json',WEB/'next.config.ts']
    return {path.relative_to(WEB).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths) if path.is_file()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('name',choices=('validation1','validation2','final'))
    args=parser.parse_args();folder=FOLDER/args.name;output=folder/'web-validation.json'
    if output.exists():raise ValueError('Preserve earlier portal validation')
    command=shutil.which('pnpm.cmd' if os.name=='nt' else 'pnpm')
    if not command:raise ValueError('Existing pnpm runtime is required')
    before=pins();results=[]
    for label,arguments in (('focused-tests',['exec','tsx','--test','tests/ratings.test.ts','tests/city.test.ts','tests/assault.test.ts']),
                            ('typescript',['exec','tsc','--noEmit'])):
        started=time.monotonic()
        result=subprocess.run([command,*arguments],cwd=WEB,capture_output=True,encoding='utf-8',errors='replace',timeout=120)
        log=folder/(label+'.log');log.write_text(result.stdout+result.stderr,encoding='utf-8')
        results.append(dict(check=label,command=['pnpm',*arguments],exit_code=result.returncode,
                            seconds=round(time.monotonic()-started,3),log=log.relative_to(folder).as_posix()))
    after=pins();unchanged=before==after
    proof=dict(version=1,utc=datetime.now(timezone.utc).isoformat(),passed=unchanged and all(r['exit_code']==0 for r in results),
               checks=results,source_unchanged=unchanged,source_sha256=before,hosted_changes=False,graphical_acceptance=False,
               player_data_opened=False,scope='Focused portal ratings and published city/assault regression; TypeScript')
    output.write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:proof[k] for k in ('passed','checks','source_unchanged')}))
    if not proof['passed']:raise SystemExit(1)


if __name__=='__main__':main()
