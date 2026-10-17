"""Read current hosted hashes and save counts before a scoped gameplay release."""
import argparse
import json
from pathlib import Path
from tools.deploy_gameplay_completion import ROOT,valid_path
from tools.deploy_stage4_economy import remote

INSPECT=r'''
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,time
p=json.load(sys.stdin);root=Path('/opt/tio-emulator')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def run(*args):return subprocess.run(args,capture_output=True,text=True,check=True,timeout=30).stdout.strip()
guards=('/etc/tio-server/server.toml','/etc/systemd/system/tio-server.service',
 '/var/www/tio-client/updates/manifest.json','/var/www/tio-client/downloads/TIO-Launcher.exe')
tables={}
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 db.execute('BEGIN');integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
  rows=sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'))
  tables[name]=dict(rows=len(rows),sha256=hashlib.sha256('\n'.join(rows).encode()).hexdigest())
 sc_deadlines=[int(row[0]-time.time()) for row in db.execute("SELECT ends FROM sc_auction_lots WHERE state='active'")] if 'sc_auction_lots' in tables else []
connections=run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
manifest=json.loads(Path(guards[2]).read_text())
print(json.dumps(dict(observed_utc=datetime.now(timezone.utc).isoformat(),integrity=integrity,tables=tables,
 files={n:dict(sha256=sha(root/n)) for n in p['files']},guards={n:sha(Path(n)) for n in guards},
 game_connections=len(connections.splitlines()) if connections else 0,sc_seconds_to_close=sc_deadlines,
 service=run('systemctl','show','tio-server','-p','ActiveState','-p','MainPID','-p','NRestarts','-p','ExecMainStatus'),
 client=dict(version=manifest['version'],silver=next(r for r in manifest['files'] if r['path']=='silver.dll')))))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',required=True,type=Path)
    parser.add_argument('--output',default='remote-baseline.json',help='Fresh JSON evidence filename inside the report folder')
    args=parser.parse_args();folder=args.folder.resolve()
    if not folder.is_relative_to(ROOT/'reports/gameplay-completion'):raise ValueError('Expected gameplay report folder')
    files=json.loads((folder/'runtime-files.json').read_text(encoding='utf-8'))
    if not files or not all(valid_path(n) for n in files):raise ValueError('Unexpected runtime paths')
    if Path(args.output).name!=args.output or not args.output.endswith('.json'):raise ValueError('Expected a plain JSON evidence filename')
    target=folder/args.output
    if target.exists():raise ValueError('Preserve previous hosted inspection')
    result=remote(INSPECT,dict(files=files))
    with target.open('x',encoding='utf-8') as output:json.dump(result,output,indent=2)
    print(json.dumps(dict(integrity=result['integrity'],game_connections=result['game_connections'],
       accounts=result['tables']['accounts']['rows'],checkpoints=result['tables']['battle_checkpoints']['rows'],sc_seconds_to_close=result['sc_seconds_to_close'],
       service=result['service'],client=result['client'])))


if __name__=='__main__':main()
