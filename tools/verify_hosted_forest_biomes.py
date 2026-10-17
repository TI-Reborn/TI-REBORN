"""Fresh real hosted accounts, encrypted TCP gameplay/loot/shop/shared auction.

Only QA accounts receive a strong weapon/high HP to make the combat check reliable.
This is an automated protocol check; it does not validate graphical rendering.
"""
from verify_hosted_encounters import *
from dataclasses import replace
from tio.protocol.battle_ground import decode_battle_ground
from tio.protocol.battle_attack import decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_sale import ShopSale,encode_sale_request
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.binary import Reader,Writer
from tio.protocol.system_message import encode_open_town_view
from tio.locations import center
from test_player_auction import create_packet
OUT=ROOT/'reports/forest-biomes'

def remote(code,data):
    p=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(data),capture_output=True,text=True,encoding='utf-8')
    if p.returncode:raise RuntimeError(p.stderr)
    return json.loads(p.stdout) if p.stdout.strip() else None

def provision_qa(names,passwords):
    remote('''import json,sys,sqlite3
from pathlib import Path
from dataclasses import replace
from server.accounts import Accounts
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.squad import SquadStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
path='/var/lib/tio-server/reservation.sqlite3';a=Accounts(path);pets=OwnedPetStore(path)
trial=json.loads(Path('evidence/owned_pet_trial.json').read_text());original=bytes.fromhex(trial['packet_hex'])
for n,p in json.load(sys.stdin):
 assert n.startswith('qf');a.create(n,p,character=n)
 inventory=encode_item_list(1,(ItemRecord(101,304,b'\\0\\0',1,1,16,(300,300,300),b'\\0'*4,None,b'\\0'*3),ItemRecord(102,7,b'\\0\\0',200,0,0,(0,0,0),b'\\0'*4,None,b'\\0'*3)))
 pets.ensure(n,original,inventory,human=True);WalletStore(path).ensure(n)
 with sqlite3.connect(path) as d:
  raw=d.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]
  pet=decode_pet_info(raw,human_equipment=True)
  pet=replace(pet,fields={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000})
  d.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(pet),inventory,n))
 SquadStore(path).assign(n,1,1)
''',list(zip(names,passwords)))

def connect_case(host,name,password):
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        sock=socket.create_connection((host,port),timeout=15);case.clients.append(sock);return sock
    case.connect=connect
    def ping(peer):peer.send(b'\x70');peer.until(b'\x9e',max_packets=4096)
    case.ping=ping
    peer=case.handoff(case.begin(name,password));case.enter(peer,name)
    return case,peer

