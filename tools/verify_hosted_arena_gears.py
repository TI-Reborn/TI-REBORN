"""Two fresh accounts on public encrypted TCP; no graphical-client claim."""
from verify_hosted_character_onboarding import *
import socket,subprocess,shlex,struct
from tio.protocol.ranked import decode_gears


def main():
    host='185.184.42.88';prefix='qg'+secrets.token_hex(4)
    names=[prefix+c for c in 'ab'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,passed=False,method=__doc__,checks=[],fixture='Only fresh QA accounts moved to Denver/New York and set to level4; snapshot after normal login synchronizes XP/rank')
    def remote(code,payload=names):
        p=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,encoding='utf-8',check=True)
        return json.loads(p.stdout) if p.stdout.strip() else None
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        s=socket.create_connection((host,port),timeout=15);case.clients.append(s);return s
    case.connect=connect
    def close():
        for s in case.clients:s.close()
        case.clients=[]
        time.sleep(1)
    def enter(i):
        p=case.handoff(case.begin(names[i],passwords[i]));case.enter(p,names[i]);return p
    try:
        report['backup']=remote('''
import json,sys,sqlite3,pathlib,tempfile
from server.accounts import Accounts
pairs=json.load(sys.stdin)
assert len(pairs)==2 and all(n.startswith('qg') and len(n)==11 for n,p in pairs)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-arena-gears-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:src.backup(dst)
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in pairs:a.create(n,p,character=n)
print(json.dumps(str(folder)))
''',list(zip(names,passwords)))
        for i in (0,1):
            p=enter(i);p.send(b'\x50\x03');assert decode_gears(p.until(b'\xc6\x18'))
        close()
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.locations import LocationStore,center
names=json.load(sys.stdin)
assert len(names)==2 and all(n.startswith('qg') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n,t in zip(names,(2,5)):
  raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]
  pet=decode_pet_info(raw,human_equipment=True)
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4})),n))
  LocationStore._save(db,n,t,*center(t))
''')
        def saved():
            return remote('''
import json,sys,sqlite3
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 print(json.dumps({n:dict(pets=[(i,p.hex(),v.hex()) for i,p,v in db.execute('SELECT pet_id,pet_packet,inventory_packet FROM owned_pets WHERE account=?',(n,))],wallet=db.execute('SELECT * FROM wallets WHERE account=?',(n,)).fetchall()) for n in names}))
''')
        peers=[enter(i) for i in (0,1)];before=saved();catalogues=[]
        for i,p in enumerate(peers):
            for _ in range(2):
                p.send(bytes((0x50,(2,5)[i])));ids=decode_gears(p.until(b'\xc6\x18'))
                assert 301 in ids;catalogues.append(ids);case.ping(p)
            for request in (b'\xc6\x02',b'\xc6\x20'):
                p.send(request);assert decode_gears(p.until(b'\xc6\x18'))==ids
                assert p.until(b'\xc6\x03').startswith(b'\xc6\x03');case.ping(p)
            p.send(b'\xc6\x21'+bytes(2)+struct.pack('<III',1,1,0)+b'\0')
            assert p.until(b'\xc6\x03').startswith(b'\xc6\x03');case.ping(p)
            p.send(b'\xc6\x23');assert p.until(b'\xc6\x06')==b'\xc6\x06';case.ping(p)
        assert len(set(catalogues))==1
        close()
        for i in (0,1):
            p=enter(i);p.send(bytes((0x50,(2,5)[i])))
            assert decode_gears(p.until(b'\xc6\x18'))==catalogues[0];case.ping(p)
        close();assert saved()==before,'Catalogue requests modified saved equipment or wallet'
        report.update(passed=True,templates=len(catalogues[0]))
        report['checks']=['Two authenticated accounts: Reservation, then Denver and New York',
            'Town-ready, repeated opening, C6/02 and C6/20 all deliver nonempty catalogue',
            'Each account can queue its saved fighter and cancel independently',
            'Relogin delivers catalogue again; saved pets, inventories and wallets unchanged']
        print(json.dumps(report))
    finally:
        close()
        (ROOT/'reports/arena-loading/hosted-tcp.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
