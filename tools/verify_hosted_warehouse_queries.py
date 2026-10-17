"""Two fresh QA accounts exercise deployed warehouse queries over public encrypted TCP.

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


def warehouse_run(host):
    import socket
    prefix='qw'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result=dict(accounts=names,kind='public encrypted TCP; no graphical clients',checks=[],passed=False)
    output=ROOT/f'evidence/hosted-warehouse-queries-{prefix}.json'
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
        from tio.protocol.warehouse import decode_warehouse_list
        from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
        expectations=[];wallets=[]
        for index,peer in enumerate(peers):
            peer.send(b'\x73\0');_,offers=decode_item_shop(peer.until(b'\x74'))
            template=(301,210)[index];offer=next(o for o in offers if o.item_id==template)
            peer.send(encode_shop_purchase(ShopPurchase(1,0,offer.unknown_u32_01,1)))
            items=decode_item_list(peer.until(b'\x30'))[1];case.ping(peer)
            target=next(i for i in items if i.template_id==template)
            peer.send(encode_warehouse_transfer(WarehouseTransfer(0,1,((target.instance_id,1),),())))
            packet=peer.until(b'\x6a');kind,total,segment,warehouse=decode_warehouse_list(packet);case.ping(peer)
            assert (kind,total,segment)==(0,1,0) and len(warehouse)==1 and warehouse[0].template_id==template
            expectations.append(warehouse)
            peer.send(bytes.fromhex('b811'));asset=decode_asset_count(peer.until(bytes.fromhex('c839')));case.ping(peer)
            wallets.append(asset)
        assert wallets[0].credits!=wallets[1].credits
        for index,peer in enumerate(peers):
            for request,expected in (('b804','c82900000000'),('b809','b80a00000000'),('6903','b77500000000')):
                peer.send(bytes.fromhex(request));packet=peer.until(bytes.fromhex(expected[:4]));assert packet.hex()==expected;case.ping(peer)
            for kind in (1,2):
                peer.send(bytes((0x69,kind)))
                assert decode_warehouse_list(peer.until(b'\x6a'))==(kind,1,0,())
                peer.until(b'\xf0');case.ping(peer)
            for kind in (1,2,3):
                peer.send(encode_warehouse_transfer(WarehouseTransfer(kind,1,(),((expectations[index][0].instance_id,1),))))
                peer.until(b'\xf0');case.ping(peer)
            peer.send(bytes.fromhex('b81100'));peer.until(b'\xf0');case.ping(peer)
            peer.send(bytes.fromhex('b811'));assert decode_asset_count(peer.until(bytes.fromhex('c839')))==wallets[index];case.ping(peer)
            peer.send(b'\x69\0');assert decode_warehouse_list(peer.until(b'\x6a'))[3]==expectations[index];case.ping(peer)
        for connection in case.clients:connection.close()
        case.clients=[];time.sleep(1)
        for index in range(2):
            peer=case.handoff(case.begin(names[index],passwords[index]));case.enter(peer,names[index])
            peer.send(b'\x69\0');assert decode_warehouse_list(peer.until(b'\x6a'))[3]==expectations[index]
            peer.send(bytes.fromhex('b811'));actual=decode_asset_count(peer.until(bytes.fromhex('c839')))
            # Existing achievement38 pays on city re-entry after the first
            # normal-shop purchase. Query must return that NEW saved balance.
            from dataclasses import replace
            achievement=next(r for r in json.loads((ROOT/'config/achievements.json').read_text(encoding='utf-8'))['records'] if r['id']==38)
            reward=achievement['temporary_credits']
            assert actual==replace(wallets[index],credits=wallets[index].credits+reward),(actual,wallets[index])
            result.setdefault('reentry_credits',[]).append(actual.credits)
            result['existing_first_purchase_achievement_reward']=reward
        result.update(passed=True,credits=[w.credits for w in wallets],stored_templates=[w[0].template_id for w in expectations],
            checks=['two fresh authenticated accounts with different purchases and balances',
            'normal personal deposit and re-login persistence remain correct',
            'B804 marks C829, B809 assault ranking B80A, B811 actual account assets C839',
            'clan/safe clear only requested caches and return refusal; postbox B775 empty',
            'non-personal transfer and malformed query rejected without changing own or other account data'])
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':warehouse_run(sys.argv[1])

