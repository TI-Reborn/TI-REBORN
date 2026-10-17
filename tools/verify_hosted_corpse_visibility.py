"""Public mine entry with two fresh QA accounts; no graphical clients."""
from verify_hosted_character_onboarding import *
from tio.protocol.battle_soldier import decode_battle_soldier
import socket,subprocess


def remote(host,source):
    return subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
        'cd /opt/tio-emulator && .venv/bin/python -'],input=source,text=True,capture_output=True,check=True).stdout


def run(host):
    prefix='qv'+secrets.token_hex(4);names=[prefix+'a',prefix+'b'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,kind='public encrypted TCP; no graphical clients',passed=False,checks=[])
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        connection=socket.create_connection((host,port),timeout=15);case.clients.append(connection);return connection
    case.connect=connect
    remote(host,"from server.accounts import Accounts\na=Accounts('/var/lib/tio-server/reservation.sqlite3')\n"+
           '\n'.join('a.create('+repr(n)+','+repr(p)+')' for n,p in zip(names,passwords)))
    try:
        for name,password in zip(names,passwords):
            peer=case.handoff(case.begin(name,password));assert case.character_screen(peer)==()
            peer.send(encode_character_create(CharacterCreateRequest(name.encode(),0,(1,0,0,0))))
            assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
            peer.send(bytes.fromhex('1701000000'));assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
            peer.send(encode_request(1,bytes((1,5,1,3,0,0))));peer.until(b'\x10')
            peer.send(bytes.fromhex('1701000000'));assert peer.receive()[0]==0x18
            peer.send(b'\x19');peer.until(b'\x66');case.ping(peer)
        for connection in case.clients:connection.close()
        case.clients=[];time.sleep(1)
        # Prepare ONLY the two newly created QA squads for the level4 checkpoint.
        remote(host,"""import sqlite3
from tio.locations import LocationStore,center
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
path='/var/lib/tio-server/reservation.sqlite3'
locations=LocationStore(path)
with sqlite3.connect(path) as db:
    for account in ACCOUNTS:
        rows=list(db.execute('SELECT pet_id,pet_packet,human FROM owned_pets WHERE account=?',(account,)))
        assert len(rows)==1
        for identity,packet,human in rows:
            pet=decode_pet_info(packet,human_equipment=bool(human));pet.fields['0x8c4aef']=4
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(encode_pet_info(pet),account,identity))
        locations._save(db,account,13,*center(13))
""".replace('ACCOUNTS',repr(names)))
        peers=[]
        for name,password in zip(names,passwords):
            peer=case.handoff(case.begin(name,password));case.character_screen(peer)
            peer.send(bytes.fromhex('1701000000'));assert peer.receive()[0]==0x18
            peer.send(b'\x19');peer.until(b'\x66');case.ping(peer);peers.append(peer)
        for peer in peers:
            peer.send(b'\xb0\x14\x01');packets=[]
            while not packets or packets[-1]!=b'\x41':packets.append(peer.receive())
            soldiers=[decode_battle_soldier(p,human_equipment=True) for p in packets if p[0]==0x3b]
            enemies=[s for s in soldiers if s.fields['0x8c50fb']==100]
            assert len(enemies)==10
            hidden=[s for s in enemies if s.position==(255,255)]
            assert hidden and all(s.fields['0x8c57bb']==1 for s in hidden)
            assert len([s for s in soldiers if s.owner_id==1])==1
            report.setdefault('scenes',[]).append(dict(enemies=len(enemies),hidden=len(hidden)))
            peer.send(b'\x36');peer.until(b'\x38');case.ping(peer)
        report['checks']=['two accounts authenticate independently and enter hosted mines',
                          'all ten enemies registered; hidden coordinates masked as 255/255 and HP as alive bit',
                          'both scenes load and accept first turn; other account stays connected']
        report['passed']=True
    finally:
        for connection in case.clients:connection.close()
        (ROOT/f'evidence/hosted-corpse-visibility-{prefix}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':run(sys.argv[1])
