"""Two fresh HTTPS accounts exercise the deployed Wall over native public TCP with legacy obfuscation.

Does not use player credentials or modify their saved squads. This is not a
graphical-client validation. QA accounts are retained for auditability.
"""
from verify_hosted_character_onboarding import *
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_turn import encode_end_turn


def reward_run(host, *, profile_check=None, battle_check=None):
    import socket
    prefix='qr'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result=dict(accounts=names,kind='native public TCP with legacy obfuscation; no graphical clients',checks=[],passed=False)
    output=ROOT/f'evidence/hosted-rewards-{prefix}.json'
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        connection=socket.create_connection((host,port),timeout=15)
        case.clients.append(connection);return connection
    case.connect=connect
    try:
        if '--admin-provision' in sys.argv:
            import subprocess
            command="cd /opt/tio-emulator && .venv/bin/python -c \"import json,sys; from server.accounts import Accounts; a=Accounts('/var/lib/tio-server/reservation.sqlite3'); [a.create(n,p) for n,p in json.load(sys.stdin)]\""
            subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,command],
                           input=json.dumps(list(zip(names,passwords))),text=True,check=True,capture_output=True)
            result['provisioning']='two fresh QA accounts via account administration; public registration rate limit left intact'
        else:
            for name,password in zip(names,passwords):
                origin='https://'+host
                opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                html=opener.open(origin+'/register/',timeout=15).read()
                token=re.search(rb'name="csrf" value="([^"]+)"',html)[1].decode()
                data=urllib.parse.urlencode(dict(csrf=token,login=name,password=password,confirm=password)).encode()
                assert opener.open(urllib.request.Request(origin+'/register/',data=data,headers={'Origin':origin}),timeout=15).status==201
        peers=[];received=[[],[]]
        for index,(name,password) in enumerate(zip(names,passwords)):
            peer=case.handoff(case.begin(name,password));peers.append(peer)
            assert case.character_screen(peer)==()
            peer.send(encode_character_create(CharacterCreateRequest(name.encode(),0,(1,0,0,0))))
            assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
            peer.send(bytes.fromhex('1701000000'))
            assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
            peer.send(encode_request(1,bytes((1,5,1,3,0,0))))
            peer.until(b'\x10');peer.send(bytes.fromhex('1701000000'))
            entered=peer.receive();assert entered[0]==0x18,entered.hex()
            peer.send(b'\x19');peer.until(b'\x66');case.ping(peer)
            original=peer.receive
            def receive(original=original,index=index):
                packet=original();received[index].append(packet);return packet
            peer.receive=receive
            peer.send(b'\xba\x03\0\1')
        actors=[]
        for index,peer in enumerate(peers):
            peer.until(b'\x41',max_packets=512)
            own=[]
            for packet in received[index]:
                if packet[0]==0x3b:
                    actor=decode_battle_soldier(packet,human_equipment=int.from_bytes(packet[9:13],'little') in (1,2,6))
                    if actor.owner_id==1:own.append(actor)
            assert len(own)==1
            actors.append(own[0]);peer.send(b'\x36')
        if battle_check is not None:battle_check(names,actors,result)
        from collections import deque
        from tio.protocol.battle_ground import decode_battle_ground
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
        import struct
        ground=decode_battle_ground(next(p for p in received[0] if p[0]==0x35))
        fragments={Path(k).stem:v for k,v in json.loads((ROOT/'config/arena_fragments.json').read_text()).items()}
        blocked=set()
        for entry in ground.entries:
            f=fragments[entry.name.decode()];x,y=entry.unknown_u8_01,entry.unknown_u8_02
            blocked.update((x+i,y+j) for j in range(f['height']) for i in range(f['width']) if f['tiles'][j*f['width']+i] in (2,3,4))
            for i,j,opened in f.get('doors',()):
                if opened:blocked.discard((x+i,y+j))
                else:blocked.add((x+i,y+j))
        ids=[a.soldier_id for a in actors]
        positions=[(a.fields['0x8c519b'],a.fields['0x8c51af']) for a in actors]
        offsets=[0,0];done=[None,None];turn=[False,False];dealt=[0,0]
        def refresh(index):
            for p in received[index][offsets[index]:]:
                if p[0]==0x38:turn[index]=True
                if p[0]==0x39:turn[index]=False
                if p[0]==0x3d:
                    move=decode_battle_move(p)
                    if move.actor_id==ids[index]:positions[index]=move.path[-1]
                if p[0]==0x4b:
                    attack=decode_attack_result(p)
                    if attack.actor_id==ids[index]:dealt[index]+=sum(h.damage for h in attack.hits if h.actor_id==ids[1-index])
                if p[0]==0x4c:done[index]=p;turn[index]=False
            offsets[index]=len(received[index])
        def path_to_enemy(index):
            start=positions[index];target=positions[1-index]
            goals={(target[0]+dx,target[1]+dy) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1))}
            if start in goals:return ()
            queue=deque([start]);previous={start:None}
            while queue:
                x,y=queue.popleft()
                for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if cell in previous or cell in blocked or cell==target or not(0<=cell[0]<ground.width and 0<=cell[1]<ground.height):continue
                    previous[cell]=(x,y)
                    if cell in goals:
                        route=[]
                        while cell!=start:route.append(cell);cell=previous[cell]
                        return tuple(reversed(route))
                    queue.append(cell)
            raise AssertionError('No route to QA opponent')
        for cycle in range(80):
            for index in sorted(range(2),key=lambda i:ids[i]):
                peer=peers[index]
                refresh(index)
                while not turn[index] and done[index] is None:
                    peer.receive();refresh(index)
                if done[index] is not None:continue
                for action in range(30):
                    route=path_to_enemy(index)
                    if index==1 and dealt[index]>0:break
                    if route:
                        peer.send(encode_move_request(BattleMove(ids[index],route[:5])))
                    else:
                        peer.send(encode_attack_request(AttackRequest(ids[index],*positions[1-index])))
                    begin=len(received[index]);case.ping(peer);refresh(index)
                    if not turn[index] or done[index] is not None:break
                    if any(p[0]==0xf0 for p in received[index][begin:]):break
                if turn[index]:peer.send(encode_end_turn());case.ping(peer);refresh(index)
            if all(p is not None for p in done):break
        assert all(p is not None for p in done),'Battle did not complete'
        assert all(d>0 for d in dealt),dealt
        summaries=[(p[3],*struct.unpack_from('<6I',p,4)) for p in done]
        assert [r[0] for r in summaries]==[1,0],summaries
        assert [r[5] for r in summaries]==[100,25],summaries
        assert [r[6] for r in summaries]==[0,0],summaries
        for index,peer in enumerate(peers):
            wallets=[decode_asset_count(p).credits for p in received[index] if p[:2]==b'\xc8\x39']
            assert wallets, 'No wallet update'
            result.setdefault('wallets',[]).append(wallets[-1])
            peer.send(b'\x2a\x01');case.ping(peer)
            start=len(received[index]);peer.send(b'\x2a\x01');case.ping(peer)
            assert not any(p[0]==0x4c for p in received[index][start:])
        if profile_check is not None:profile_check(peers,names,summaries,result,case)
        result.update(passed=True,summaries=summaries,damage=dealt)
        result['checks'].extend(['two real QA accounts completed shared Survival via native public TCP with legacy obfuscation',
                                 'both dealt authoritative damage; winner 100, loser 25; native 4C summaries',
                                 'wallet updates delivered; repeated result dismissal did not repeat summary'])
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':reward_run(sys.argv[1])
