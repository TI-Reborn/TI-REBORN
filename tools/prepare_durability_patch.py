from pathlib import Path
import subprocess,json,hashlib,tarfile
root=Path(__file__).resolve().parents[1]
names=['tio/durability.py','tio/repair.py','tio/protocol/repair.py','tio/combat.py','tio/equipment.py','tio/enhancement.py','tio/battle_loot.py','tio/arena_service.py','server/battle_events.py','server/team_arena.py','tools/loopback_exchange.py']
script="""import json,hashlib,sqlite3
from pathlib import Path
from tio.protocol.item_list import decode_item_list
root=Path('/opt/tio-emulator')
names=NAMES
hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).exists() else None for n in names}
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
    zero=[];count=0
    for account,pet,packet in db.execute('select account,pet_id,inventory_packet from owned_pets'):
        for item in decode_item_list(packet)[1]:
            count+=1
            if item.unknown_words[0]==0 and item.template_id>=200 and item.template_id<400:zero.append([account,pet,item.instance_id,item.template_id,list(item.unknown_words),item.equipped])
print(json.dumps(dict(hashes=hashes,items=count,zero_equipment=zero)))
""".replace('NAMES',repr(names))
r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@185.184.42.88','cd /opt/tio-emulator && .venv/bin/python -'],input=script,text=True,capture_output=True,check=True)
report=json.loads(r.stdout);(root/'data/durability-remote-before.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
