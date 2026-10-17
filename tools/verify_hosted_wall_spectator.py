"""Three fresh TCP accounts: kill the sole fighter, spectate, leave.

Only pre-match saved HP is a QA fixture. Death comes from ordinary attack49;
live battle state, damage and results are never changed via the database.
No graphical-client verification is claimed.
"""
from verify_hosted_character_onboarding import *
from collections import deque
import socket,subprocess,shlex
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.arena import decode_room_list
from tio.protocol.system_message import encode_current_town


def main():
    host='185.184.42.88';prefix='qs'+secrets.token_hex(4)
    names=[prefix+c for c in 'abc'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,passed=False,method=__doc__,checks=[])
    def remote(code,payload=names):
        r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    peers={};received={i:[] for i in range(3)}
    def connect(port):
        s=socket.create_connection((host,port),timeout=15);case.clients.append(s);return s
    case.connect=connect
    def ping(peer):
        peer.send(b'\x70')
        assert peer.until(b'\x9e',max_packets=2048)==b'\x9e'
    case.ping=ping
    def close():
        for s in case.clients:s.close()
        case.clients=[];peers.clear();time.sleep(1)
    def enter(i):
        p=case.handoff(case.begin(names[i],passwords[i]));original=p.receive
        p.sock.settimeout(15)
        def receive():
            packet=original();received[i].append(packet);return packet
        p.receive=receive;peers[i]=p;case.enter(p,names[i]);return p
    def command(i,p):peers[i].send(p);case.ping(peers[i])
    def state(account=0):
        return remote('''
import json,sys,sqlite3
from tio.battle_snapshot import loads
account=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT payload FROM battle_checkpoints JOIN battle_checkpoint_members USING(match_id) WHERE account=?',(account,)).fetchone()
 if row is None:print('null')
 else:
  b=loads(row[0])[0]['battle'];f=b['field'];turn=b['arena']._turns.get(b['room'].room_id)
  print(json.dumps(dict(match=b['match_id'],width=f.width,height=f.height,blocked=list(f.blocked),
   turn=None if turn is None else b['names'][turn[0]].decode('ascii'),
   actors=[dict(id=a.actor_id,account=b['reward_roster'][a.owner_id][0] if a.owner_id in b['reward_roster'] else None,
    x=a.x,y=a.y,hp=a.health,ap=a.action_points) for a in f._actors.values()])))
''',names[account])
    def approach(s,a,target):
        occupied={(r['x'],r['y']) for r in s['actors'] if r['id']!=a['id'] and r['hp']}
        blocked=set(map(tuple,s['blocked']))|occupied;start=(a['x'],a['y'])
        goals={(target['x']+dx,target['y']+dy) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1))}
        previous={start:None};queue=deque([start]);goal=None
        while queue:
            p=queue.popleft()
            if p in goals:goal=p;break
            for cell in ((p[0]-1,p[1]),(p[0]+1,p[1]),(p[0],p[1]-1),(p[0],p[1]+1)):
                if cell in previous or cell in blocked or not (0<=cell[0]<s['width'] and 0<=cell[1]<s['height']):continue
                previous[cell]=p;queue.append(cell)
        if goal is None:return ()
        path=[]
        while goal!=start:path.append(goal);goal=previous[goal]
        return tuple(reversed(path))[:min(12,a['ap'])]
    started=False
    try:
        report['backup']=remote('''
import json,sys,sqlite3,tempfile,pathlib
from server.accounts import Accounts
pairs=json.load(sys.stdin);assert len(pairs)==3 and all(n.startswith('qs') and len(n)==11 for n,p in pairs)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-spectator-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:src.backup(dst)
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in pairs:a.create(n,p,character=n)
print(json.dumps(str(folder)))
''',list(zip(names,passwords)))
        for i in range(3):enter(i)
        close()
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
names=json.load(sys.stdin);assert len(names)==3 and all(n.startswith('qs') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for index,n in enumerate(names):
  rows=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(n,)).fetchall();assert len(rows)==1
  i,h,p=rows[0];pet=decode_pet_info(p,human_equipment=bool(h));hp=85 if index==0 else 1000
  f={**pet.fields,'0x8c4a07':hp,'0x8c4ab1':hp}
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(encode_pet_info(replace(pet,fields=f)),n,i))
''')
        for i in range(3):enter(i);received[i].clear()
        command(0,b'\xba\x03\x04\x01')
        if not any(p[0]==0x25 for p in received[0]):peers[0].until(b'\x25')
        command(2,b'\xba\x01')
        listing=peers[2].until(b'\xba\x02') if not any(p.startswith(b'\xba\x02') for p in received[2]) else next(p for p in received[2] if p.startswith(b'\xba\x02'))
        room=next(r.unknown_u32_00 for r in decode_room_list(listing) if r.name==names[0].encode())
        command(2,b'\xba\x04'+room.to_bytes(4,'little'));command(2,b'\x2c\x01')
        command(1,b'\xba\x03\x04\x01')
        command(0,b'\x2e');command(1,b'\x2e');started=True
        for i in range(3):
            if not any(p==b'\x41' for p in received[i]):peers[i].until(b'\x41',max_packets=512)
            command(i,b'\x36')
        dead=False
        for _ in range(40):
            for i in range(3):case.ping(peers[i])
            s=state();assert s
            victim=next(a for a in s['actors'] if a['account']==names[0])
            opponent=next(a for a in s['actors'] if a['account']==names[1])
            if victim['hp']==0:dead=True;report['match']=s['match'];report['dead_actor']=victim['id'];break
            if s['turn'] not in names:time.sleep(.15);continue
            i=names.index(s['turn'])
            if i==0:
                path=approach(s,victim,opponent)
                if path:command(0,encode_move_request(BattleMove(victim['id'],path)))
            elif i==1 and abs(victim['x']-opponent['x'])+abs(victim['y']-opponent['y'])==1:
                for _ in range(opponent['ap']//4):
                    command(1,encode_attack_request(AttackRequest(opponent['id'],victim['x'],victim['y'])))
                    update=state();victim=next(a for a in update['actors'] if a['account']==names[0])
                    if not victim['hp']:break
            command(i,encode_end_turn());time.sleep(.15)
        assert dead,'Could not obtain a natural combat death'
        for i in range(3):case.ping(peers[i])
        mark=len(received[0]);observed=0
        for _ in range(12):
            s=state();assert s and s['turn']!=names[0]
            assert next(a for a in s['actors'] if a['account']==names[2])['hp']>0
            for i in range(3):case.ping(peers[i])
            if s['turn'] in names[1:]:command(names.index(s['turn']),encode_end_turn());observed+=1
            time.sleep(.15)
            assert not any(p[0]==0x38 for p in received[0][mark:]),'Eliminated account still got YourTurn'
            if observed>=6:break
        assert observed>=6
        command(0,encode_end_turn())
        assert any(p.startswith(b'\xf0'+(394).to_bytes(4,'little')) for p in received[0][mark:]),'Spectator action was not rejected'
        command(0,b'\x2a\x01')
        assert state(2),'Leaving spectator ended the surviving ally\'s fight'
        town=encode_current_town(3)
        if town not in received[0][mark:]:peers[0].until(town)
        assert town in received[0][mark:]
        report['checks']=['Three real accounts; eliminated account admitted with exactly one fighter',
            'Ordinary attacks killed that fighter while its human ally remained alive',
            'Six later human turns skipped the eliminated account; no YourTurn packets',
            'Spectator turn action rejected; spectator left to town and ally battle continued']
        report['passed']=True
    finally:
        if started:
            for i,p in list(peers.items()):
                try:command(i,b'\x2a\x01')
                except (OSError,EOFError,ValueError,AssertionError):pass
        close()
        (ROOT/'reports/wall-disconnect/hosted-spectator.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))


if __name__=='__main__':main()
