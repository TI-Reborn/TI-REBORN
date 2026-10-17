"""Two fresh QA accounts exercise deployed ground loot over public encrypted TCP.

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


def ground_run(host):
    import socket
    prefix='qg'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result=dict(accounts=names,kind='public encrypted TCP; no graphical clients',checks=[],passed=False)
    output=ROOT/f'evidence/hosted-ground-loot-{prefix}.json'
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
assert len(names)==2 and all(n.startswith('qg') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for index,name in enumerate(names):
  row=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()
  pet=decode_pet_info(row[0],human_equipment=True)
  pet=replace(pet,fields={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000,'0x8c4aef':10})
  equipment=((301,1,True),(3,200,False),(9,2,False))
  items=tuple(ItemRecord(1001+j,t,bytes(2),count,int(equip),16 if equip else 0,(300,300,300),bytes(4),None,bytes(3)) for j,(t,count,equip) in enumerate(equipment))
  db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(pet),encode_item_list(1,items),name))
print('QA fixtures installed')
"""
        subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+__import__('shlex').quote(fixture)],
            input=json.dumps(names),text=True,check=True,capture_output=True)
        result['fixture']='Only newly created QA accounts: level10, HP1000, pistol/ammo and two bandages each; not gameplay progression'
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
            goals={(x,y) for x in range(ground.width) for y in range(ground.height) if 1 <= ((x-target[0])**2+(y-target[1])**2)**0.5 <= 2 and (x,y) not in blocked and clear_sight((x,y),target,blocked)}
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
        from tio.protocol.battle_loot import LootTransfer,encode_loot_transfer,decode_container
        from tio.protocol.battle_position import BattlePositionRequest,encode_position_request
        def latest(index):
            return decode_item_list(next(p for p in reversed(received[index]) if p[0]==0x30 and decode_item_list(p)[0]==ids[index]))[1]
        drop_cell=None;dropped=None;taken=False;donor_moved=False
        for cycle in range(60):
            for index in sorted(range(2),key=lambda i:ids[i]):
                peer=peers[index];refresh(index)
                while not turn[index] and done[index] is None:
                    peer.receive();refresh(index)
                assert done[index] is None,'Battle ended before transfer'
                for action in range(30):
                    begin=len(received[index])
                    if index==0 and drop_cell is None:
                        route=path_to_enemy(index)
                        if route:peer.send(encode_move_request(BattleMove(ids[index],route[:4])))
                        else:
                            drop_cell=positions[index]
                            source=next(i for i in latest(index) if i.template_id==9)
                            peer.send(encode_loot_transfer(LootTransfer(ids[index],*drop_cell,((source.instance_id,1),))))
                    elif index==0 and not donor_moved:
                        x,y=positions[index]
                        target=next(p for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)) if p not in blocked and p!=positions[1] and 0<=p[0]<ground.width and 0<=p[1]<ground.height)
                        peer.send(encode_move_request(BattleMove(ids[index],(target,))))
                    elif index==1 and donor_moved and not taken:
                        if positions[index]!=drop_cell:
                            start=positions[index];queue=deque([start]);previous={start:None}
                            while queue and drop_cell not in previous:
                                x,y=queue.popleft()
                                for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                                    if cell in previous or cell in blocked or cell==positions[0] or not(0<=cell[0]<ground.width and 0<=cell[1]<ground.height):continue
                                    previous[cell]=(x,y);queue.append(cell)
                            assert drop_cell in previous
                            route=[];cell=drop_cell
                            while cell!=start:route.append(cell);cell=previous[cell]
                            peer.send(encode_move_request(BattleMove(ids[index],tuple(reversed(route))[:4])))
                        else:
                            peer.send(encode_position_request(BattlePositionRequest(ids[index],*drop_cell)))
                            case.ping(peer);refresh(index)
                            response=next((p for p in received[index][begin:] if p[0]==0x47),None)
                            if response is None:break
                            found=decode_container(response)[3]
                            assert len(found)==1 and found[0].template_id==9 and found[0].count==1
                            dropped=found[0].instance_id
                            assert dropped!=1003,'Permanent item did not receive unique battle ID'
                            peer.send(encode_loot_transfer(LootTransfer(ids[index],*drop_cell,(),((dropped,1),))))
                            case.ping(peer);refresh(index)
                            assert sum(i.count for i in latest(index) if i.template_id==9)==3
                            taken=True;break
                    else:break
                    case.ping(peer);refresh(index)
                    errors=[p for p in received[index][begin:] if p[0]==0xf0]
                    if errors:
                        if index==0 and drop_cell is not None and sum(i.count for i in latest(index) if i.template_id==9)==2:drop_cell=None
                        break
                    if index==0 and drop_cell is not None and positions[0]!=drop_cell:donor_moved=True
                    if not turn[index]:break
                if turn[index]:peer.send(encode_end_turn());case.ping(peer);refresh(index)
            if taken:break
        assert taken,'No shared ground transfer'
        for peer in peers:case.ping(peer)
        spawn=bytes((0x44,*drop_cell,0,0));remove=bytes((0x45,*drop_cell))
        for index in range(2):
            assert spawn in received[index],('No backpack for player',index)
            assert remove in received[index],('No empty-bag removal for player',index)
            assert not any(p[0]==0x30 and decode_item_list(p)[0]==ids[1-index] for p in received[index])
            assert sum(i.count for i in latest(index) if i.template_id==9)==(1 if index==0 else 3)
        final=[latest(i) for i in range(2)]
        for peer in peers:peer.send(b'\x2a\x01');case.ping(peer)
        for connection in case.clients:connection.close()
        case.clients=[];time.sleep(1)
        for index in range(2):
            peer=case.handoff(case.begin(names[index],passwords[index]));case.enter(peer,names[index])
            peer.send(b'\x2f\x01\0\x01\0\0\0')
            items=decode_item_list(peer.until(b'\x30'))[1]
            assert items==final[index],'Transferred items not persistent'
        result.update(passed=True,cell=drop_cell,ground_item_id=dropped,checks=[
            'two authenticated accounts in shared hosted battle',
            'native40 drop on empty ground without46; donor inventory decreases',
            'second player walks onto backpack and receives47, then picks item with40',
            'both players receive44 appearance and45 removal; inventory30 stays private',
            'bandage totals1 and3 survive leaving battle and authenticated reconnect'])
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':ground_run(sys.argv[1])
