"""Read-only post-deployment health and warehouse admission verification."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

sys.path.insert(0,'/opt/tio-emulator')
sys.dont_write_bytecode=True
from tio.warehouse_completion import current_town

backup=Path('/root/tio-before-game-operations-mine-warehouses-20261023')
receipt=json.loads((backup/'backup-manifest.json').read_text())
source=Path('/opt/tio-emulator/tio/warehouse_completion.py')
expected='73b3cab68b1165f930b56f064fe4c655c5c23b1ac1674552a853ce7d05260d53'
assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
assert hashlib.sha256(Path('/etc/tio-server/server.toml').read_bytes()).hexdigest()==receipt['config_sha256']
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
    accounts=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
    clans=db.execute('SELECT COUNT(*) FROM clans').fetchone()[0]
with sqlite3.connect(':memory:') as db:
    db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER)')
    for town in (13,14,15,16):
        db.execute('INSERT OR REPLACE INTO character_locations VALUES (?,?)',('admission-probe',town))
        assert current_town(db,'admission-probe')==town
services={name:subprocess.check_output(['systemctl','is-active',name],text=True).strip()
          for name in ('tio-server','tio-game-api','tio-portal','nginx','postgresql')}
assert set(services.values())=={'active'}
identity=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts'],text=True)
assert identity=='MainPID=443456\nNRestarts=0\n'
logs=subprocess.check_output(['journalctl','-u','tio-server','--since','@'+str(int((backup/'deployment.json').stat().st_mtime)),
                              '--no-pager'],text=True)
assert 'database or disk is full' not in logs and 'Server startup/runtime failure' not in logs
v=__import__('os').statvfs('/')
assert v.f_bavail*v.f_frsize>4*1024**3
print(json.dumps(dict(passed=True,source_sha256=expected,config_preserved=True,integrity='ok',
    mine_locations=[13,14,15,16],services=services,accounts=accounts,clans=clans,
    no_unplanned_restart=True,new_storage_errors=False,available_bytes=v.f_bavail*v.f_frsize),indent=2))
