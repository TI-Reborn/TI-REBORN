"""Two fresh HTTPS accounts exercise the deployed Wall over public encrypted TCP.

Does not use player credentials or modify their saved squads. This is not a
graphical-client validation. QA accounts are retained for auditability.
"""
from verify_hosted_character_onboarding import *
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_turn import encode_end_turn


def combat_run(host):
    import socket
    prefix='qh'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result=dict(accounts=names,kind='public encrypted TCP; no graphical clients',checks=[],passed=False)
    output=ROOT/f'reports/wall-disconnect/hosted-{prefix}.json'
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        connection=socket.create_connection((host,port),timeout=15)
        case.clients.append(connection);return connection
    case.connect=connect
    try:
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
            peer.send(encode_create_request(ArenaCreateRequest(4,0,8,2,40,1,1,0,0)))
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
        assert actors[0].soldier_id!=actors[1].soldier_id
        result['checks'].append('two independent accounts; shared eight-player Wall; unique own actors')
        import threading
        start=time.monotonic();beats=[[],[]];errors=[]
        def observe(index,peer):
            try:
                while time.monotonic()-start<45:
                    packet=peer.receive()
                    if packet==b'\x9e':beats[index].append(round(time.monotonic()-start,3))
            except BaseException as error:errors.append(repr(error))
        threads=[threading.Thread(target=observe,args=(i,p)) for i,p in enumerate(peers)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(60)
        assert not any(t.is_alive() for t in threads) and not errors,errors
        for times in beats:
            assert len(times)>=4,times
            assert max(b-a for a,b in zip([0]+times,times))<12,times
        result['heartbeat_seconds']=beats
        result['checks'].append('Both passive clients receive periodic9E beyond the original36-second disconnect, without ping70 or actions')
        for peer in peers:peer.send(b'\x2a\x01')
        from tio.protocol.system_message import encode_current_town
        for peer in peers:peer.until(encode_current_town(3),max_packets=2048)
        result['passed']=True
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':combat_run(sys.argv[1])
