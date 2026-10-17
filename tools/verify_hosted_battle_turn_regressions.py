"""Public encrypted TCP with two fresh accounts, real moves and bot attacks.

Saved HP for these QA accounts is raised before the match to allow repeated
turns. No live battle, opponent action, damage or result is injected remotely.
This is a protocol integration test, not a graphical-client test.
"""
from verify_hosted_character_onboarding import *
from collections import deque
import socket,subprocess,shlex
from tio.protocol.hire import encode_hire_request
from tio.protocol.pet_state import encode_squad_slot
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_turn import encode_end_turn


def main():
    host='185.184.42.88';prefix='qv'+secrets.token_hex(4)
    names=[prefix+c for c in 'ab'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,passed=False,method=__doc__,checks=[],moves=0,attacks=0,turns=0)
    def remote(code,payload=names):
        r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    peers={};packets={0:[],1:[]};own={0:{},1:{}}
    def connect(port):
        s=socket.create_connection((host,port),timeout=15);case.clients.append(s);return s
    case.connect=connect
    def close():
        for s in case.clients:s.close()
        case.clients=[];peers.clear();time.sleep(1)
    def enter(i):
        p=case.handoff(case.begin(names[i],passwords[i]));original=p.receive
        def receive():
            packet=original();packets[i].append(packet)
            if packet[0]==0x3b:
                a=decode_battle_soldier(packet,human_equipment=int.from_bytes(packet[9:13],'little') in (1,2,6))
                if a.owner_id==1:
                    assert a.position!=(255,255),'Own fighter hidden by a foreign fog snapshot'
                    assert a.fields['0x8c57bb']>1,'Own fighter received fake HP=1'
                    own[i][a.soldier_id]=a
            if packet[0]==0x43:assert int.from_bytes(packet[1:5],'little') not in own[i],'Own fighter removed'
            if packet[0]==0x4b:report['attacks']+=1
            return packet
        p.receive=receive;peers[i]=p;case.enter(p,names[i]);return p
    def command(i,packet):
        peers[i].send(packet);case.ping(peers[i])
    def state():
        return remote('''
import json,sys,sqlite3
from tio.battle_snapshot import loads
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT payload FROM battle_checkpoints JOIN battle_checkpoint_members USING(match_id) WHERE account=?',(names[0],)).fetchone()
 if row is None:print('null')
 else:
  b=loads(row[0])[0]['battle'];f=b['field'];turn=b['arena']._turns.get(b['room'].room_id)
  print(json.dumps(dict(match=b['match_id'],width=f.width,height=f.height,blocked=list(f.blocked),
   turn=None if turn is None else b['names'][turn[0]].decode('ascii'),bots=len(b['bots']),
   actors=[dict(id=a.actor_id,account=b['reward_roster'][a.owner_id][0] if a.owner_id in b['reward_roster'] else None,
    side=f.teams[a.owner_id],x=a.x,y=a.y,hp=a.health,ap=a.action_points) for a in f._actors.values()])))
''')
    def retreat(s,a):
        occupied={(r['x'],r['y']) for r in s['actors'] if r['id']!=a['id'] and r['hp']}
        blocked=set(map(tuple,s['blocked']))|occupied;start=(a['x'],a['y'])
        previous={start:None};depth={start:0};queue=deque([start])
        while queue:
            x,y=queue.popleft()
            if depth[x,y]>=min(7,a['ap']):continue
            for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if cell in previous or cell in blocked or not (0<=cell[0]<s['width'] and 0<=cell[1]<s['height']):continue
                previous[cell]=(x,y);depth[cell]=depth[x,y]+1;queue.append(cell)
        enemies=[r for r in s['actors'] if r['side']!=a['side']]
        goal=max(previous,key=lambda p:min((p[0]-e['x'])**2+(p[1]-e['y'])**2 for e in enemies))
        path=[]
        while goal!=start:path.append(goal);goal=previous[goal]
        return tuple(reversed(path))
    started=False
    try:
        report['backup']=remote('''
import json,sys,sqlite3,tempfile,pathlib
from server.accounts import Accounts
pairs=json.load(sys.stdin);assert len(pairs)==2 and all(n.startswith('qv') and len(n)==11 for n,p in pairs)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-battle-turn-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:src.backup(dst)
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in pairs:a.create(n,p,character=n)
print(json.dumps(str(folder)))
''',list(zip(names,passwords)))
        for i in (0,1):
            enter(i);command(i,encode_hire_request(3));command(i,encode_squad_slot(2,2))
        close()
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
names=json.load(sys.stdin);assert len(names)==2 and all(n.startswith('qv') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n in names:
  for i,h,p in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(n,)).fetchall():
   pet=decode_pet_info(p,human_equipment=bool(h));f={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000}
   db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(encode_pet_info(replace(pet,fields=f)),n,i))
''')
        for i in (0,1):enter(i);command(i,b'\xba\x03\x01\x01')
        for i in (0,1):command(i,b'\x2e')
        started=True
        for i in (0,1):
            if not any(p==b'\x41' for p in packets[i]):peers[i].until(b'\x41',max_packets=512)
            command(i,b'\x36')
        time.sleep(.2);initial=state();assert initial and initial['bots']==2 and len(initial['actors'])==8
        report['match']=initial['match']
        for i in (0,1):assert len(own[i])==2 and {a.human_equipment for a in own[i].values()}=={True,False}
        for step in range(20):
            for i in (0,1):case.ping(peers[i])
            s=state();assert s,'Battle disappeared before verification'
            if s['turn'] not in names:time.sleep(.2);continue
            i=names.index(s['turn'])
            if step<8:
                for a in [a for a in s['actors'] if a['account']==names[i]]:
                    path=retreat(s,a)
                    if path:command(i,encode_move_request(BattleMove(a['id'],path)));report['moves']+=1
            command(i,encode_end_turn());report['turns']+=1;time.sleep(.2)
            if report['turns']>=10 and report['attacks']>=4:break
        for i in (0,1):case.ping(peers[i])
        assert report['moves']>=2 and report['turns']>=10 and report['attacks']>=1,report
        report['checks']=['Two real accounts each admitted with exactly a human and a dog; two shared team bots',
            'Real movement, skipped turns and bot attacks produced no hidden/removed own models or fake HP=1',
            'Both dogs remain registered for their owners across repeated turns']
        report['passed']=True
    finally:
        if started:
            for i,p in list(peers.items()):
                try:command(i,b'\x2a\x01')
                except (OSError,EOFError,ValueError,AssertionError):pass
        close()
        (ROOT/'reports/battle-turn-regressions/hosted-tcp.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))


if __name__=='__main__':main()
