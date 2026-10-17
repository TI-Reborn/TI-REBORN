"""Two hosted accounts: native-compatible timer handoff in Team and Wall.

Checks public encrypted TCP and member IDs, not graphical clients.
Fresh QA accounts only; existing accounts/saves are never modified.
"""
from verify_hosted_character_onboarding import *
import socket,subprocess,shlex
from tio.protocol.arena import decode_battle_settings_body
from tio.protocol.battle_members import decode_battle_members
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.item_list import decode_item_list
from tio.protocol.battle_turn import encode_end_turn


def run(host):
    prefix='qz'+secrets.token_hex(4);names=[prefix+x for x in 'ab']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,scope=__doc__,passed=False,cases=[])
    def remote(code,payload):
        return subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@'+host,
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
    def enter(i):
        p=case.handoff(case.begin(names[i],passwords[i]));received[i]=[];original=p.receive
        def receive():
            packet=original();received[i].append(packet);return packet
        p.receive=receive;case.enter(p,names[i]);return p
    try:
        remote('''
import json,sys
from server.accounts import Accounts
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in json.load(sys.stdin):
 assert n.startswith('qz') and len(n)==11
 a.create(n,p,character=n)
''',list(zip(names,passwords)))
        for i in range(2):enter(i)
        close();time.sleep(1)
        remote('''
import json,sys
from dataclasses import replace
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
names=json.load(sys.stdin)
assert len(names)==2 and all(n.startswith('qz') and len(n)==11 for n in names)
store=OwnedPetStore('/var/lib/tio-server/reservation.sqlite3')
_,raw,_=store.list(names[1])[0]
p=decode_pet_info(raw,human_equipment=True)
fields={**p.fields,'0x8c43eb':2,'0x8c44a6':2,'0x8c4489':b'QA reserve'}
store.ensure(names[1],encode_pet_info(replace(p,fields=fields)),encode_item_list(2,()),human=True)
''',names)
        for mode,expected_players in ((1,4),(4,8)):
            peers=[enter(i) for i in range(2)]
            for p in peers:
                p.send(bytes((0xba,3,mode,1)));p.until(b'\x25');case.ping(p)
            starts=[len(v) for v in received]
            peers[0].send(b'\x2e');case.ping(peers[0])
            assert not any(x[0]==0x35 for x in received[0][starts[0]:]),'No all-bot fallback'
            peers[1].send(b'\x2e')
            own=[];grounds=[];rosters=[]
            for i,p in enumerate(peers):
                p.until(b'\x41',max_packets=512)
                scene=received[i][starts[i]:]
                assert not any(x[0]==0xf0 for x in scene),'Start rejected'
                settings=decode_battle_settings_body(next(x[1:] for x in reversed(scene) if x[0]==0x6c))
                assert (settings.mode,settings.players_count,settings.soldiers_count,settings.turn_seconds)==(mode,expected_players,1,40)
                members=decode_battle_members(next(x for x in reversed(scene) if x[0]==0x25))[2]
                assert len(members)==expected_players
                # Battle bots share the display name "AI bot"; retain every ID.
                rosters.append({m.name.decode() if m.name.decode() in names else
                    f'{m.name.decode()}#{m.character_id}':m.character_id for m in members})
                assert set(names)<={m.name.decode() for m in members}
                own_actors=[decode_battle_soldier(x,human_equipment=True) for x in scene if x[0]==0x3b and int.from_bytes(x[5:9],'little')==1]
                assert len(own_actors)==1
                own.append(own_actors[0].soldier_id)
                grounds.append(next(x for x in scene if x[0]==0x35))
            assert grounds[0]==grounds[1]
            for p in peers:p.send(b'\x36')
            peers[0].until(b'\x38',max_packets=512)
            peers[0].send(encode_end_turn());peers[0].until(b'\x39')
            peers[1].until(b'\x38',max_packets=512)
            case.ping(peers[0])
            # Old bare1B never reached the native timer callback. Check exact
            # C8/17 header, foreign member identity and seconds on both sockets.
            timer_packets=[]
            for i in range(2):
                foreign=rosters[i][names[1-i]]
                expected=b'\xc8\x17'+foreign.to_bytes(4,'little')+(40).to_bytes(4,'little')
                assert expected in received[i][starts[i]:], (i,foreign)
                timer_packets.append(expected.hex())
            report['last_human_handoff']=dict(mode=mode,packets=timer_packets)
            peers[1].send(encode_end_turn());peers[1].until(b'\x39')
            peers[0].until(b'\x38',max_packets=2048)
            case.ping(peers[1])
            bot_timers=[]
            for i in range(2):
                packets=received[i][starts[i]:]
                assert not any(p[:1]==b'\x1b' for p in packets)
                bots={v for k,v in rosters[i].items() if k not in names}
                timers=[p for p in packets if p[:2]==b'\xc8\x17']
                assert all(len(p)==10 and int.from_bytes(p[2:6],'little') in set(rosters[i].values())-{1} for p in timers)
                observed={int.from_bytes(p[2:6],'little') for p in timers}&bots
                assert observed==bots,(observed,bots)
                bot_timers.append(sorted(observed))
            for i,p in enumerate(peers):
                p.send(b'\x2f\1\0'+own[i].to_bytes(4,'little'))
                assert decode_item_list(p.until(b'\x30'))[0]==own[i]
            for p in peers:p.send(b'\x2a\1');case.ping(p)
            report['cases'].append(dict(mode=mode,selected=[1,2],admitted=[1,1],players=expected_players,
                humans=2,bots=expected_players-2,timer_packets=timer_packets,bot_timer_owners=bot_timers,
                both_skip_directions=True,second_round_started=True,inventory_readable=True))
            close();time.sleep(1)
        report['saved_selection']=json.loads(remote('''
import json,sys
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info
result=[]
for n in json.load(sys.stdin):
 assert n.startswith('qz') and len(n)==11
 result.append([(i,decode_pet_info(p,human_equipment=True).fields['0x8c44a6']) for i,p,_ in OwnedPetStore('/var/lib/tio-server/reservation.sqlite3').list(n)])
assert result==[[(1,1)],[(1,1),(2,2)]],result
print(json.dumps(result))
''',names))
        report['passed']=True
    finally:
        close()
        (ROOT/f'evidence/hosted-turn-timer-{prefix}.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run(sys.argv[1])
