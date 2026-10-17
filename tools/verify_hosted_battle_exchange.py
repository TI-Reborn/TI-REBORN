"""Two fresh hosted accounts, each with two mercenaries, share a Team battle.

Original6E layout (empty opening hook, then native confirmation); public encrypted
TCP. QA fixtures only; no existing account modified. Not graphical validation.
"""
from verify_hosted_character_onboarding import *
import socket,subprocess,shlex
from tio.protocol.battle_exchange import BattleExchange,encode_exchange
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.item_list import decode_item_list
from tio.protocol.action_points import encode_action_points
from tio.protocol.battle_turn import encode_end_turn


def run(host):
    prefix='qx'+secrets.token_hex(4);names=[prefix+x for x in 'ab'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,scope=__doc__,passed=False,checks=[])
    def remote(code,payload):
        r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr)
        return r.stdout
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        s=socket.create_connection((host,port),timeout=15);case.clients.append(s);return s
    case.connect=connect;received=[[],[]];peers={}
    def enter(i):
        p=case.handoff(case.begin(names[i],passwords[i]));received[i]=[];original=p.receive
        def receive():
            packet=original();received[i].append(packet);return packet
        p.receive=receive;peers[i]=p;case.enter(p,names[i]);return p
    def close():
        for s in case.clients:s.close()
        case.clients=[]
    try:
        remote("""
import json,sys
from server.accounts import Accounts
for n,p in json.load(sys.stdin):
 assert n.startswith('qx') and len(n)==11
 Accounts('/var/lib/tio-server/reservation.sqlite3').create(n,p,character=n)
""",list(zip(names,passwords)))
        for i in range(2):enter(i)
        close();time.sleep(1)
        remote("""
import json,sys,sqlite3
from dataclasses import replace
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
names=json.load(sys.stdin);assert len(names)==2 and all(n.startswith('qx') and len(n)==11 for n in names)
path='/var/lib/tio-server/reservation.sqlite3';store=OwnedPetStore(path)
for n in names:
 _,raw,_=store.list(n)[0];p=decode_pet_info(raw,human_equipment=True)
 for identity in (1,2):
  f={**p.fields,'0x8c43eb':identity,'0x8c44a6':identity,'0x8c4489':('QA '+str(identity)).encode(),'0x8c4a07':1000,'0x8c4ab1':1000}
  entries=((1001,3,200),(1002,301,1),(1003,317,1)) if identity==1 else ((2001,3,10),(2002,208,1))
  items=tuple(ItemRecord(i,t,bytes(2),count,0,0,(123,200,300) if t in (301,208) else (0,0,0),bytes(4),None,bytes(3)) for i,t,count in entries)
  raw=encode_pet_info(replace(p,fields=f));bag=encode_item_list(identity,items)
  if identity==2:store.ensure(n,raw,bag,human=True)
  else:
   with sqlite3.connect(path) as db:db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(raw,bag,n))
""",names)
        for i in range(2):enter(i);peers[i].send(b'\xba\3\1\1');peers[i].until(b'\x25')
        for p in peers.values():p.send(b'\x2e')
        actors=[]
        for i,p in peers.items():
            p.until(b'\x41',max_packets=512)
            own=[decode_battle_soldier(x,human_equipment=True) for x in received[i] if x[0]==0x3b and int.from_bytes(x[5:9],'little')==1]
            assert len(own)==2;actors.append(own)
        for p in peers.values():p.send(b'\x36')
        peers[0].until(b'\x38',max_packets=512)
        def action(i,request):
            start=len(received[i]);peers[i].send(encode_exchange(request));case.ping(peers[i]);return received[i][start:]
        def bag(i,actor):
            packet=next(x for x in reversed(received[i]) if x[0]==0x30 and int.from_bytes(x[1:5],'little')==actor)
            return {v.instance_id:v for v in decode_item_list(packet)[1]}
        first,second=actors[0];a,b=first.soldier_id,second.soldier_id
        start,target=first.position,second.position
        assert max(abs(start[0]-target[0]),abs(start[1]-target[1]))<=2,(start,target)
        if max(abs(start[0]-target[0]),abs(start[1]-target[1]))==2:
            middle=((start[0]+target[0])//2,(start[1]+target[1])//2)
            peers[0].send(encode_move_request(BattleMove(a,(middle,))));case.ping(peers[0])
            assert any(x[0]==0x3d and decode_battle_move(x).actor_id==a and decode_battle_move(x).path[-1]==middle for x in received[0])
        request=BattleExchange(a,b,((2002,1),),((1001,7),(1002,1)))
        before={i:dict(bag(0,i)) for i in (a,b)}
        observer_start=len(received[1])
        opened=action(0,BattleExchange(a,b));assert not any(x[0]==0xf0 for x in opened)
        ap=next(int.from_bytes(x[13:17],'little') for x in reversed(opened) if x[:5]==b'\x4e'+a.to_bytes(4,'little') and int.from_bytes(x[9:13],'little')==10)
        replies=action(0,request);assert not any(x[0]==0xf0 for x in replies)
        assert encode_action_points(a,ap-1) in replies
        assert bag(0,a)[1001].count==193 and bag(0,b)[2001].count==17
        assert bag(0,b)[1002]==before[a][1002] and bag(0,a)[2002]==before[b][2002]
        saved_after={i:dict(bag(0,i)) for i in (a,b)}
        replay=action(0,request);assert any(x[0]==0xf0 for x in replay)
        assert encode_action_points(a,ap-1) in replay
        assert all(bag(0,i)==saved_after[i] for i in (a,b))
        case.ping(peers[1])
        assert not any(x[0]==0x30 and int.from_bytes(x[1:5],'little') in (a,b) for x in received[1][observer_start:])
        report['checks'].append('Shared Team: weapon/armor swapped, 7 ammo transferred and merged; durability preserved; exactly1AP; replay rejected; opponent receives no inventory')
        # A legitimately reopened reverse operation is distinct from replay.
        reverse=BattleExchange(b,a,((2002,1),),((1002,1),))
        action(0,BattleExchange(b,a));r=action(0,reverse);assert not any(x[0]==0xf0 for x in r)
        assert bag(0,a)[1002]==before[a][1002] and bag(0,b)[2002]==before[b][2002]
        # Invalidate an open dialog across a real TCP disconnect/relogin.
        action(0,BattleExchange(a,b));expected={i:dict(bag(0,i)) for i in (a,b)}
        peers[0].sock.close();time.sleep(1);enter(0)
        assert b'\x41' in received[0]
        peers[0].send(b'\x36');peers[0].until(b'\x38',max_packets=512)
        assert all(bag(0,i)==expected[i] for i in (a,b))
        rejected=action(0,BattleExchange(a,b,(),((1001,1),)))
        assert any(x[0]==0xf0 for x in rejected) and all(bag(0,i)==expected[i] for i in (a,b))
        report['checks'].append('Reopened reverse exchange works; reconnect retains both inventories and invalidates unconfirmed old dialog')
        # The other actual account gets its own turn and cannot access our bags.
        peers[0].send(encode_end_turn());peers[0].until(b'\x39')
        peers[1].until(b'\x38',max_packets=512)
        e=actors[1][0].soldier_id
        denied=action(1,BattleExchange(e,a))
        assert any(x[0]==0xf0 for x in denied)
        assert not any(x[0]==0x30 and int.from_bytes(x[1:5],'little') in (a,b) for x in denied)
        report['checks'].append('Foreign exchange rejected during the second real account own turn; no inventory disclosure')
        for p in peers.values():p.send(b'\x2a\1');case.ping(p)
        close();time.sleep(1)
        enter(0)
        for local in (1,2):
            peers[0].send(b'\x2f\1\0'+local.to_bytes(4,'little'));peers[0].until(b'\x30')
        city1,city2=bag(0,1),bag(0,2)
        assert city1[1001].count==193 and city2[2001].count==17
        assert city1[1002]==before[a][1002] and city2[2002]==before[b][2002]
        report['checks'].append('Exit and new city login preserve both inventories, quantities and original equipment durability')
        report['fixture']='Only two new QA accounts: two selected mercenaries each, HP1000 and loose test gear. Not a progression test.'
        report['passed']=True
    finally:
        close();(ROOT/f'evidence/hosted-battle-exchange-{prefix}.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run(sys.argv[1])
