"""Read-only hosted sources and anonymous repair-kit storage diagnostics."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/repair-warehouse-20261017'
REPORT=ROOT/'reports/repair-warehouse-20261017'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
CODE=r'''
import collections,hashlib,json,sqlite3,subprocess
from pathlib import Path
from tio.protocol.item_list import decode_item_list
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 result=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0])
 groups=collections.Counter()
 for account,key,packet in db.execute('SELECT account,instance_id,item_packet FROM warehouse_items'):
  for item in decode_item_list(packet)[1]:
   if item.template_id not in (17,18,19):continue
   place=db.execute('SELECT bucket,town FROM warehouse_places WHERE account=? AND instance_id=?',(account,key)).fetchone()
   town=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
   groups[(item.template_id,item.count,item.unknown_words,item.equipped,item.slot,item.unknown_bytes_02.hex(),item.unknown_bytes_03.hex(),place[0] if place else 'legacy',place[1] if place else None,town[0] if town else None)]+=1
 result['repair_kit_warehouse_groups']=[dict(template=k[0],quantity=k[1],durability=k[2],equipped=k[3],slot=k[4],flags=k[5],enhancements=k[6],bucket=k[7],stored_town=k[8],current_town=k[9],rows=v) for k,v in groups.items()]
 result['warehouse_rows_total']=db.execute('SELECT count(*) FROM warehouse_items').fetchone()[0]
result['service']=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()
manifest=Path('/var/www/tio-client/updates/manifest.json').read_bytes()
result['client_manifest_sha256']=hashlib.sha256(manifest).hexdigest()
result['client_version']=json.loads(manifest)['version']
print(json.dumps(result))
'''


def main():
    WORK.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    result=subprocess.run(SSH+["tar --exclude=__pycache__ --exclude='*.pyc' -czf - -C /opt/tio-emulator server tio tools config evidence"],capture_output=True,check=True,timeout=45)
    (WORK/'runtime-before.tar.gz').write_bytes(result.stdout)
    baseline=WORK/'baseline';baseline.mkdir(exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(result.stdout),mode='r:gz') as archive:archive.extractall(baseline,filter='data')
    hashes={p.relative_to(baseline).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in baseline.rglob('*') if p.is_file()}
    (REPORT/'baseline-sha256.json').write_text(json.dumps(hashes,indent=2))
    state=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -'],input=CODE,capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    report=json.loads(state.stdout)
    report.update(hosted_changes_made=False,local_differences=[n for n,h in hashes.items() if (ROOT/n).is_file() and hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h])
    (REPORT/'inspection.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
