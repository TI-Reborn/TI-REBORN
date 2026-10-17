"""Prepare private credentials and a remote backup; never create game accounts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA

REMOTE = r'''
import hashlib,json,pathlib,sqlite3,subprocess,sys,tempfile
data=json.load(sys.stdin);names=data['names']
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-surroundings-qa-',dir='/root'));folder.chmod(0o700)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:
 assert not any(src.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
dst=sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True)
tables={}
for table, in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence' ORDER BY name"):
 q='"'+table.replace('"','""')+'"';rows=sorted(map(repr,dst.execute('SELECT * FROM '+q)))
 tables[table]=dict(count=len(rows),sha256=hashlib.sha256('\n'.join(rows).encode()).hexdigest())
paths=['opt/tio-emulator/server','opt/tio-emulator/tio','etc/tio-server','etc/tio-portal','etc/systemd/system/tio-server.service','etc/systemd/system/tio-server.service.d','etc/systemd/system/tio-portal.service','etc/systemd/system/tio-game-api.service','etc/nginx/sites-available','var/www/tio-client/updates/manifest.json','var/www/tio-client/downloads/TIO-Launcher.exe']
paths=[p for p in paths if pathlib.Path('/'+p).exists()]
subprocess.run(['tar','--exclude=__pycache__','-czf',str(folder/'code-config-downloads.tar.gz'),'-C','/',*paths],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
with (folder/'portal.dump').open('wb') as stream:
 subprocess.run(['runuser','-u','postgres','--','pg_dump','-Fc','tionline_web'],check=True,stdout=stream,stderr=subprocess.PIPE)
for p in folder.iterdir():p.chmod(0o600)
web_count=int(subprocess.check_output(['runuser','-u','postgres','--','psql','-d','tionline_web','-Atc','SELECT COUNT(*) FROM "User"'],text=True).strip())
services={n:subprocess.check_output(['systemctl','is-active',n],text=True).strip() for n in ('tio-server','tio-portal','tio-game-api','nginx')}
connections=subprocess.check_output(['ss','-Htn','state','established','( sport = :29512 or sport = :29513 or sport = :28512 or sport = :28513 )'],text=True).splitlines()
assert not connections,'Gameplay sessions present; do not enter shared QA matching'
result=dict(backup=str(folder),integrity='ok',accounts_before=dst.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],website_accounts_before=web_count,tables=tables,services=services,gameplay_connections=0,new_accounts_created=0,remote_database_writes=0)
(folder/'new-player-before.json').write_text(json.dumps(result,indent=2)+'\n');(folder/'new-player-before.json').chmod(0o600)
print(json.dumps(result))
'''

def main():
    folder = ROOT / 'reports/new-player'
    folder.mkdir(exist_ok=True)
    prefix = 'qs' + secrets.token_hex(4)
    fixture = FreshSurroundingsQA('185.184.42.88', prefix,
        [prefix + letter for letter in 'ab'],
        ['Qa1!' + secrets.token_urlsafe(24) for _ in range(2)], '')
    before = fixture.remote(REMOTE, fixture.ownership_payload())
    fixture.backup = before['backup']
    private = fixture.save_private()
    before.update(prefix=prefix, names=fixture.names, private_fixture=str(private),
        email_addresses=[n + '@example.invalid' for n in fixture.names])
    (folder / 'before.json').write_text(json.dumps(before, indent=2) + '\n', encoding='utf-8')
    for letter in 'ab':
        root = folder / ('client-' + letter)
        root.mkdir(exist_ok=False)
        assert not any(root.iterdir())
    print(json.dumps({k: before[k] for k in ('backup','accounts_before','website_accounts_before','names','private_fixture','email_addresses')}))

if __name__ == '__main__':
    main()
