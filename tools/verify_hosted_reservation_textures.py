"""Two fresh HTTPS accounts exercise the deployed Reservation maps over public encrypted TCP.

Does not use player credentials or modify their saved squads. This is not a
graphical-client validation. QA accounts are retained for auditability.
"""
from verify_hosted_character_onboarding import *
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_turn import encode_end_turn


def combat_run(host,mode):
    import socket
    prefix='qr'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result=dict(accounts=names,kind='public encrypted TCP; no graphical clients',checks=[],passed=False)
    output=ROOT/f'reports/reservation-textures/hosted-{mode}-{prefix}.json'
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        connection=socket.create_connection((host,port),timeout=15)
        case.clients.append(connection);return connection
    case.connect=connect
    def ping(peer):
        peer.send(b'\x70')
        assert peer.until(b'\x9e',max_packets=2048)==b'\x9e'
    case.ping=ping
    try:
        import subprocess
        command="cd /opt/tio-emulator && .venv/bin/python -c \"import json,sys; from server.accounts import Accounts; a=Accounts('/var/lib/tio-server/reservation.sqlite3'); [a.create(n,p) for n,p in json.load(sys.stdin)]\""
        subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,command],
                       input=json.dumps(list(zip(names,passwords))),text=True,check=True,capture_output=True)
        result['mode']=mode
        result['provisioning']='fresh QA accounts via account administration; public registration limit unchanged'
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
            peer.send(encode_create_request(ArenaCreateRequest(mode,0,4 if mode==1 else 8,2,40,1,1,0,0)))
            peer.until(b'\x25');peer.send(b'\x2e')
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
        from tio.protocol.battle_ground import decode_battle_ground
        grounds=[next(p for p in packets if p[0]==0x35) for packets in received]
        assert grounds[0]==grounds[1], 'Accounts received different map geometry'
        ground=decode_battle_ground(grounds[0])
        assert (ground.width,ground.height)==(57,57)
        assert ground.entries
        bindings=json.loads((ROOT/'config/reservation_visuals.json').read_text())['entries']
        assert set(ground.first_layer) in ({10},{11})
        assert all(e.name.decode() in set(bindings.values()) for e in ground.entries)
        result['checks'].append('Both accounts receive isolated Reservation resource names and new ground brush')
        result['map_brushes']=sorted(set(ground.first_layer))
        result['map']={'width':ground.width,'height':ground.height,'ground_id':ground.unknown_u8,
                       'objects':[{'name':e.name.decode(),'x':e.unknown_u8_01,'y':e.unknown_u8_02} for e in ground.entries]}
        result['checks'].append('Both real accounts receive identical 57x57 battlefield')
        assert actors[0].soldier_id!=actors[1].soldier_id
        result['checks'].append('two independent accounts; shared team battlefield; unique own actors')
        accepted_moves=0
        for cycle in range(2):
            for index,peer in enumerate(peers):
                peer.until(b'\x38',max_packets=2048)
                actor=actors[index];identity=actor.soldier_id
                x,y=actor.fields['0x8c519b'],actor.fields['0x8c51af']
                if cycle==0:
                    start=len(received[index])
                    peer.send(encode_move_request(BattleMove(identity,((255,255),))))
                    case.ping(peer)
                    replies=received[index][start:]
                    correction=decode_battle_move(next(p for p in replies if p[0]==0x3d))
                    assert correction.path==((x,y),)*2
                    result['checks'].append(f'player{index+1}: rejected move restores native prediction')
                    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                        if not (0<=x+dx<=255 and 0<=y+dy<=255):continue
                        start=len(received[index]);path=((x+dx,y+dy),)
                        peer.send(encode_move_request(BattleMove(identity,path)));case.ping(peer)
                        moves=[decode_battle_move(p) for p in received[index][start:] if p[0]==0x3d]
                        if any(m.actor_id==identity and m.path==path for m in moves):
                            accepted_moves+=1;break
                peer.send(encode_end_turn(identity if cycle else 0))
                peer.until(b'\x39',max_packets=2048)
        # Drain the next circle's native events before checking observer delivery.
        peers[0].until(b'\x38',max_packets=2048)
        for peer in peers:case.ping(peer)
        assert accepted_moves==2
        for index,packets in enumerate(received):
            assert any(p[:2]==b'\xc8\x17' for p in packets)
            assert any(p[0]==0x3d and int.from_bytes(p[1:5],'little') not in {a.soldier_id for a in actors} for p in packets)
            assert not any(p[0]==0x30 and int.from_bytes(p[1:5],'little')!=actors[index].soldier_id for p in packets)
        result['checks'].extend(['both players: movement then immediate manual end turn; repeated complete turn circles',
                                 'both observers receive foreign owner/timer C8/17 and AI movement3D',
                                 'no foreign inventory30 delivered'])
        result['passed']=True
        for peer in peers:peer.send(b'\x2a\x01')
        for peer in peers:case.ping(peer)
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':combat_run(sys.argv[1],int(sys.argv[2]))
