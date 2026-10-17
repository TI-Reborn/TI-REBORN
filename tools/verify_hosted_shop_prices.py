"""Public encrypted TCP shopping with two fresh QA accounts; no player credentials."""
from verify_hosted_character_onboarding import *
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
from tio.protocol.binary import Reader
import socket
import struct


def premium_rows(packet):
    r=Reader(packet);assert r.u8()==0x77
    category=r.u32();revision=int.from_bytes(r.read(8),'little');r.u8();rows={}
    for _ in range(r.u32()):
        lot,item,pack=r.u16(),r.u32(),r.u32();r.u32();r.u32()
        currency,price=r.u8(),r.u32();assert currency==2
        assert r.u8()==0;r.u8();r.u32();assert r.u8()==0
        r.u32();r.u32();assert r.u8()==0;assert r.u8()==0
        rows[item]=(lot,pack,price)
    r.finish();return category,revision,rows


def run(host):
    prefix='qs'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result={'accounts':names,'kind':'public encrypted TCP; not graphical clients','checks':[],'passed':False}
    output=ROOT/f'evidence/hosted-shop-{prefix}.json'
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        c=socket.create_connection((host,port),timeout=15);case.clients.append(c);return c
    case.connect=connect
    try:
        for name,password in zip(names,passwords):
            origin='https://'+host
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            html=opener.open(origin+'/register/',timeout=15).read()
            csrf=re.search(rb'name="csrf" value="([^"]+)"',html)[1].decode()
            data=urllib.parse.urlencode(dict(csrf=csrf,login=name,password=password,confirm=password)).encode()
            assert opener.open(urllib.request.Request(origin+'/register/',data=data,headers={'Origin':origin}),timeout=15).status==201
        peers=[]
        for name,password in zip(names,passwords):
            peer=case.handoff(case.begin(name,password));peers.append(peer)
            assert case.character_screen(peer)==()
            peer.send(encode_character_create(CharacterCreateRequest(name.encode(),0,(1,0,0,0))))
            assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
            peer.send(bytes.fromhex('1701000000'))
            assert peer.receive()==b'\x12\x05';assert peer.receive()[0]==0x10
            peer.send(encode_request(1,bytes((1,5,1,3,0,0))))
            peer.until(b'\x10');peer.send(bytes.fromhex('1701000000'))
            assert peer.receive()[0]==0x18
            peer.send(b'\x19');peer.until(b'\x66');case.ping(peer)
        a,b=peers
        catalogs=[]
        for peer in peers:
            peer.send(b'\x73\0');_,rows=decode_item_shop(peer.until(b'\x74'))
            assert len(rows)==78;cr={o.item_id:o for o in rows}
            assert cr[304].unknown_u32_03==900 and cr[3].unknown_u32_03==50
            assert 326 not in cr and 32 not in cr and 252 not in cr
            peer.send(b'\x76'+bytes(4));category,revision,gold=premium_rows(peer.until(b'\x77'))
            assert len(gold)==55 and gold[9][1:]==(3,1) and gold[252][2]==126
            catalogs.append((cr,gold,revision))
        result['checks'].append('two accounts receive identical 78-credit and 55-Gold native catalogs')
        cr,gold,revision=catalogs[0]
        a.send(encode_shop_purchase(ShopPurchase(1,0,cr[304].unknown_u32_01,1)))
        bought=decode_item_list(a.until(b'\x30'))[1]
        wallet=decode_asset_count(a.until(b'\xc8\x39'))
        assert any(i.template_id==304 for i in bought)
        assert wallet.credits==9100 and wallet.gold==10000
        a.until(b'\xb5\x03');bonus=decode_asset_count(a.until(b'\xc8\x39'));assert bonus.credits==9200
        packet=struct.pack('<BIIIIIQI',0x78,1,gold[9][0],2,1,0,revision,0)
        a.send(packet);items=decode_item_list(a.until(b'\x30'))[1]
        wallet=decode_asset_count(a.until(b'\xc8\x39'))
        assert wallet.credits==9200 and wallet.gold==9998
        assert sum(i.count for i in items if i.template_id==9)==6
        result['checks'].append('AK-47 costs 900 credits; two Gold bandage packs cost 2 Gold and deliver six bandages')
        # Old fixture ID, wrong revision and insufficient Gold must reject without a purchase.
        for denied in [encode_shop_purchase(ShopPurchase(1,0,2,1)),
                       struct.pack('<BIIIIIQI',0x78,1,1326,1,1,0,revision-1,0),
                       struct.pack('<BIIIIIQI',0x78,1,1252,1000,1,0,revision,0)]:
            a.send(denied);a.until(b'\xf0');case.ping(a)
        a.send(b'\x2f\x01\0\x01\0\0\0');assert decode_item_list(a.until(b'\x30'))[1]==items
        b.send(b'\x2f\x01\0\x01\0\0\0');other=decode_item_list(b.until(b'\x30'))[1]
        assert not any(i.template_id in (304,9) for i in other)
        result['checks'].append('forged credit offer, stale price revision and insufficient Gold rejected; second account inventory isolated')
        for c in case.clients:c.close()
        case.clients=[];time.sleep(1)
        a=case.handoff(case.begin(names[0],passwords[0]));case.character_screen(a)
        a.send(bytes.fromhex('1701000000'));assert a.receive()[0]==0x18
        a.send(b'\x19');a.until(b'\x66');case.ping(a)
        a.send(b'\x2f\x01\0\x01\0\0\0');assert decode_item_list(a.until(b'\x30'))[1]==items
        result['checks'].append('purchased inventory survives disconnect and authentication again')
        result['passed']=True
    finally:
        for c in case.clients:c.close()
        output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    return result


if __name__=='__main__':run(sys.argv[1])