def play_forest(host,name,password):
    case,peer=connect_case(host,name,password)
    state=dict(actors={},ground=None,turn=False,summary=None,turns=0,attacks=0,bag=(),warehouse=(),credits=None,moves=0,errors=[])
    original=peer.receive
    def receive():
        packet=original()
        if packet[0]==0x35:state['ground']=decode_battle_ground(packet)
        elif packet[0]==0x3b:
            resource=int.from_bytes(packet[9:13],'little');actor=decode_battle_soldier(packet,human_equipment=resource in (1,2,6,100))
            state['actors'][actor.soldier_id]=dict(owner=actor.owner_id,resource=resource,position=actor.position,hp=actor.fields['0x8c57bb'],ap=actor.fields['0x8c571d'])
        elif packet[0]==0x3d:
            move=decode_battle_move(packet)
            if move.actor_id in state['actors'] and move.path:state['actors'][move.actor_id]['position']=move.path[-1];state['moves']+=1
        elif packet[0]==0x43:
            identity=int.from_bytes(packet[1:5],'little')
            if identity in state['actors']:state['actors'][identity]['position']=(255,255)
        elif packet[0]==0x4b:
            for hit in decode_attack_result(packet).hits:
                if hit.actor_id in state['actors']:state['actors'][hit.actor_id]['hp']=hit.left_hp
        elif packet[0]==0x4e and len(packet)==18 and int.from_bytes(packet[5:9],'little')==1:
            identity=int.from_bytes(packet[1:5],'little');attribute=int.from_bytes(packet[9:13],'little')
            if identity in state['actors'] and attribute in (4,10):state['actors'][identity]['hp' if attribute==4 else 'ap']=int.from_bytes(packet[13:17],'little')
        elif packet[0]==0x38:state['turn']=True;state['turns']+=1
        elif packet[0]==0x39:state['turn']=False
        elif packet[0]==0x4c:state['summary']=packet
        elif packet[0]==0x30:
            owner,items,_=decode_item_list(packet)
            if owner==1:state['bag']=items
        elif packet[0]==0x6a:state['warehouse']=decode_warehouse_list(packet)[3]
        elif packet[:2]==b'\xc8\x39':state['credits']=decode_asset_count(packet).credits
        elif packet[:5]==b'\xf0\x8a\x01\0\0':state['errors'].append(packet.hex())
        return packet
    peer.receive=receive
    try:
        peer.send(struct.pack('<Bii',0x1b,400,300));deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            if peer.receive()==b'\x41':break
        else:raise AssertionError('Natural encounter timed out')
        g=state['ground'];brush=set(g.first_layer);assert len(brush)==1 and brush<={7,8,9}
        print(json.dumps(dict(account=name,stage='natural encounter',brush=list(brush))),flush=True)
        assert g.unknown_u8==0 and g.entries
        assert all(b'box' not in e.name and b'crate' not in e.name for e in g.entries)
        hero=next(i for i,a in state['actors'].items() if a['owner']==1)
        fragments=json.loads((ROOT/'config/arena_fragments.json').read_text());blocked=set();opaque=set()
        for entry in g.entries:
            f=fragments[entry.name.decode()+'.s'];x,y=entry.unknown_u8_01,entry.unknown_u8_02
            for j in range(f['height']):
                for i in range(f['width']):
                    kind=f['tiles'][j*f['width']+i]
                    if kind in (2,3,4):blocked.add((x+i,y+j))
                    if kind==3:opaque.add((x+i,y+j))
        from tio.shot_geometry import clear_shot
        waypoints=[(g.width//2,g.height//2),(g.width//4,g.height//4),(3*g.width//4,g.height//4),(3*g.width//4,3*g.height//4),(g.width//4,3*g.height//4)]
        waypoint=0
        def path_to(start,targets,occupied):
            pending=deque([start]);prev={start:None};targetset=set(targets)
            while pending:
                p=pending.popleft()
                if p in targetset:
                    path=[]
                    while prev[p] is not None:path.append(p);p=prev[p]
                    return tuple(reversed(path))
                x,y=p
                for q in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if q not in prev and q not in blocked and q not in occupied and 0<=q[0]<g.width and 0<=q[1]<g.height:prev[q]=p;pending.append(q)
            return ()
        peer.send(b'\x36');deadline=time.monotonic()+240
        while state['summary'] is None and time.monotonic()<deadline and state['turns']<60:
            if not state['turn']:peer.receive();continue
            for action in range(6):
                if state['summary'] is not None or not state['turn']:break
                own=state['actors'][hero];start=own['position'];ap=own['ap']
                visible=[a for a in state['actors'].values() if a['resource']==103 and a['hp'] and a['position']!=(255,255)]
                shootable=[a for a in visible if (a['position'][0]-start[0])**2+(a['position'][1]-start[1])**2<=64 and clear_shot(start,a['position'],opaque)]
                if shootable and ap>=5:
                    target=min(shootable,key=lambda a:(a['position'][0]-start[0])**2+(a['position'][1]-start[1])**2)
                    peer.send(encode_attack_request(AttackRequest(hero,*target['position'])));state['attacks']+=1;case.ping(peer);continue
                if ap<2:break
                occupied={a['position'] for i,a in state['actors'].items() if i!=hero and a['hp'] and a['position']!=(255,255)}
                if visible:
                    target=min(visible,key=lambda a:abs(a['position'][0]-start[0])+abs(a['position'][1]-start[1]))['position']
                    targets=[(x,y) for x in range(max(0,target[0]-3),min(g.width,target[0]+4)) for y in range(max(0,target[1]-3),min(g.height,target[1]+4)) if (x,y) not in blocked and (x,y) not in occupied and clear_shot((x,y),target,opaque)]
                else:
                    target=waypoints[waypoint%len(waypoints)]
                    nearest=min(((x,y) for x in range(g.width) for y in range(g.height) if (x,y) not in blocked and (x,y) not in occupied),key=lambda p:abs(p[0]-target[0])+abs(p[1]-target[1]))
                    if start==nearest:waypoint+=1;continue
                    targets=[nearest]
                path=path_to(start,targets,occupied)
                if not path:break
                steps=max(1,ap-5) if visible else ap
                before=start;peer.send(encode_move_request(BattleMove(hero,path[:steps])));case.ping(peer)
                if state['actors'][hero]['position']==before:break
            if state['summary'] is None and state['turn']:peer.send(encode_end_turn(0));state['turn']=False
        assert state['summary'] is not None,dict(turns=state['turns'],actors=state['actors'])
        summary=state['summary'];assert summary[3]==1,summary.hex()
        print(json.dumps(dict(account=name,stage='victory',turns=state['turns'],attacks=state['attacks'])),flush=True)
        assert int.from_bytes(summary[4:8],'little')==2 and int.from_bytes(summary[20:24],'little')==75
        peer.send(b'\x2a\x01');peer.until(b'\x1e',max_packets=4096);case.ping(peer)
        materials={i.template_id:i.count for i in state['bag'] if i.template_id in (65487,65488)};assert materials=={65487:2,65488:4},materials
        peer.send(b'\x2a\x01');peer.until(b'\x1e',max_packets=4096);case.ping(peer)
        assert {i.template_id:i.count for i in state['bag'] if i.template_id in (65487,65488)}==materials
        peer.send(struct.pack('<Bii',0x1b,*center(3)));peer.until(encode_open_town_view(),max_packets=4096);case.ping(peer)
        report=dict(account=name,passed=True,ground_brush=next(iter(brush)),dimensions=[g.width,g.height],objects=len(g.entries),crates=0,turns=state['turns'],attacks=state['attacks'],loot=materials)
        return case,peer,state,report
    except BaseException:
        (OUT/(name+'-failure.json')).write_text(json.dumps(dict(actors=state['actors'],turns=state['turns'],attacks=state['attacks'],moves=state['moves'],errors=state['errors']),indent=2)+'\n')
        if state['ground'] is not None and state['summary'] is None:
            try:peer.send(b'\x2a\x01');case.ping(peer)
            except Exception:pass
        for sock in case.clients:sock.close()
        raise

def main(host):
    names=['qf'+secrets.token_hex(4)+s for s in ('a','b')];passwords=[secrets.token_urlsafe(24) for _ in names]
    provision_qa(names,passwords);connections=[];report=dict(passed=False,accounts=names,graphical=False,qa_fixture='AK47, 200 rounds, 1000 HP only on these fresh QA accounts')
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(play_forest,host,n,p) for n,p in zip(names,passwords)]
            for future in futures:connections.append(future.result())
        (ac,a,sa,ra),(bc,b,sb,rb)=connections;report['clients']=[ra,rb]
        hide=next(i for i in sa['bag'] if i.template_id==65487);credits=sa['credits']
        request=ShopSale(1,hide.instance_id,1);a.send(encode_sale_request(request,quote=True))
        quote=a.until(b'\xb8\x07');assert int.from_bytes(quote[6:10],'little')==30;ac.ping(a)
        meat=next(i for i in sa['bag'] if i.template_id==65488)
        a.send(encode_sale_request(ShopSale(1,meat.instance_id,1),quote=True))
        quote=a.until(b'\xb8\x07');assert int.from_bytes(quote[6:10],'little')==10;ac.ping(a)
        a.send(encode_sale_request(request));a.until(b'\xc8\x39');ac.ping(a);assert sa['credits']==credits+30
        hide=next(i for i in sa['bag'] if i.template_id==65487);assert hide.count==1
        a.send(encode_warehouse_transfer(WarehouseTransfer(0,1,((hide.instance_id,1),),())));a.until(b'\x6a');ac.ping(a)
        stored=next(i for i in sa['warehouse'] if i.template_id==65487)
        a.send(create_packet(instance=stored.instance_id,count=1,price=100,step=10,buyout=200));a.until(b'\xc8\x0c')
        added=Reader(a.until(b'\xc8\x03')[2:]);assert added.u32()==1;lot=added.u32();ac.ping(a)
        buyer_before=sb['credits'];b.send(Writer().u8(0xc8).u8(15).u32(lot).build());b.until(b'\xc8\x04');bc.ping(b)
        assert sb['credits']==buyer_before-200
        assert sum(i.count for i in sb['warehouse'] if i.template_id==65487)==1
        time.sleep(2.1);ac.ping(a);assert sa['credits']==credits+30+200
        report.update(shop_hide_price=30,shop_meat_price=10,auction_lot=lot,buyout=200)
        for case,peer,_,_ in connections:
            for sock in case.clients:sock.close()
        time.sleep(1)
        reconnect=[]
        for n,p in zip(names,passwords):
            case,peer=connect_case(host,n,p);reconnect.append(case)
            try:peer.send(bytes.fromhex('2f010001000000'));inventory=decode_item_list(peer.until(b'\x30',max_packets=4096))[1];case.ping(peer)
            finally:
                for sock in case.clients:sock.close()
        saved=remote('''import json,sys,sqlite3
from tio.protocol.item_list import decode_item_list
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
def materials(packets):
 result={}
 for p, in packets:
  for i in decode_item_list(p)[1]:
   if i.template_id in (65487,65488):result[i.template_id]=result.get(i.template_id,0)+i.count
 return result
print(json.dumps({n:dict(encounters=d.execute('SELECT match_id FROM world_encounter_audit WHERE account=?',(n,)).fetchall(),
 rewards=d.execute('SELECT result,credits FROM battle_rewards WHERE account=?',(n,)).fetchall(),
 loot=d.execute('SELECT template_id,amount,destination FROM encounter_loot_awards WHERE account=?',(n,)).fetchall(),
 bag=materials(d.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(n,))),warehouse=materials(d.execute('SELECT item_packet FROM warehouse_items WHERE account=?',(n,))),
 credits=d.execute('SELECT credits FROM wallets WHERE account=?',(n,)).fetchone()[0]) for n in json.load(sys.stdin)}))''',names)
        for n in names:
            assert len(saved[n]['encounters'])==1 and saved[n]['rewards']==[[1,75]]
            assert {int(t):q for t,q,_ in saved[n]['loot']}=={65487:2,65488:4}
        assert saved[names[0]]['bag']=={'65488':4} and saved[names[0]]['warehouse']=={}
        assert saved[names[1]]['bag']=={'65487':2,'65488':4} and saved[names[1]]['warehouse']=={'65487':1}
        assert saved[names[0]]['encounters']!=saved[names[1]]['encounters']
        report.update(passed=True,persisted=saved,checks=['Two independent natural travel encounters and victories','Native ground 7/8/9, no crate entries','Persistent loot, repeated finish gives no duplicate','Shop partial stack sale and shared auction transfer','Reconnect and DB ownership/settlement verification'])
    finally:
        for case,_,_,_ in connections:
            for sock in case.clients:sock.close()
        (OUT/'hosted-tcp.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main(sys.argv[1])
