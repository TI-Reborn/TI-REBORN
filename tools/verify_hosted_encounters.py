"""Two fresh hosted accounts encounter and fight dogs through public encrypted TCP.

Automated protocol clients, not graphical clients. No existing player credentials/data.
"""
from verify_hosted_character_onboarding import *
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import socket,struct,subprocess,shlex
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import decode_battle_move
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_turn import encode_end_turn

SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']

def provision(names,passwords):
    code="import json,sys; from server.accounts import Accounts; a=Accounts('/var/lib/tio-server/reservation.sqlite3'); [a.create(n,p) for n,p in json.load(sys.stdin)]"
    result=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(list(zip(names,passwords))),capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr)

def play(host,name,password):
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        sock=socket.create_connection((host,port),timeout=12);case.clients.append(sock);return sock
    case.connect=connect
    def ping(peer):peer.send(b'\x70');peer.until(b'\x9e',max_packets=4096)
    case.ping=ping
    result=dict(account=name,kind='public encrypted TCP, automated client',checks=[])
    try:
        peer=case.handoff(case.begin(name,password));assert case.character_screen(peer)==()
        peer.send(encode_character_create(CharacterCreateRequest(name.encode(),0,(1,0,0,0))))
        assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
        peer.send(bytes.fromhex('1701000000'));assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
        peer.send(encode_request(1,bytes((1,5,1,3,0,0))));peer.until(b'\x10')
        peer.send(bytes.fromhex('1701000000'));assert peer.receive()[0]==0x18
        peer.send(b'\x19');peer.until(b'\x66');ping(peer)
        state=dict(actors={},turn=False,summary=None,turns=0,attacks=0,dog_moves=0,dog_hits=0)
        original=peer.receive
        def receive():
            packet=original()
            if packet[0]==0x3b:
                resource=int.from_bytes(packet[9:13],'little')
                actor=decode_battle_soldier(packet,human_equipment=resource in (1,2,6,100))
                state['actors'][actor.soldier_id]=dict(owner=actor.owner_id,resource=resource,position=actor.position,hp=actor.fields['0x8c57bb'])
            elif packet[0]==0x3d:
                move=decode_battle_move(packet)
                if move.actor_id in state['actors'] and move.path:
                    actor=state['actors'][move.actor_id];actor['position']=move.path[-1]
                    if actor['resource']==103:state['dog_moves']+=1
            elif packet[0]==0x43:
                identity=int.from_bytes(packet[1:5],'little')
                if identity in state['actors']:state['actors'][identity]['position']=(255,255)
            elif packet[0]==0x4e and len(packet)==18 and int.from_bytes(packet[5:9],'little')==1 and int.from_bytes(packet[9:13],'little')==4:
                identity=int.from_bytes(packet[1:5],'little');hp=int.from_bytes(packet[13:17],'little')
                if identity in state['actors']:
                    actor=state['actors'][identity]
                    if actor['owner']==1 and hp<actor['hp']:state['dog_hits']+=1
                    actor['hp']=hp
            elif packet[0]==0x38:state['turn']=True;state['turns']+=1
            elif packet[0]==0x39:state['turn']=False
            elif packet[0]==0x4c:state['summary']=packet
            return packet
        peer.receive=receive
        peer.send(struct.pack('<Bii',0x1b,400,300))
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            packet=peer.receive()
            if packet==b'\x41':break
        else:raise AssertionError('Random encounter did not start within the journey')
        dogs=[i for i,a in state['actors'].items() if a['resource']==103]
        assert len(dogs)==2,state
        hero=next(i for i,a in state['actors'].items() if a['owner']==1)
        result['checks'].append('Natural world-map travel triggers two infected dog NPCs without client spawn request')
        peer.send(b'\x36')
        deadline=time.monotonic()+150
        while state['summary'] is None and time.monotonic()<deadline and state['turns']<25:
            if not state['turn']:
                peer.receive();continue
            for _ in range(3):
                if not state['turn'] or state['summary'] is not None:break
                own=state['actors'][hero];x,y=own['position']
                targets=[(i,a) for i,a in state['actors'].items() if a['resource']==103 and a['hp'] and a['position']!=(255,255)]
                if not targets:break
                target=min(targets,key=lambda row:(row[1]['position'][0]-x)**2+(row[1]['position'][1]-y)**2)[1]
                peer.send(encode_attack_request(AttackRequest(hero,*target['position'])));state['attacks']+=1;ping(peer)
            if state['summary'] is None and state['turn']:peer.send(encode_end_turn(0));state['turn']=False
        assert state['summary'] is not None,dict(state=state)
        summary=state['summary'];result.update(result=summary[3],kills=int.from_bytes(summary[4:8],'little'),
            credits=int.from_bytes(summary[20:24],'little'),damage_dealt=int.from_bytes(summary[12:16],'little'),
            damage_received=int.from_bytes(summary[16:20],'little'),turns=state['turns'],attacks=state['attacks'],dog_moves=state['dog_moves'])
        assert result['damage_dealt']>0
        if result['result']==1:assert result['kills']==2 and result['credits']==75
        else:assert result['credits']==0
        result['checks'].append('Real hosted combat actions settle damage, outcome and credit reward')
        peer.send(b'\x2a\x01');peer.until(b'\x1e',max_packets=4096);ping(peer)
        peer.send(b'\x2a\x01');peer.until(b'\x1e',max_packets=4096);ping(peer)
        result['checks'].append('Finish and repeated finish return to world map with stop packet')
        peer.send(struct.pack('<Bii',0x1b,390,290));peer.until(b'\x1d',max_packets=4096);ping(peer)
        result['checks'].append('Map travel works again after the encounter')
        result['passed']=True
        return result
    finally:
        for connection in case.clients:connection.close()

def main(host):
    prefix='qd'+secrets.token_hex(4);names=[prefix+'a',prefix+'b'];passwords=[secrets.token_urlsafe(24) for _ in names]
    provision(names,passwords)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda pair:play(host,*pair),zip(names,passwords)))
    (ROOT/'reports/dog-encounters/hosted-tcp-clients.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    code="""import json,sqlite3,sys
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True);names=json.load(sys.stdin)
print(json.dumps({n:dict(encounters=d.execute('SELECT match_id,x,y,level,dogs FROM world_encounter_audit WHERE account=?',(n,)).fetchall(),
rewards=d.execute('SELECT result,credits FROM battle_rewards WHERE account=?',(n,)).fetchall(),
rank_gains=d.execute('SELECT earned FROM rank_battle_audit WHERE account=?',(n,)).fetchall()) for n in names}))"""
    process=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(names),capture_output=True,text=True)
    if process.returncode:raise RuntimeError(process.stderr)
    saved=json.loads(process.stdout)
    for name in names:
        assert len(saved[name]['encounters'])==1 and len(saved[name]['rewards'])==1
        assert all(row[0]==0 for row in saved[name]['rank_gains'])
    assert saved[names[0]]['encounters'][0][0]!=saved[names[1]]['encounters'][0][0]
    report=dict(passed=True,kind=__doc__,clients=results,persisted=saved,checks=['Two simultaneous real hosted accounts, independent match IDs, one reward each, no PvP rank farming'])
    (ROOT/'reports/dog-encounters/hosted-tcp.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main(sys.argv[1])
