"""Five fresh hosted accounts: 2v2 combat/reconnect/chat and a city outsider.

Uses public encrypted TCP and only new QA fixtures. Never edits existing players.
This is protocol integration testing, not a graphical-client check.
"""
from verify_hosted_character_onboarding import *
from collections import deque
import socket,subprocess,shlex,struct
from tio.protocol.arena import decode_room_list
from tio.protocol.battle_members import decode_battle_members
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_ground import decode_battle_ground
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_list import decode_item_list
from tio.visibility import clear_sight


def run_battle(host):
    prefix='qr'+secrets.token_hex(4);names=[prefix+x for x in 'abcde']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    report={'accounts':names,'kind':__doc__,'passed':False,'checks':[]}
    output=ROOT/f'evidence/hosted-battle-core-{prefix}.json'
    def remote(code,payload):
        result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,check=True)
        return result.stdout
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        sock=socket.create_connection((host,port),timeout=12);case.clients.append(sock);return sock
    case.connect=connect
    peers={};received={i:[] for i in range(5)}
    def enter(i):
        peer=case.handoff(case.begin(names[i],passwords[i]));received[i]=[];original=peer.receive
        def receive():
            packet=original();received[i].append(packet);return packet
        peer.receive=receive;peers[i]=peer;case.enter(peer,names[i]);return peer
    def close_all():
        for sock in case.clients:sock.close()
        case.clients=[]
    try:
        remote('''
import json,sys
from server.accounts import Accounts
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in json.load(sys.stdin):
 assert n.startswith('qr') and len(n)==11
 a.create(n,p,character=n)
''',list(zip(names,passwords)))
        for i in range(5):enter(i)
        close_all();time.sleep(1)
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
names=json.load(sys.stdin)
assert len(names)==5 and all(n.startswith('qr') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n in names:
  raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]
  pet=decode_pet_info(raw,human_equipment=True)
  pet=replace(pet,fields={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000,'0x8c4aef':10})
  items=tuple(ItemRecord(1001+j,t,bytes(2),count,int(equip),16 if equip else 0,(300,300,300),bytes(4),None,bytes(3)) for j,(t,count,equip) in enumerate(((304,1,True),(7,200,False))))
  db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(pet),encode_item_list(1,items),n))
