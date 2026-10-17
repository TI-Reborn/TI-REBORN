"""Two fresh hosted accounts through public encrypted TCP; no graphical client."""
from verify_hosted_character_onboarding import *
import shlex,socket,subprocess
from test_services import request
from test_player_auction import create_packet
from tio.protocol.binary import Reader,Writer
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.warehouse import decode_warehouse_list


def run(host):
    prefix='qs'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    ssh=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host]
    fixture='''
import json,sys,sqlite3
from pathlib import Path
from dataclasses import replace
from server.accounts import Accounts
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore
from tio.protocol.item_list import decode_item_list,encode_item_list
d=json.load(sys.stdin);path='/var/lib/tio-server/reservation.sqlite3'
trial=json.loads(Path('evidence/owned_pet_trial.json').read_text())
for name,password in d:
 assert name.startswith('qs') and len(name)==11
 Accounts(path).create(name,password,character=name)
 OwnedPetStore(path).ensure(name,bytes.fromhex(trial['packet_hex']),bytes.fromhex(trial['inventory_packet_hex']),human=True)
 WalletStore(path).ensure(name)
WarehouseStore(path)
item=replace(decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))[1][0],instance_id=77777,template_id=316,
 unknown_u32_01=1,unknown_u8_01=0,location_raw=0,unknown_bytes_02=bytes(4),optional_u32=None,
 unknown_words=(123,234,300),unknown_bytes_03=bytes((2,3,1)))
with sqlite3.connect(path) as db:db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',(d[0][0],77777,encode_item_list(0,(item,))))
'''
    report=dict(accounts=names,passed=False,kind=__doc__,checks=[])
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        sock=socket.create_connection((host,port),timeout=15);case.clients.append(sock);return sock
    case.connect=connect
    try:
        subprocess.run(ssh+['cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(fixture)],
                       input=json.dumps(list(zip(names,passwords))),text=True,capture_output=True,check=True)
        a=case.handoff(case.begin(names[0],passwords[0]));case.enter(a,names[0])
        b=case.handoff(case.begin(names[1],passwords[1]));case.enter(b,names[1])
        a.send(request(service=2));a.until(b'\xb1\x01')
        assert decode_asset_count(a.until(b'\xc8\x39')).credits==8000
        case.ping(a)
        a.send(request(service=2));a.until(b'\xb1\x01')
        assert decode_asset_count(a.until(b'\xc8\x39')).credits==8000
        case.ping(a)
        report['checks'].append('Service purchase charged once; paid status returned')
        a.send(create_packet(instance=77777));assert a.until(b'\xc8\x0c')==b'\xc8\x0c\x01\0\0\0'
        r=Reader(a.until(b'\xc8\x03')[2:]);assert r.u32()==1;lot=r.u32();report['lot']=lot
        assert decode_asset_count(a.until(b'\xc8\x39')).credits==7950
        case.ping(a)
        # Native Buy: page1, all types and complete enhancement/durability ranges.
        found=[];number=1
        while True:
            query=(Writer().u8(0xc8).u8(8).u32(0).u32(77).u8(1).u32(0).u32(0)
                   .u8(1).u8(0).u8(27).u8(1).u8(0).u8(100).u8(1).u32(3).u32(3).u32(number).build())
            b.send(query);page=b.until(b'\xc8\x09');r=Reader(page[2:])
            assert r.u32()==77 and r.u32()==number
            pages=r.u32();count=r.u32()
            for _ in range(count):
                found.append(r.u32());r.read(8)
                while r.u8():pass
                while r.u16():pass
                r.read(8)
                if r.u8():r.u32()
                r.read(r.u32()*15)
                if r.u8():
                    while r.u8():pass
                    r.read(8)
                r.u32()
            r.finish()
            if number>=pages:break
            number+=1
        assert lot in found and len(found)==len(set(found))
        report['checks'].append('Original UI filters and one-based pages: buyer sees seller lot, load-more has no duplicate pages')
        b.send(Writer().u8(0xc8).u8(0x10).u32(lot).build());assert b.until(b'\xc8\x11')[2:6]==lot.to_bytes(4,'little')
        b.send(Writer().u8(0xc8).u8(13).u32(lot).u32(1000).u32(0).build());b.until(b'\xc8\x02')
        assert decode_asset_count(b.until(b'\xc8\x39')).credits==9000
        case.ping(b)
        a.send(Writer().u8(0xc8).u8(14).u32(lot).build());a.until(b'\xf0\x8a\x01\0\0');case.ping(a)
        b.send(Writer().u8(0xc8).u8(15).u32(lot).build());b.until(b'\xc8\x04')
        assert decode_asset_count(b.until(b'\xc8\x39')).credits==7000
        goods=decode_warehouse_list(b.until(b'\x6a'))[3]
        assert goods[0].template_id==316
        assert len(goods)==1 and (goods[0].durability,goods[0].max_durability,goods[0].calculated_max_durability)==(123,234,300)
        assert (goods[0].enhance_level,goods[0].damage_enhance_level,goods[0].special_enhance)==(2,3,True)
        case.ping(a);a.send(b'\xb8\x11');assert decode_asset_count(a.until(b'\xc8\x39')).credits==11000
        report['checks'].append('Shared lot, 5% pledge, bid escrow, cancel with bid rejected, buyout and pledge refund')
        report['checks'].append('Buyer warehouse keeps current/max/calculated durability and all three enhancement fields')
        a.sock.close();time.sleep(1)
        a=case.handoff(case.begin(names[0],passwords[0]));case.enter(a,names[0])
        a.send(b'\xb1\x02');assert a.until(b'\xb1\x01')[3:7]==(2).to_bytes(4,'little')
        case.ping(a);a.send(b'\xb8\x11');assert decode_asset_count(a.until(b'\xc8\x39')).credits==11000
        report['checks'].append('Reconnect preserves purchased service and seller proceeds')
        report['passed']=True
    finally:
        for sock in case.clients:sock.close()
        (ROOT/f'evidence/hosted-services-auction-{prefix}.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run(sys.argv[1])
