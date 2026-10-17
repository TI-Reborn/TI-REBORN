"""Two fresh QA accounts on public encrypted TCP; not a graphical-client test."""
from verify_hosted_character_onboarding import *
import shlex,socket,subprocess,sqlite3
from tio.premium import encode_purchase
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase


def run(host):
    prefix='qp'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    ssh=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host]
    def remote(code,data):
        return subprocess.run(ssh+['cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(data),text=True,capture_output=True,check=True).stdout
    fixture='''
import json,sys,sqlite3
from pathlib import Path
from server.accounts import Accounts
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
d=json.load(sys.stdin);path='/var/lib/tio-server/reservation.sqlite3'
trial=json.loads(Path('evidence/owned_pet_trial.json').read_text())
for name,password in d:
 assert name.startswith('qp') and len(name)==11
 Accounts(path).create(name,password,character=name)
 OwnedPetStore(path).ensure(name,bytes.fromhex(trial['packet_hex']),bytes.fromhex(trial['inventory_packet_hex']),human=True)
 WalletStore(path).ensure(name)
with sqlite3.connect(path) as db:db.execute('UPDATE wallets SET gold=9 WHERE account=?',(d[1][0],))
'''
    result=dict(accounts=names,passed=False,kind=__doc__,checks=[])
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        sock=socket.create_connection((host,port),timeout=15);case.clients.append(sock);return sock
    case.connect=connect
    try:
        remote(fixture,list(zip(names,passwords)))
        peers=[]
        for name,password in zip(names,passwords):
            p=case.handoff(case.begin(name,password));case.enter(p,name);peers.append(p)
        a,b=peers
        a.send(encode_purchase(1,1));a.until(b'\xf0\x8a\x01\0\0')
        b.send(encode_purchase(1,10));b.until(b'\xf0\x8a\x01\0\0')
        a.send(encode_purchase(1,10));v=decode_asset_count(a.until(b'\xc8\x39'))
        assert v.gold==9990 and v.optional_raw[1]==1 and 86380<=v.optional_raw[0]<=86400
        a.send(encode_purchase(1,10));assert decode_asset_count(a.until(b'\xc8\x39')).gold==9990
        result['checks'].append('Daily purchase, bad quote and insufficient gold rejection, duplicate suppression')
        for peer,price in [(a,120),(b,150)]:
            peer.send(b'\x73\0');offers=decode_item_shop(peer.until(b'\x74'))[1]
            assert next(o.unknown_u32_03 for o in offers if o.unknown_u32_01==81)==price
        a.send(encode_shop_purchase(ShopPurchase(1,0,81,1)))
        v=decode_asset_count(a.until(b'\xc8\x39'));assert v.credits==9880 and v.optional_raw[1]==1
        result['checks'].append('Independent catalogs, 20% credit-shop discount matches wallet, status survives purchase')
        a.send(encode_purchase(4,200));v=decode_asset_count(a.until(b'\xc8\x39'))
        assert v.gold==9790 and v.optional_raw[1]==3 and 31*86400-60<=v.optional_raw[0]<=31*86400
        a.sock.close();time.sleep(1)
        a=case.handoff(case.begin(names[0],passwords[0]));case.character_screen(a)
        a.send(bytes.fromhex('1701000000'));a.until(b'\x18');a.send(b'\x19')
        v=decode_asset_count(a.until(b'\xc8\x39'));assert v.gold==9790 and v.optional_raw[1]==3
        result['checks'].append('Monthly anti-experience purchase transfers remaining day; reconnect retains status')
        result['passed']=True
    finally:
        for sock in case.clients:sock.close()
        (ROOT/f'evidence/hosted-premium-{prefix}.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':run(sys.argv[1])
