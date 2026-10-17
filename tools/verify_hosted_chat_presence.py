"""Three fresh hosted accounts, public encrypted TCP; not graphical clients.

Only randomly named QA accounts are prepared/moved. A separate real 1B journey
checks arrival/leave updates; all seven towns are checked with fixture positions.
Run after a backed-up deployment, while no other gameplay sessions are active.
"""
from verify_hosted_character_onboarding import *
import shlex
import socket
import struct
import subprocess
from tio.locations import TOWNS,center


def run(host):
    prefix='qh'+secrets.token_hex(4);names=[prefix+c for c in 'abc']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    ssh=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host]
    report=dict(accounts=names,passed=False,kind=__doc__,checks=[],towns=[])
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]

    def remote(code,data):
        result=subprocess.run(ssh+['cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],
                              input=json.dumps(data),text=True,capture_output=True,check=True)
        return result.stdout

    def connect(port):
        sock=socket.create_connection((host,port),timeout=15);case.clients.append(sock);return sock
    case.connect=connect

    def login(i):
        peer=case.handoff(case.begin(names[i],passwords[i]));case.enter(peer,names[i]);return peer

    def snapshot(peer):
        # Long journeys enqueue movement/recovery updates on unpolled peers.
        peer.send(b'\x70');assert peer.until(b'\x9e',max_packets=2048)==b'\x9e'
        peer.send(b'\xc7\1');peer.until(b'\xc7\4')
        global_list=peer.until(b'\xc7\2');peer.until(b'\x51')
        return global_list,peer.until(b'\x4f')

    def expect(peer,local_names):
        deadline=time.monotonic()+8
        while True:
            global_list,local=snapshot(peer)
            if all((name.encode()+b'\0' in local)==(name in local_names) for name in names):break
            if time.monotonic()>deadline:raise AssertionError('Wrong local roster')
            time.sleep(.2)
        assert all(name.encode()+b'\0' in global_list for name in names),'Missing global player'
        return global_list,local

    prepare='''
import json,sys
from pathlib import Path
from server.accounts import Accounts
from tio.owned_pets import OwnedPetStore
d=json.load(sys.stdin);path='/var/lib/tio-server/reservation.sqlite3'
trial=json.loads(Path('evidence/owned_pet_trial.json').read_text())
for name,password in d:
 assert name.startswith('qh') and len(name)==11
 Accounts(path).create(name,password,character=name)
 OwnedPetStore(path).ensure(name,bytes.fromhex(trial['packet_hex']),bytes.fromhex(trial['inventory_packet_hex']),human=True)
'''
    position='''
import json,sys,sqlite3
from contextlib import closing
from tio.locations import LocationStore,center
path='/var/lib/tio-server/reservation.sqlite3';store=LocationStore(path)
with closing(sqlite3.connect(path)) as db,db:
 for name,town in json.load(sys.stdin):
  assert name.startswith('qh') and len(name)==11
  assert db.execute('SELECT 1 FROM accounts WHERE login=?',(name,)).fetchone()
  db.execute('DELETE FROM map_journeys WHERE account=?',(name,))
  store._save(db,name,town,*center(town))
'''
    try:
        remote(prepare,list(zip(names,passwords)))
        remote(position,list(zip(names,(3,3,9))))
        a,b,c=[login(i) for i in range(3)]
        expect(a,names[:2]);expect(b,names[:2]);expect(c,names[2:])
        report['checks'].append('Join: global across towns, local isolated, self included')

        # Exercise actual public travel, including the empty local list en route.
        b.send(b'\x1b'+struct.pack('<ii',*center(9)))
        b.until(b'\xf0\x61\0\0\0')
        expect(b,[]);expect(a,names[:1])
        deadline=time.monotonic()+40
        while True:
            _,local=snapshot(c)
            if names[1].encode()+b'\0' in local:break
            if time.monotonic()>deadline:raise AssertionError('Journey arrival not reflected')
            time.sleep(1)
        expect(a,names[:1]);expect(b,names[1:]);expect(c,names[1:])
        report['checks'].append('Native 1B journey: leave, empty local while travelling, arrival, global retained')

        for town in TOWNS:
            # Test positions only: scope is the three fresh QA accounts.
            other=9 if town==3 else 3
            remote(position,list(zip(names,(town,town,other))))
            expect(a,names[:2]);expect(b,names[:2]);expect(c,names[2:])
            report['towns'].append(town)
        report['checks'].append('Global/local list payloads and refresh in every supported town')

        from tio.protocol.chat import encode_message
        for channel in (0,6,8,12):
            text='Roster QA '+str(channel)
            a.send(bytes((0x21,channel))+text.encode('utf-16-le')+b'\0\0')
            assert b.until(b'\x22')==encode_message(channel,names[0].encode(),text)
        # Third account receives only the global message, not local/trade/help.
        assert c.until(b'\x22')==encode_message(12,names[0].encode(),'Roster QA 12')
        report['checks'].append('Message audiences agree with Location/Trade/Help/Global lists')

        b.sock.close()
        deadline=time.monotonic()+8
        while True:
            global_list,_=snapshot(c)
            if names[1].encode()+b'\0' not in global_list:break
            if time.monotonic()>deadline:raise AssertionError('Disconnected player remains globally')
            time.sleep(.2)
        b=login(1);expect(a,names[:2]);expect(c,names[2:])
        report['checks'].append('Disconnect reflected in other town; reconnect restores lists')
        report['passed']=True
    finally:
        for sock in case.clients:sock.close()
        (ROOT/'reports/chat-presence/hosted-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run(sys.argv[1])
