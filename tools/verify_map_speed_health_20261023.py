"""Run read-only on the hosting server after disposable QA fixtures are removed."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

sys.path.insert(0,'/opt/tio-emulator')
sys.dont_write_bytecode=True
from tio import warehouse_completion as stock
from tio.warehouse import WarehouseStore
from tio.warehouse_resources import counts
from tio.durability import KITS

root=Path('/opt/tio-emulator')
expected={
    'tio/locations.py':'8c67cc57c7101e4d4ea770c833da4e67da1a76ecce810b388bae45d4206a3b99',
    'tio/warehouse_completion.py':'4f40218ddeb673f9688ab1339b4b96753717b24bf4c88d4a9e42c8c91978218b',
    'tio/warehouse_resources.py':'851dc8c4b7b2163a8c3c7deb41e60c53f31a2834cecbb90857cb2db4e686c418',
}
for name,digest in expected.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
from tio.locations import MAP_SPEED
from tio.party_travel import MAP_SPEED as PARTY_SPEED
assert MAP_SPEED==PARTY_SPEED==12
backup=Path('/root/tio-before-game-operations-map-speed-20261023')
receipt=json.loads((backup/'backup-manifest.json').read_text())
assert hashlib.sha256(Path('/etc/tio-server/server.toml').read_bytes()).hexdigest()==receipt['config_sha256']
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
    db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
    assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
    owners=[r[0] for r in db.execute('SELECT DISTINCT account FROM warehouse_items')]
    checked=0
    for owner in owners:
        items=WarehouseStore._read(db,owner)
        assert stock.read_scope(db,owner,items)==items
        repair=sum(i.count*i.unknown_words[0] for i in items.values() if i.template_id in KITS)
        upgrades=sum(i.count for i in items.values() if i.template_id==30)
        assert counts(db,owner)==(min(repair,0xffffffff),min(upgrades,0xffffffff))
        checked+=len(items)
    accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
    clans=db.execute('SELECT count(*) FROM clans').fetchone()[0]
    multi_town=db.execute("SELECT count(*) FROM (SELECT w.account FROM warehouse_items w JOIN warehouse_places p USING(account,instance_id) GROUP BY w.account HAVING count(DISTINCT p.town)>1)").fetchone()[0]
services={name:subprocess.check_output(['systemctl','is-active',name],text=True).strip()
          for name in ('tio-server','tio-game-api','tio-portal','nginx','postgresql')}
assert set(services.values())=={'active'}
identity=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts'],text=True)
assert 'NRestarts=0' in identity
logs=subprocess.check_output(['journalctl','-u','tio-server','--since','@'+str(int((backup/'deployment.json').stat().st_mtime)),
                              '--no-pager'],text=True)
assert 'database or disk is full' not in logs and 'Server startup/runtime failure' not in logs
v=os.statvfs('/');available=v.f_bavail*v.f_frsize
assert available>4*1024**3
print(json.dumps(dict(passed=True,files=expected,config_preserved=True,integrity='ok',
    accounts=accounts,clans=clans,warehouse_owners=len(owners),warehouse_items_checked=checked,
    owners_with_old_multiple_town_tags=multi_town,all_saved_items_accessible=True,
    all_saved_resource_counters_match=True,services=services,service_identity=identity,
    map_speed=MAP_SPEED,party_speed=PARTY_SPEED,new_storage_errors=False,available_bytes=available),indent=2))
