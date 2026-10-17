"""Fresh QA saves and public encrypted TCP; no graphical-client claim."""
from verify_hosted_character_onboarding import *
import shlex
import socket
import subprocess


def run(host):
    prefix='ql'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    ssh=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host]
    def remote(code,data):
        return subprocess.run(ssh+['cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],
            input=json.dumps(data),text=True,capture_output=True,check=True).stdout
    fixture='''
import json,sys,sqlite3
from pathlib import Path
from dataclasses import replace
from server.accounts import Accounts
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.level_progression import FLOORS
from tio.appearance import starter
data=json.load(sys.stdin);path='/var/lib/tio-server/reservation.sqlite3'
for index,(name,password) in enumerate(data['accounts']):
 assert name.startswith('ql') and len(name)==11
 if data['create']:
  Accounts(path).create(name,password,character=name)
  raw=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex'])
  pet=starter(decode_pet_info(raw,human_equipment=True),1 if index==0 else 2)
 else:
  with sqlite3.connect(path) as db:raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()[0]
  pet=decode_pet_info(raw,human_equipment=True)
 level=(2 if index==0 else 5) if data['create'] else 3
 fields={**pet.fields,'0x8c4aef':level,'0x8c4b05':FLOORS[level-1]}
 slots=((101,1),(102,4),(103,8),(301,16),(302,128)) if data['create'] and index==0 else ((302,16),(301,128)) if not data['create'] else ()
 items=tuple(ItemRecord(800+i,t,bytes(2),1,1,s,(300,300,300),bytes(4),None,bytes(3)) for i,(t,s) in enumerate(slots))
 packet=encode_pet_info(replace(pet,fields=fields));inventory=encode_item_list(1,items)
 if data['create']:OwnedPetStore(path).ensure(name,packet,inventory,human=True)
 else:
  with sqlite3.connect(path) as db:db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(packet,inventory,name))
'''
    result=dict(accounts=names,passed=False,kind=__doc__,checks=[])
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        connection=socket.create_connection((host,port),timeout=15);case.clients.append(connection);return connection
    case.connect=connect
    try:
        remote(fixture,dict(accounts=list(zip(names,passwords)),create=True))
        peers=[];counts=[]
        for index,(name,password) in enumerate(zip(names,passwords)):
            peer=case.handoff(case.begin(name,password));peers.append(peer)
            entry=case.last_server_entry;counts.append(entry.unknown_u16_02)
            assert entry.unknown_u16_03==15
            shown=case.character_screen(peer)[0]
            assert shown.unknown_u8_02==(2 if index==0 else 5)
            assert tuple(shown.words[i] for i in (0,6,7,4,5))==((101,102,103,301,302) if index==0 else (0,0,0,0,0))
            assert shown.resource_type==index+1
        assert counts[1]==counts[0]+1
        result['counts']=counts;result['percentages']=[n*100//16 for n in counts]
        result['checks'].append('Two accounts: live online count, capacity16, independent level/equipment and sex')
        for peer in peers:peer.sock.close()
        time.sleep(1)
        remote(fixture,dict(accounts=[(names[0],passwords[0])],create=False))
        peer=case.handoff(case.begin(names[0],passwords[0]))
        assert case.last_server_entry.unknown_u16_02==counts[0]
        shown=case.character_screen(peer)[0]
        assert shown.unknown_u8_02==3
        assert tuple(shown.words[i] for i in (0,6,7,4,5))==(0,0,0,302,301)
        result['checks'].append('Reconnect: disconnected accounts released, new level3, removed armor and swapped hands')
        result['passed']=True
    finally:
        for connection in case.clients:connection.close()
        (ROOT/f'evidence/hosted-login-display-{prefix}.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':run(sys.argv[1])
