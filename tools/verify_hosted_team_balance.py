"""Public encrypted TCP: unequal selected squads enter with equal numbers.

Fresh QA accounts own three human fixtures each. Selection, matchmaking,
loading, turns and exit use normal public game packets. Only these accounts'
pre-match recovery and initial recruit fixtures use the account stores.
This is not graphical-client validation and changes no production code.
"""
from verify_hosted_character_onboarding import *
from collections import Counter
import hashlib,shlex,socket,subprocess
from tio.protocol.arena import decode_battle_settings_body
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_turn import encode_end_turn,turn_seconds
from tio.protocol.pet_state import encode_squad_slot


def main():
    host='185.184.42.88';prefix='qb'+secrets.token_hex(4)
    names=[prefix+c for c in 'ab'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,passed=False,method=__doc__,cases=[])
    folder=ROOT/'reports/team-balance';folder.mkdir(parents=True,exist_ok=True)
    def remote(code,payload=names):
        r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,encoding='utf-8',check=True)
        return json.loads(r.stdout) if r.stdout.strip() else None
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    peers={};received={0:[],1:[]}
    def connect(port):
        s=socket.create_connection((host,port),timeout=15);case.clients.append(s);return s
    case.connect=connect
    def close():
        for s in case.clients:s.close()
        peers.clear();case.clients=[];time.sleep(1)
    def enter(i):
        p=case.handoff(case.begin(names[i],passwords[i]));p.sock.settimeout(15)
        original=p.receive;received[i]=[]
        def receive():
            packet=original();received[i].append(packet);return packet
        p.receive=receive;peers[i]=p;case.enter(p,names[i]);return p
    def command(i,packet):peers[i].send(packet);case.ping(peers[i])
    def selection():
        return remote('''
import json,sys
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info
names=json.load(sys.stdin)
assert all(n.startswith('qb') and len(n)==11 for n in names)
store=OwnedPetStore('/var/lib/tio-server/reservation.sqlite3')
print(json.dumps([[(i,decode_pet_info(p,human_equipment=True).fields['0x8c44a6'])
 for i,p,_ in store.list(n)] for n in names]))
''')
    active=False
    try:
        report['inspection']=remote('''
import json,sys,pathlib,sqlite3,tempfile,hashlib,subprocess
from server.accounts import Accounts
pairs=json.load(sys.stdin);assert len(pairs)==2 and all(n.startswith('qb') and len(n)==11 for n,p in pairs)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-team-balance-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:
 assert src.execute('PRAGMA integrity_check').fetchone()[0]=='ok';src.backup(dst)
 count=src.execute('SELECT count(*) FROM accounts').fetchone()[0]
files=['server/team_arena.py','tio/team_lobbies.py','tio/team_scene.py','tio/matchmaking.py']
hashes={f:hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest() for f in files}
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in pairs:a.create(n,p,character=n)
print(json.dumps(dict(backup=str(folder),accounts=count,hashes=hashes)))
''',list(zip(names,passwords)))
        assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in report['inspection']['hashes'].items())
        for i in (0,1):enter(i)
        close()
        remote('''
import json,sys
from dataclasses import replace
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
names=json.load(sys.stdin);assert all(n.startswith('qb') and len(n)==11 for n in names)
store=OwnedPetStore('/var/lib/tio-server/reservation.sqlite3')
for n in names:
 rows=store.list(n);assert len(rows)==1
 pet=decode_pet_info(rows[0][1],human_equipment=True)
 for i in (2,3):
  fields={**pet.fields,'0x8c43eb':i,'0x8c44a6':0,'0x8c4489':('QA reserve '+str(i)).encode()}
  store.ensure(n,encode_pet_info(replace(pet,fields=fields)),encode_item_list(i,()),human=True)
''')
        for counts in ((1,3),(2,3),(3,3)):
            remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
names=json.load(sys.stdin);assert all(n.startswith('qb') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n in names:
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(n,)).fetchone()
  for i,p in db.execute('SELECT pet_id,pet_packet FROM owned_pets WHERE account=?',(n,)).fetchall():
   pet=decode_pet_info(p,human_equipment=True)
   packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4ab1':pet.fields['0x8c4a07']}))
   db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,n,i))
''')
            for i in (0,1):
                enter(i)
                for actor in range(1,counts[i]+1):command(i,encode_squad_slot(actor,actor))
                command(i,b'\xba\x03\x01\x01')
                if not any(p[0]==0x25 for p in received[i]):peers[i].until(b'\x25')
            before=selection();starts={i:len(received[i]) for i in (0,1)}
            for i in (0,1):command(i,b'\x2e')
            active=True;admitted=min(counts);grounds=[]
            for i in (0,1):
                if not any(p==b'\x41' for p in received[i][starts[i]:]):peers[i].until(b'\x41',max_packets=512)
                packets=received[i][starts[i]:]
                settings=decode_battle_settings_body(next(p[1:] for p in reversed(packets) if p[0]==0x6c))
                assert (settings.mode,settings.players_count,settings.soldiers_count,settings.turn_seconds)==(1,4,admitted,turn_seconds(admitted))
                actors={a.soldier_id:a for p in packets if p[0]==0x3b for a in [decode_battle_soldier(p,human_equipment=True)]}
                assert len(actors)==4*admitted
                assert set(Counter(a.owner_id for a in actors.values()).values())=={admitted}
                assert sum(a.owner_id==1 for a in actors.values())==admitted
                grounds.append(next(p for p in packets if p[0]==0x35))
            assert grounds[0]==grounds[1]
            for i in (0,1):command(i,b'\x36')
            if not any(p[0]==0x38 for p in received[0][starts[0]:]):peers[0].until(b'\x38',max_packets=512)
            command(0,encode_end_turn())
            if not any(p[0]==0x38 for p in received[1][starts[1]:]):peers[1].until(b'\x38',max_packets=512)
            for i in (0,1):command(i,b'\x2a\x01')
            active=False;close()
            assert selection()==before,'Match changed selected reserve fighters'
            report['cases'].append(dict(selected=counts,admitted_per_player=admitted,total_actors=4*admitted,
                humans=2,bots=2,shared_scene=True,both_human_turns=True,selection_preserved=True))
        report['passed']=True
    finally:
        if active:
            for i in list(peers):
                try:command(i,b'\x2a\x01')
                except (OSError,EOFError,ValueError,AssertionError):pass
        close()
        (folder/'hosted-tcp.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))


if __name__=='__main__':main()
