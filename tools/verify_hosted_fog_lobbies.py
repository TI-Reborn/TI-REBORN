"""Two fresh hosted accounts: wounded rejection, paid heal, Team/Wall creation,
shared room discovery and survival scene fog flag. Public encrypted TCP;
not a visual game-client test. Only the new QA characters are modified.
"""
from verify_hosted_character_onboarding import *
import socket,subprocess,shlex
from tio.protocol.arena import decode_room_list
from tio.protocol.battle_ground import decode_battle_ground
from tio.protocol.battle_members import decode_battle_members


def run(host):
    prefix='qf'+secrets.token_hex(4);names=[prefix+x for x in 'ab']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,kind=__doc__,passed=False,checks=[])
    def remote(code,payload):
        return subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],
            input=json.dumps(payload),capture_output=True,text=True,check=True).stdout
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        sock=socket.create_connection((host,port),timeout=15);case.clients.append(sock);return sock
    case.connect=connect
    def close():
        for sock in case.clients:sock.close()
        case.clients=[]
    received=[[],[]]
    def enter(index):
        peer=case.handoff(case.begin(names[index],passwords[index]));received[index]=[]
        original=peer.receive
        def receive():
            packet=original();received[index].append(packet);return packet
        peer.receive=receive;case.enter(peer,names[index]);return peer
    try:
        remote('''
import json,sys
from server.accounts import Accounts
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in json.load(sys.stdin):
 assert n.startswith('qf') and len(n)==11
 a.create(n,p,character=n)
''',list(zip(names,passwords)))
        for i in range(2):enter(i)
        close();time.sleep(1)
        remote('''
import json,sys,sqlite3
from tio.battle_recovery import save_wounds
names=json.load(sys.stdin)
assert len(names)==2 and all(n.startswith('qf') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n in names:save_wounds(db,n,{1:1})
''',names)
        peers=[enter(i) for i in range(2)]
        for i,peer in enumerate(peers):
            for mode in (1,4):
                peer.send(bytes((0xba,3,mode,1)))
                error=peer.until(b'\xf0\x8a\x01\0\0')
                assert int.from_bytes(error[9:13],'little')==5
                message=error[13:-2].decode('utf-16-le')
                assert 'здоровье' in message and 'Вылечите' in message
                case.ping(peer)
            peer.send(b'\xb8\x11');before=decode_asset_count(peer.until(b'\xc8\x39')).credits
            case.ping(peer)
            peer.send(b'\x7c\1\1\0\0\0')
            after=decode_asset_count(peer.until(b'\xc8\x39')).credits
            pet=decode_pet_info(peer.until(b'\x66'),human_equipment=True)
            assert after<before and pet.fields['0x8c4ab1']==pet.fields['0x8c4a07']
            case.ping(peer)
        report['checks'].append('Both accounts: Team and Wall reject wounded fighter with UTF16 HP/help text; native7C treatment charges credits and restores full health')
        for mode in (1,4):
            for peer in peers:
                peer.send(bytes((0xba,3,mode,1)));peer.until(b'\x25');case.ping(peer)
            for peer in peers:
                peer.send(b'\xba\1');rooms=decode_room_list(peer.until(b'\xba\2'))
                assert set(names)<={r.name.decode() for r in rooms},rooms
                case.ping(peer)
            for peer in peers:
                peer.send(b'\xba\5\1\0\0\0\0');peer.until(b'\xf0\x18\0\0\0');case.ping(peer)
        report['checks'].append('Both healed accounts independently create Team and Wall rooms; each client sees both captains in the shared list and leaves normally')
        starts=[len(p) for p in received]
        for peer in peers:peer.send(b'\xba\3\0\1')
        maps=[]
        for i,peer in enumerate(peers):
            peer.until(b'\x41',max_packets=512)
            scene=received[i][starts[i]:]
            ground=next(p for p in scene if p[0]==0x35);maps.append(ground)
            assert decode_battle_ground(ground).unknown_u8==0
            members=decode_battle_members(next(p for p in reversed(scene) if p[0]==0x25))[2]
            assert {m.name.decode() for m in members}==set(names),'Must be two humans without bots'
            peer.send(b'\x36');case.ping(peer)
        assert maps[0]==maps[1]
        report['checks'].append('Two humans share the same authoritative battlefield, without bots; both receive dynamic fog flag0 in scene35')
        for peer in peers:peer.send(b'\x2a\1');case.ping(peer)
        report['passed']=True
    finally:
        close()
        (ROOT/f'evidence/hosted-fog-lobbies-{prefix}.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run(sys.argv[1])
