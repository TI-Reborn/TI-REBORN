"""Two fresh hosted accounts die in natural encounters over encrypted public TCP.

Automated protocol clients, not graphical clients. Only these QA accounts receive
one HP and an initial map position so the death/nearest-city check is bounded.
"""
from verify_hosted_forest_biomes import connect_case,remote,ROOT
from verify_hosted_encounters import secrets,json,struct,time,ThreadPoolExecutor
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_attack import decode_attack_result
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.battle_ground import decode_battle_ground
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from collections import deque
from tio.protocol.system_message import encode_current_town,encode_open_town_view
from tio.locations import nearest_city,center
OUT=ROOT/'reports/world-encounter-return'

def provision(names,passwords):
    remote('''import json,sys,sqlite3
from pathlib import Path
from dataclasses import replace
from server.accounts import Accounts
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.squad import SquadStore
from tio.locations import LocationStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
path='/var/lib/tio-server/reservation.sqlite3';accounts=Accounts(path);pets=OwnedPetStore(path);locations=LocationStore(path)
original=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex'])
for n,p,point in json.load(sys.stdin):
 assert n.startswith('qer');accounts.create(n,p,character=n)
 pet=decode_pet_info(original,human_equipment=True)
 pet=replace(pet,fields={**pet.fields,'0x8c4a07':1,'0x8c4ab1':1})
 pets.ensure(n,encode_pet_info(pet),encode_item_list(1,()),human=True)
 WalletStore(path).ensure(n);SquadStore(path).assign(n,1,1)
 with sqlite3.connect(path) as db:locations._save(db,n,None,*point)
''',[(n,p,point) for n,p,point in zip(names,passwords,((-77,-505),(190,100)))])

