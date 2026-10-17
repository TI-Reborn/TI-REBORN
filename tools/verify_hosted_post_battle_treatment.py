"""Two fresh QA accounts fight over public encrypted TCP and heal after Finish.
Only pre-match maximum HP is a QA fixture. Battle death comes from attack49.
No existing player records or live battle state are changed. Not GUI validation.
"""
from verify_hosted_character_onboarding import *
from collections import deque
from dataclasses import replace
import socket,subprocess,shlex,struct
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.system_message import encode_current_town
from tio.protocol.transport import encode_initial_frame
from tio.battle_recovery import CREDITS_PER_HP


def main():
    host='185.184.42.88';prefix='qt'+secrets.token_hex(4)
    names=[prefix+c for c in 'ab'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,passed=False,method=__doc__,checks=[])
    def remote(code,payload=names):
        result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,encoding='utf-8')
        if result.returncode:raise RuntimeError(result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    peers={};received={i:[] for i in range(2)}
    def connect(port):
        connection=socket.create_connection((host,port),timeout=15);case.clients.append(connection);return connection
    case.connect=connect
    def ping(peer):peer.send(b'\x70');assert peer.until(b'\x9e',max_packets=2048)==b'\x9e'
    case.ping=ping
    def close():
        for connection in case.clients:connection.close()
        case.clients=[];peers.clear();time.sleep(1)
    def enter(index):
        peer=case.handoff(case.begin(names[index],passwords[index]));original=peer.receive
        def receive():
            packet=original();received[index].append(packet);return packet
        peer.receive=receive;peers[index]=peer;case.enter(peer,names[index])
    def command(index,packet):peers[index].send(packet);ping(peers[index])
    def saved():
        return remote('''
import json,sys,sqlite3
from tio.protocol.pet_info import decode_pet_info
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 out=[]
 for n in names:
  i,h,p=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(n,)).fetchone()
  f=decode_pet_info(p,human_equipment=bool(h)).fields
  out.append(dict(hp=f['0x8c4ab1'],maximum=f['0x8c4a07'],credits=db.execute('SELECT credits FROM wallets WHERE account=?',(n,)).fetchone()[0]))
 print(json.dumps(out))
''')
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
  print(json.dumps(dict(match=b['match_id'],width=f.width,height=f.height,blocked=list(f.blocked),turn=None if turn is None else b['names'][turn[0]].decode(),
   actors=[dict(id=a.actor_id,account=b['reward_roster'][a.owner_id][0],x=a.x,y=a.y,hp=a.health,ap=a.action_points) for a in f._actors.values()])))
''')
    def approach(scene,actor,target):
        occupied={(r['x'],r['y']) for r in scene['actors'] if r['id']!=actor['id'] and r['hp']}
        blocked=set(map(tuple,scene['blocked']))|occupied;start=(actor['x'],actor['y'])
        goals={(target['x']+dx,target['y']+dy) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1))}
        previous={start:None};queue=deque([start]);goal=None
        while queue:
            cell=queue.popleft()
            if cell in goals:goal=cell;break
            for neighbour in ((cell[0]-1,cell[1]),(cell[0]+1,cell[1]),(cell[0],cell[1]-1),(cell[0],cell[1]+1)):
                if neighbour in previous or neighbour in blocked or not (0<=neighbour[0]<scene['width'] and 0<=neighbour[1]<scene['height']):continue
                previous[neighbour]=cell;queue.append(neighbour)
        if goal is None:return ()
        path=[]
        while goal!=start:path.append(goal);goal=previous[goal]
        return tuple(reversed(path))[:min(12,actor['ap'])]
    started=False
    try:
        report['qa_backup']=remote('''
import json,sys,sqlite3,tempfile,pathlib
from server.accounts import Accounts
pairs=json.load(sys.stdin);assert len(pairs)==2 and all(n.startswith('qt') and len(n)==11 for n,p in pairs)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-treatment-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:src.backup(dst)
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in pairs:a.create(n,p,character=n)
print(json.dumps(str(folder)))
''',list(zip(names,passwords)))
        for i in range(2):enter(i)
        for i in range(2):
            settings=next(p for p in received[i] if p[:2]==b'\xc8\x37')
            assert struct.unpack('<f',settings[2:6])[0]==CREDITS_PER_HP
        close()
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
names=json.load(sys.stdin);assert len(names)==2 and all(n.startswith('qt') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for index,n in enumerate(names):
  rows=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(n,)).fetchall();assert len(rows)==1
  i,h,p=rows[0];pet=decode_pet_info(p,human_equipment=bool(h));hp=85 if index==0 else 1000
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4a07':hp,'0x8c4ab1':hp})),n,i))
''')
        for i in range(2):enter(i);received[i].clear()
        for i in range(2):command(i,b'\xba\x03\x00\x01')
        started=True
        for i in range(2):
            if b'\x41' not in received[i]:peers[i].until(b'\x41',max_packets=512)
            command(i,b'\x36')
        victim_id=None
        for _ in range(50):
            for i in range(2):ping(peers[i])
            scene=state()
            if scene is None:break
            report['match']=scene['match']
            victim=next(a for a in scene['actors'] if a['account']==names[0]);victim_id=victim['id']
            attacker=next(a for a in scene['actors'] if a['account']==names[1])
            if scene['turn'] not in names:time.sleep(.15);continue
            index=names.index(scene['turn']);actor=victim if index==0 else attacker;target=attacker if index==0 else victim
            if abs(victim['x']-attacker['x'])+abs(victim['y']-attacker['y'])>1:
                path=approach(scene,actor,target)
                if path:command(index,encode_move_request(BattleMove(actor['id'],path)))
            elif index==1:
                for _ in range(attacker['ap']//4):
                    command(1,encode_attack_request(AttackRequest(attacker['id'],victim['x'],victim['y'])))
                    if state() is None:break
            if state() is not None:command(index,encode_end_turn())
            time.sleep(.15)
        for i in range(2):
            if not any(p[0]==0x4c for p in received[i]):peers[i].until(b'\x4c',max_packets=2048)
        before=saved();assert before[0]['hp']==0 and victim_id
        request=b'\x7c\x01'+struct.pack('<I',victim_id);peer=peers[0]
        peer.sock.sendall(encode_initial_frame(b'\x2a\x01',peer.outbound)+encode_initial_frame(request,peer.outbound))
        peer.until(encode_current_town(3),max_packets=2048)
        assets=decode_asset_count(peer.until(b'\xc8\x39',max_packets=2048))
        pet=decode_pet_info(peer.until(b'\x66',max_packets=2048),human_equipment=True)
        expected=before[0]['maximum']*CREDITS_PER_HP
        assert pet.fields['0x8c4ab1']==before[0]['maximum']
        assert assets.credits==before[0]['credits']-expected
        command(0,request);after=saved()
        assert after[0]['credits']==assets.credits and after[0]['hp']==after[0]['maximum']
        assert after[1]==before[1]
        report.update(cost=expected,before=before,after=after,shared_actor_id=victim_id)
        report['checks']=['Both accounts received the configured nonzero treatment tariff',
            'Natural attack killed the victim and both peers received battle results',
            'Native Finish order2A01 then7C in one TCP write revived the saved fighter and charged exactly the displayed tariff',
            'Retry charged nothing; other account health and wallet unchanged']
        report['passed']=True
    finally:
        if started:
            for i,peer in list(peers.items()):
                try:command(i,b'\x2a\x01')
                except (OSError,EOFError,ValueError,AssertionError):pass
        close()
        (ROOT/'reports/post-battle-treatment/hosted.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))


if __name__=='__main__':main()
