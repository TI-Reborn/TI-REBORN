"""Read only the requested player_two roster and recovery state on hosting."""
import json
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/recovery-roster-20261017'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
CODE=r'''
import hashlib,json,sqlite3,time
from pathlib import Path
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_list import decode_item_list
from tio.passive_stats import project_saved_pet
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 names=[r[0] for r in db.execute("SELECT login FROM accounts WHERE lower(login) IN ('player_two','playertwo')")]
 assert names,'Requested account not found'
 owners=[]
 for name in names:
  owners.extend([name]+[r[0] for r in db.execute('SELECT DISTINCT account FROM owned_pets WHERE account LIKE ?',('@character:'+name+':%',))])
 result=dict(time=time.time(),accounts=names,owners=owners,pets=[],read_only=True)
 for account in owners:
  for identity,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)):
   base=decode_pet_info(raw,human_equipment=bool(human));effective=project_saved_pet(db,account,identity,raw,bool(human))
   pet=decode_pet_info(effective,human_equipment=bool(human));inv_owner,items,_=decode_item_list(inventory)
   fields={k:(v.hex() if isinstance(v,bytes) else v) for k,v in pet.fields.items()}
   stable={k:v for k,v in fields.items() if k!='0x8c4ab1'}
   recovery=db.execute('SELECT stamp,hp,maximum,paused FROM pet_recovery WHERE account=? AND pet_id=?',(account,identity)).fetchone()
   result['pets'].append(dict(account=account,id=identity,packet_id=pet.fields['0x8c43eb'],inventory_owner=inv_owner,
    human=bool(human),name=pet.fields['0x8c4489'].decode('cp1251'),hp=pet.fields['0x8c4ab1'],maximum=pet.fields['0x8c4a07'],
    stable_sha256=hashlib.sha256(json.dumps(stable,sort_keys=True).encode()).hexdigest(),
    inventory_sha256=hashlib.sha256(inventory).hexdigest(),base_packet_hex=raw.hex(),projected_packet_hex=effective.hex(),
    inventory_packet_hex=inventory.hex(),fields=fields,recovery=recovery,
    equipped=[dict(instance=i.instance_id,template=i.template_id,slot=i.slot) for i in items if i.equipped]))
 result['runtime_sha256']={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in ('tio/battle_recovery.py','tio/passive_stats.py','tio/equipment_bonuses.py','tools/loopback_exchange.py')}
print(json.dumps(result,ensure_ascii=True))
'''


def snapshot(label):
    REPORT.mkdir(parents=True,exist_ok=True)
    result=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -'],input=CODE,capture_output=True,text=True,encoding='utf-8',timeout=40)
    if result.returncode:
        (REPORT/'inspection-error.log').write_text(result.stderr,encoding='utf-8')
        raise RuntimeError('Read-only player_two inspection failed; see private local diagnostic')
    data=json.loads(result.stdout);(REPORT/(label+'.json')).write_text(json.dumps(data,ensure_ascii=True,indent=2))
    print(json.dumps(dict(report=label,pets=[{k:p[k] for k in ('id','name','hp','maximum','equipped')} for p in data['pets']],read_only=True),ensure_ascii=True))
    return data


if __name__=='__main__':snapshot('observation-'+str(int(time.time())))
