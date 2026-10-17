"""Run portal tests using an owned disposable PostgreSQL database via SSH.

The production database is never selected. Credentials exist only in process
memory, and the generated database/role and SSH tunnel are removed afterwards.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15']
HOST='root@185.184.42.88'
HIDDEN=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0


def sql(statement):
    remote="import subprocess\nsubprocess.run(['runuser','-u','postgres','--','psql','-X','-v','ON_ERROR_STOP=1','-d','postgres'],input="+repr(statement)+",text=True,stdout=subprocess.DEVNULL,check=True)\n"
    result=subprocess.run(SSH+[HOST,'python3 -'],input=remote,text=True,capture_output=True)
    if result.returncode:
        raise RuntimeError('Isolated PostgreSQL setup/cleanup failed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/site-backups',
                        help='Directory for sanitized website-tests.log and website-tests.json; relative paths use the repository root (default: reports/site-backups)')
    args=parser.parse_args()
    report_dir=args.report_dir if args.report_dir.is_absolute() else ROOT/args.report_dir
    name='portal_check_'+secrets.token_hex(8)
    assert re.fullmatch(r'portal_check_[a-f0-9]{16}',name)
    password=secrets.token_hex(32)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
    tunnel=None
    created=False
    try:
        sql(f"CREATE ROLE {name} LOGIN PASSWORD '{password}';\nCREATE DATABASE {name} OWNER {name};\n")
        created=True
        tunnel=subprocess.Popen(SSH+['-o','ExitOnForwardFailure=yes','-L',f'127.0.0.1:{port}:127.0.0.1:5432','-N',HOST],
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
        deadline=time.monotonic()+20
        while True:
            if tunnel.poll() is not None:raise RuntimeError('Isolated test tunnel failed')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=1):break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError('Isolated test tunnel timed out')
                time.sleep(0.2)
        environment=dict(os.environ)
        url=f'postgresql://{name}:{password}@127.0.0.1:{port}/{name}'
        environment['DATABASE_URL']=url
        pnpm=shutil.which('pnpm.cmd' if os.name=='nt' else 'pnpm')
        if not pnpm:raise RuntimeError('pnpm is unavailable')
        result=subprocess.run([pnpm,'test'],cwd=ROOT/'web',env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=HIDDEN)
        output=(result.stdout+'\n'+result.stderr).replace(url,'[isolated database URL]').replace(password,'[redacted]')
        report=report_dir/'website-tests.log'
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(output,encoding='utf-8')
        summary={key:int(value) for key,value in re.findall(r'(?:#|\u2139) (tests|pass|fail|skipped) (\d+)',output)}
        record={'exit_code':result.returncode,'isolated_database':True,'live_database_selected':False,'production_game_api_used':False,'summary':summary}
        (report.parent/'website-tests.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(record))
        if result.returncode:raise RuntimeError('Portal tests failed; see sanitized test log')
    finally:
        if tunnel is not None:
            tunnel.terminate()
            try:tunnel.wait(timeout=10)
            except subprocess.TimeoutExpired:tunnel.kill();tunnel.wait(timeout=10)
        if created:
            sql(f'DROP DATABASE IF EXISTS {name} WITH (FORCE);\nDROP ROLE IF EXISTS {name};\n')


if __name__=='__main__':main()