def play(host,name,password,target,expected):
    case,peer=connect_case(host,name,password)
    state=dict(turn=False,turns=0,summary=None,actors={},towns=[],stops=[],opened=False,ground=None)
    receive_original=peer.receive
    def receive():
        packet=receive_original()
        if packet[0]==0x35:state['ground']=decode_battle_ground(packet)
        elif packet[0]==0x3b:
            resource=int.from_bytes(packet[9:13],'little')
            actor=decode_battle_soldier(packet,human_equipment=resource in (1,2,6,100))
            state['actors'][actor.soldier_id]=dict(owner=actor.owner_id,resource=resource,hp=actor.fields['0x8c57bb'],position=actor.position)
        elif packet[0]==0x3d:
            move=decode_battle_move(packet)
            if move.actor_id in state['actors'] and move.path:state['actors'][move.actor_id]['position']=move.path[-1]
        elif packet[0]==0x4b:
            for hit in decode_attack_result(packet).hits:
                if hit.actor_id in state['actors']:state['actors'][hit.actor_id]['hp']=hit.left_hp
        elif packet[0]==0x38:state['turn']=True;state['turns']+=1
        elif packet[0]==0x39:state['turn']=False
        elif packet[0]==0x4c:state['summary']=packet
        elif packet[0]==0x1e:state['stops'].append(struct.unpack_from('<ii',packet,5))
        elif packet[:5]==b'\xf0\x62\0\0\0':state['towns'].append(int.from_bytes(packet[-4:],'little'))
        elif packet==encode_open_town_view():state['opened']=True
        return packet
    peer.receive=receive
    try:
        peer.send(struct.pack('<Bii',0x1b,*target));deadline=time.monotonic()+130
        while time.monotonic()<deadline:
            if peer.receive()==b'\x41':break
        else:raise AssertionError('Natural encounter timed out')
        print(json.dumps(dict(account=name,stage='natural encounter')),flush=True)
        ground=state['ground'];blocked=set()
        fragments=json.loads((ROOT/'config/arena_fragments.json').read_text())
        for entry in ground.entries:
            f=fragments[entry.name.decode()+'.s'];x,y=entry.unknown_u8_01,entry.unknown_u8_02
            blocked.update((x+i,y+j) for j in range(f['height']) for i in range(f['width']) if f['tiles'][j*f['width']+i] in (2,3,4))
        hero=next(i for i,a in state['actors'].items() if a['owner']==1)
        def approach():
            start=state['actors'][hero]['position']
            occupied={a['position'] for i,a in state['actors'].items() if i!=hero and a['hp']}
            dogs=[a for a in state['actors'].values() if a['resource']==103 and a['hp']]
            if dogs:
                target=min(dogs,key=lambda a:abs(a['position'][0]-start[0])+abs(a['position'][1]-start[1]))['position']
                goals={(target[0]+dx,target[1]+dy) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))}
            else:
                goals={(ground.width//2,ground.height//2)}
            goals-=blocked|occupied
            if start in goals:return ()
            queue=deque([start]);previous={start:None}
            while queue:
                x,y=queue.popleft()
                for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if p in previous or p in blocked or p in occupied or not (0<=p[0]<ground.width and 0<=p[1]<ground.height):continue
                    previous[p]=(x,y)
                    if p in goals:
                        path=[]
                        while previous[p] is not None:path.append(p);p=previous[p]
                        return tuple(reversed(path))[:10]
                    queue.append(p)
            return ()
        peer.send(b'\x36');deadline=time.monotonic()+120
        while state['summary'] is None and time.monotonic()<deadline and state['turns']<50:
            if state['turn']:
                path=approach()
                if path:
                    peer.send(encode_move_request(BattleMove(hero,path)));case.ping(peer)
                if state['summary'] is None and state['turn']:
                    state['turn']=False;peer.send(encode_end_turn(0))
            else:peer.receive()
        assert state['summary'] is not None,state
        assert state['summary'][3] in (0,2),state['summary'].hex()
        heroes=[a for a in state['actors'].values() if a['owner']==1]
        assert heroes and all(a['hp']==0 for a in heroes),state
        peer.send(b'\x2a\x01');case.ping(peer)
        assert expected in state['towns'] and center(expected) in state['stops'] and state['opened'],state
        peer.send(b'\x2a\x01');case.ping(peer)
        assert state['towns'][-1]==expected and state['stops'][-1]==center(expected)
        result=dict(account=name,passed=True,nearest_city=expected,position=center(expected),turns=state['turns'],
                    death_received=True,city_selection_received=True,city_view_open_received=True,repeated_finish=True)
    finally:
        for sock in case.clients:sock.close()
    # 18 is character selection; town info arrives as C8/2D after entering19.
    from verify_hosted_encounters import MultiAccountTests,SimpleNamespace,socket
    from tio.protocol.town_info import decode_town_info
    fresh=MultiAccountTests();fresh.config=SimpleNamespace(game_port=28512,session_port=28513);fresh.clients=[]
    def connect(port):
        sock=socket.create_connection((host,port),timeout=15);fresh.clients.append(sock);return sock
    fresh.connect=connect
    try:
        p=fresh.handoff(fresh.begin(name,password));fresh.character_screen(p);p.send(bytes.fromhex('1701000000'))
        assert p.until(b'\x18')[:2]==b'\x18\0'
        p.send(b'\x19');town=decode_town_info(p.until(b'\xc8\x2d')).town_id;assert town==expected,town
        result['relogin_city']=town
    finally:
        for sock in fresh.clients:sock.close()
    print(json.dumps(result),flush=True);return result

def main(host):
    prefix='qer'+secrets.token_hex(4);names=[prefix+'a',prefix+'b'];passwords=[secrets.token_urlsafe(24) for _ in names]
    provision(names,passwords)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(play,host,n,p,target,town) for n,p,target,town in zip(names,passwords,((200,-500),(430,300)),(9,5))]
        clients=[f.result() for f in futures]
    persisted=remote('''import json,sys,sqlite3
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps({n:dict(location=d.execute('SELECT town_id,x,y FROM character_locations WHERE account=?',(n,)).fetchone(),
 encounters=d.execute('SELECT match_id,x,y FROM world_encounter_audit WHERE account=?',(n,)).fetchall(),
 rewards=d.execute('SELECT result,credits FROM battle_rewards WHERE account=?',(n,)).fetchall(),
 journeys=d.execute('SELECT COUNT(*) FROM map_journeys WHERE account=?',(n,)).fetchone()[0],
 loot=d.execute('SELECT COUNT(*) FROM encounter_loot_awards WHERE account=?',(n,)).fetchone()[0]) for n in json.load(sys.stdin)}))''',names)
    matches=[]
    for n in names:
        state=persisted[n];assert len(state['encounters'])==len(state['rewards'])==1
        match,x,y=state['encounters'][0];town=nearest_city(x,y);matches.append(match)
        assert state['location']==[town,*center(town)] and state['rewards'][0][1]==0
        assert state['journeys']==state['loot']==0
    assert len(set(matches))==2
    report=dict(passed=True,kind=__doc__,clients=clients,persisted=persisted)
    (OUT/'hosted-tcp.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)

if __name__=='__main__':
    import sys
    main(sys.argv[1])
