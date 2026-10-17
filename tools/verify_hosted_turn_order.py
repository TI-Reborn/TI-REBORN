"""Two fresh QA accounts exercise deployed shared battles over public encrypted TCP.

Does not use player credentials or modify their saved squads. This is not a
graphical-client validation. QA accounts are retained for auditability.
"""
from verify_hosted_character_onboarding import *
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_turn import encode_end_turn


def combat_run(host,mode):
    import socket,subprocess,shlex
    prefix='qo'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result=dict(accounts=names,kind='public encrypted TCP; no graphical clients',checks=[],passed=False)
    output=ROOT/f'reports/turn-order/hosted-{prefix}.json'
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        connection=socket.create_connection((host,port),timeout=15)
        case.clients.append(connection);return connection
    case.connect=connect
    try:
        # Keep gameplay QA independent of public registration rate limits.
        code='''
import json,sys,sqlite3,tempfile,pathlib
from server.accounts import Accounts
pairs=json.load(sys.stdin);assert len(pairs)==2 and all(n.startswith('qo') and len(n)==11 for n,p in pairs)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-turn-order-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:src.backup(dst)
accounts=Accounts('/var/lib/tio-server/reservation.sqlite3')
for name,password in pairs:accounts.create(name,password)
print(json.dumps(str(folder)))
'''
        creation=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],
            input=json.dumps(list(zip(names,passwords))),capture_output=True,text=True,encoding='utf-8')
        if creation.returncode:raise RuntimeError(creation.stderr)
        result['qa_backup']=json.loads(creation.stdout)
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
        assert actors[0].soldier_id!=actors[1].soldier_id
        result['checks'].append('Two independent accounts; shared team or wall battle; unique own actors')
        from tio.protocol.binary import Reader
        sequences=[]
        for packets in received:
            ordered=[p for p in packets if p[0]==0x71]
            assert len(ordered)==1
            r=Reader(ordered[0]);assert r.u8()==0x71;count=r.u8()
            entries=tuple((r.u32(),r.u8()) for _ in range(count));r.finish()
            assert count==(4 if mode==1 else 8)
            assert tuple(n for owner,n in entries)==tuple(range(count))
            sequences.append(tuple(owner for owner,n in entries))
        assert sequences[0][0]==1 and sequences[1][1]==1
        assert sequences[0][2:]==sequences[1][2:]
        assert len(set(sequences[0]))==len(sequences[0])
        assert len(set(sequences[1]))==len(sequences[1])
        result['displayed_numbers']=[list(range(1,len(s)+1)) for s in sequences]
        result['wire_owner_sequences']=sequences
        result['mode']=mode
        result['checks'].append('Both peers receive native71 after members and before loading; same interleaved turn order with local ID alias')
        peers[0].until(b'\x38',max_packets=2048)
        peers[0].send(encode_end_turn())
        updates=peers[0].until(b'\xc8\x17',max_packets=2048)
        assert int.from_bytes(updates[2:6],'little')==sequences[0][1]
        result['checks'].append('Actual next turn owner agrees with displayed number2')
        for peer in peers:peer.send(b'\x2a\x01')
        from tio.protocol.system_message import encode_current_town
        for peer in peers:peer.until(encode_current_town(3),max_packets=2048)
        result['passed']=True
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':combat_run(sys.argv[1],int(sys.argv[2]))