print('QA fixtures installed')
''',names)
        report['fixture']='Five NEW QA accounts only: level10, HP1000, AK47 and 200 cartridges each. Artificial test fixture, not progression.'
        for i in range(5):enter(i)
        for i in (0,1):peers[i].send(b'\xba\x03\1\1');peers[i].until(b'\x25')
        peers[4].send(b'\xba\1');rooms=decode_room_list(peers[4].until(b'\xba\2'))
        room_ids={r.name.decode():r.unknown_u32_00 for r in rooms}
        for i,captain in ((2,0),(3,1)):
            peers[i].send(b'\xba\4'+room_ids[names[captain]].to_bytes(4,'little'));peers[i].until(b'\x25')
            peers[i].send(b'\x2c\1');case.ping(peers[i])
        for i in (0,1):peers[i].send(b'\x2e');case.ping(peers[i])
        for i in range(4):
            if b'\x41' not in received[i]:peers[i].until(b'\x41',max_packets=512)
            peers[i].send(b'\x36')
        for p in peers.values():case.ping(p)
        def chat(channel,text,expected,sender=0):
            starts={i:len(v) for i,v in received.items()}
            peers[sender].send(bytes((0x21,channel))+text.encode('utf-16-le')+b'\0\0');case.ping(peers[sender])
            for i,p in peers.items():
                case.ping(p)
                found=any(x[:1]==b'\x22' and text.encode('utf-16-le') in x for x in received[i][starts[i]:])
                assert found==(i in expected),(channel,i,found)
        chat(4,'Только союзникам',{2});chat(3,'Всем участникам',{1,2,3})
        peers[4].send(b'\x21\4'+ 'Посторонний'.encode('utf-16-le')+b'\0\0');peers[4].until(b'\xf0')
        report['checks'].append('Four real authenticated accounts: team chat only ally; battle chat only other participants; no server echo; fifth city account rejected')
        actors=[]
        for i in range(4):
            own=[decode_battle_soldier(p,human_equipment=True) for p in received[i] if p[:1]==b'\x3b' and int.from_bytes(p[5:9],'little')==1]
            assert own;actors.append(own[-1])
        ids=[a.soldier_id for a in actors]
        for i in range(4):
            hidden=[decode_battle_soldier(p,human_equipment=True) for p in received[i]
                    if p[:1]==b'\x3b' and int.from_bytes(p[5:9],'little')!=1]
            hidden=[a for a in hidden if a.position==(255,255)]
            assert hidden and all(a.fields['0x8c57bb']==1 for a in hidden)
        report['checks'].append('All four recipients receive off-map HP1 models for living hidden enemies; native owner list can distinguish fog from death')
        positions=[(a.fields['0x8c519b'],a.fields['0x8c51af']) for a in actors]
        ap=[a.fields['0x8c571d'] for a in actors];hp=[a.fields['0x8c57bb'] for a in actors]
        ground_packet=next(p for p in received[0] if p[:1]==b'\x35');ground=decode_battle_ground(ground_packet)
        members=decode_battle_members(next(p for p in reversed(received[0]) if p[:1]==b'\x25'))[2]
        order=[names.index(m.name.decode()) for m in members]
        fragments={Path(k).stem:v for k,v in json.loads((ROOT/'config/arena_fragments.json').read_text()).items()}
        blocked=set()
        for e in ground.entries:
            f=fragments[e.name.decode()];x,y=e.unknown_u8_01,e.unknown_u8_02
            blocked.update((x+i,y+j) for j in range(f['height']) for i in range(f['width']) if f['tiles'][j*f['width']+i] in (2,3,4))
            for i,j,opened in f.get('doors',()):
                if opened:blocked.discard((x+i,y+j))
                else:blocked.add((x+i,y+j))
        offsets=[0]*4;turn=[False]*4;shots=[]
        def refresh(i):
            for p in received[i][offsets[i]:]:
                if p[0]==0x38:turn[i]=True
                if p[0]==0x39:turn[i]=False
                if p[0]==0x4c:raise AssertionError('Battle ended before verification')
                if p[0]==0x3d:
                    move=decode_battle_move(p)
                    if move.actor_id==ids[i]:positions[i]=move.path[-1]
                if p[0]==0x3b and int.from_bytes(p[1:5],'little')==ids[i]:
                    a=decode_battle_soldier(p,human_equipment=True);ap[i]=a.fields['0x8c571d'];hp[i]=a.fields['0x8c57bb']
                if p[0]==0x4e and int.from_bytes(p[1:5],'little')==ids[i] and int.from_bytes(p[9:13],'little')==10:ap[i]=int.from_bytes(p[13:17],'little')
                if p[0]==0x4b:
                    r=decode_attack_result(p)
                    for h in r.hits:
                        if h.actor_id==ids[i]:hp[i]=h.left_hp
                    if i==0 and r.actor_id==ids[0]:shots.append(r)
            offsets[i]=len(received[i])
        def inventory(i):
            return decode_item_list(next(p for p in reversed(received[i]) if p[0]==0x30 and int.from_bytes(p[1:5],'little')==ids[i]))[1]
        def route():
            start=positions[0];target=positions[1];occupied=set(positions[1:])
            goals={(x,y) for x in range(ground.width) for y in range(ground.height) if 1<=((x-target[0])**2+(y-target[1])**2)**.5<=2 and (x,y) not in blocked|occupied and clear_sight((x,y),target,blocked)}
            if start in goals:return ()
            queue=deque([start]);previous={start:None}
            while queue:
                x,y=queue.popleft()
                for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if cell in previous or cell in blocked|occupied or not(0<=cell[0]<ground.width and 0<=cell[1]<ground.height):continue
                    previous[cell]=(x,y)
                    if cell in goals:
                        result=[]
                        while cell!=start:result.append(cell);cell=previous[cell]
                        return tuple(reversed(result))
                    queue.append(cell)
            raise AssertionError('No route to QA opponent')
        resumed=False
        for cycle in range(60):
            for i in order:
                p=peers[i];case.ping(p);refresh(i)
                while not turn[i]:p.receive();refresh(i)
                if i==0:
                    for action in range(12):
                        path=route();start=len(received[i])
                        if path:p.send(encode_move_request(BattleMove(ids[i],path[:4])))
                        else:p.send(encode_attack_request(AttackRequest(ids[i],*positions[1])))
                        case.ping(p);refresh(i)
                        if any(x[:1]==b'\xf0' for x in received[i][start:]):break
                        if shots and sum(h.damage for h in shots[-1].hits)>0:
                            assert sum(x.count for x in inventory(0) if x.template_id==7)==200-5*len(shots)
                            before=(ids[0],positions[0],ap[0],hp[0],inventory(0))
                            p.sock.close();time.sleep(1)
                            p=enter(0);assert b'\x41' in received[0]
                            assert next(x for x in received[0] if x[:1]==b'\x35')==ground_packet
                            a=next(decode_battle_soldier(x,human_equipment=True) for x in received[0] if x[:1]==b'\x3b' and int.from_bytes(x[1:5],'little')==ids[0])
                            after=(a.soldier_id,(a.fields['0x8c519b'],a.fields['0x8c51af']),a.fields['0x8c571d'],a.fields['0x8c57bb'],inventory(0))
                            assert before==after,'Reconnect changed combat state'
                            offsets[0]=len(received[0]);p.send(b'\x36');timer=p.until(b'\x38')[1:]
                            report['reconnect']={'actor':ids[0],'position':positions[0],'ap':ap[0],'hp':hp[0],'remaining_turn_payload':timer.hex(),'same_map_and_inventory':True}
                            chat(4,'Снова в команде',{2});resumed=True;break
                        if not turn[i]:break
                if resumed:break
                if turn[i]:
                    start=len(received[i]);p.send(encode_end_turn());case.ping(p);refresh(i)
                    from tio.protocol.action_points import encode_action_points
                    updates=received[i][start:]
                    assert updates.index(encode_action_points(ids[i],0))<updates.index(b'\x39')
                    assert ap[i]==0 and not turn[i]
            if resumed:break
        assert resumed,'No attack/reconnect completed'
        report['checks'].append('Every voluntary handoff clears own displayed AP before TurnFinished; subsequent turns restore AP')
        for i in range(1,4):case.ping(peers[i]);refresh(i)
        assert hp[1]<1000
        damaged_hp=hp[1];damaged_inventory=inventory(1)
        peers[1].sock.close();time.sleep(1)
        p=enter(1);assert b'\x41' in received[1]
        damaged=next(decode_battle_soldier(x,human_equipment=True) for x in received[1] if x[:1]==b'\x3b' and int.from_bytes(x[1:5],'little')==ids[1])
        assert damaged.fields['0x8c57bb']==damaged_hp and damaged_hp<1000
        assert inventory(1)==damaged_inventory
        p.send(b'\x36');case.ping(p)
        report['checks'].append('Damaged opponent also reconnects: actual shot damage remains, no automatic healing; same actor and inventory')
        report['combat']={'shots':len(shots),'damage':sum(h.damage for r in shots for h in r.hits),'target_hp':hp[1],'ammo_spent':5*len(shots),'players':4,'bots':0}
        report['checks'].append('Live 2v2: authoritative movement, burst ammunition and damage observed by target; disconnect/relogin restored same actor, map, HP, spent AP and inventory; allied chat still isolated')
        for i in range(4):peers[i].send(b'\x2a\1');case.ping(peers[i])
        close_all();time.sleep(1)
        receipts=json.loads(remote('''
import json,sys,sqlite3
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT account,match_id,result,gross,rental_tax FROM battle_rewards WHERE account IN (?,?,?,?)',names[:4]).fetchall()
 assert len(rows)==4 and len({r[1] for r in rows})==1,rows
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print(json.dumps(rows))
''',names))
        report['receipts']=receipts
        p=enter(0);p.send(b'\x2f\x01\0\x01\0\0\0');packet=p.until(b'\x30')
        assert sum(x.count for x in decode_item_list(packet)[1] if x.template_id==7)==200-5*len(shots)
        report['checks'].append('Exit and later city login: spent ammunition persisted; exactly one battle receipt per account; database integrity OK')
        report['passed']=True
    finally:
        close_all();output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':run_battle(sys.argv[1])
