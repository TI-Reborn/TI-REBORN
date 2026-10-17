"""Two fresh QA accounts exercise deployed weapon effects over public encrypted TCP.

Does not use player credentials or modify their saved squads. This is not a
graphical-client validation. QA accounts are retained for auditability.
"""
from verify_hosted_character_onboarding import *
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.item_action import ItemAction,encode_item_action
from tio.durability import repair_item
import struct


def effects_run(host):
    import socket
    prefix='qe'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result=dict(accounts=names,kind='public encrypted TCP; no graphical clients',checks=[],passed=False)
    output=ROOT/f'evidence/hosted-weapon-effects-{prefix}.json'
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
        for connection in case.clients:connection.close()
        case.clients=[]
        import subprocess
        fixture = """
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
names=json.load(sys.stdin)
assert len(names)==2 and all(n.startswith('qe') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for index,name in enumerate(names):
  row=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()
  pet=decode_pet_info(row[0],human_equipment=True)
  pet=replace(pet,fields={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000,'0x8c4aef':10})
  equipment=((339,1,True),(340,2,False),(36,200,False)) if index==0 else ((314,1,True),(14,200,False))
  items=tuple(ItemRecord(1001+j,t,bytes(2),count,int(equip),16 if equip else 0,(300,300,300),bytes(4),None,bytes(3)) for j,(t,count,equip) in enumerate(equipment))
  db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(pet),encode_item_list(1,items),name))
print('QA fixtures installed')
"""
        subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+__import__('shlex').quote(fixture)],
            input=json.dumps(names),text=True,check=True,capture_output=True)
        result['fixture']='Only newly created QA accounts: level10, HP1000, Groza/subgrenades versus M60; not gameplay progression'
        peers=[];received=[[],[]]
        for index,(name,password) in enumerate(zip(names,passwords)):
            peer=case.handoff(case.begin(name,password));case.enter(peer,name);peers.append(peer)
            original=peer.receive
            def receive(original=original,index=index):
                packet=original();received[index].append(packet);return packet
            peer.receive=receive
        for peer in peers:peer.send(b'\xba\x03\0\1')
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
            from tio.visibility import clear_sight
            goals={(x,y) for x in range(ground.width) for y in range(ground.height) if 4 <= ((x-target[0])**2+(y-target[1])**2)**0.5 <= 5 and (x,y) not in blocked and clear_sight((x,y),target,blocked)}
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
        from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
        from tio.protocol.abilities import decode_abilities
        assert any(p[0]==0x80 and any(e.ability_id==27 for e in decode_abilities(p)[1]) for p in received[0]),'No Groza ability in scene'
        fired=[0,0]
        for cycle in range(40):
            for index in sorted(range(2),key=lambda i:ids[i]):
                peer=peers[index];refresh(index)
                while not turn[index] and done[index] is None:
                    peer.receive();refresh(index)
                if done[index] is not None:continue
                for action in range(30):
                    if fired[index]:break
                    route=path_to_enemy(index)
                    if route:peer.send(encode_move_request(BattleMove(ids[index],route[:5])))
                    elif index==0:peer.send(encode_ability_cast(AbilityCast(27,ids[index],0,*positions[1-index])))
                    else:peer.send(encode_attack_request(AttackRequest(ids[index],*positions[1-index])))
                    begin=len(received[index]);case.ping(peer);refresh(index)
                    fired[index]+=sum(p[0]==0x4b for p in received[index][begin:])
                    if not turn[index] or done[index] is not None:break
                    if any(p[0]==0xf0 for p in received[index][begin:]):break
                if turn[index]:peer.send(encode_end_turn());case.ping(peer);refresh(index)
            if all(fired):break
        assert all(fired),fired
        for peer in peers:case.ping(peer)
        attacks=[]
        for index in range(2):
            results=[decode_attack_result(p) for p in received[index] if p[0]==0x4b]
            for attacker,weapon,skill in ((ids[0],340,27),(ids[1],314,0)):
                attack=next(a for a in results if a.actor_id==attacker)
                assert (attack.weapon_id,attack.skill_id)==(weapon,skill)
            attacks.append([(a.actor_id,a.weapon_id,a.skill_id,[(h.actor_id,h.damage) for h in a.hits]) for a in results])
        assert attacks[0]==attacks[1],attacks
        final=[]
        for index,peer in enumerate(peers):
            inventories=[decode_item_list(p)[1] for p in received[index] if p[0]==0x30 and decode_item_list(p)[0]==ids[index]]
            items=inventories[-1];final.append(items)
            ammo,expected=(340,1) if index==0 else (14,180)
            assert next(i.count for i in items if i.template_id==ammo)==expected
            assert not any(p[0]==0x30 and decode_item_list(p)[0]==ids[1-index] for p in received[index])
            peer.send(b'\x2a\x01');case.ping(peer)
        for connection in case.clients:connection.close()
        case.clients=[];time.sleep(1)
        for index in range(2):
            peer=case.handoff(case.begin(names[index],passwords[index]));case.enter(peer,names[index])
            peer.send(b'\x2f\x01\0\x01\0\0\0')
            items=decode_item_list(peer.until(b'\x30'))[1]
            assert items==final[index],'Spent ammunition not persistent'
        result.update(passed=True,attacks=attacks,checks=['two authenticated accounts entered shared battle over public encrypted TCP',
            'Groza ability27 present at entry; subgrenade340 and M60 attacks delivered to both players',
            'one subgrenade and twenty M60 rounds consumed; inventories private to owner',
            'inventory and weapon wear persist after leaving battle and authenticated reconnect'])
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':effects_run(sys.argv[1])
