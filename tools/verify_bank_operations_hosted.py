"""Two excluded hosted TLS accounts check bank operations after installation.

Requires installed code hashes before provisioning. No wallet/item SQL seeding.
Graphical client acceptance is separate. Generated credentials/PIN stay private.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
import socket
import ssl
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'work/bank-trade-release-20261015/candidate'
sys.path[:0]=[str(CANDIDATE),str(ROOT/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from tio.city_catalogs import CityCatalogs
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.item_list import decode_item_list
from tio.rating_visibility import QA_LOGIN
from tools.verify_game_operations_hosted import remote,CREATE,CLEANUP,HTTP
# The reusable administration helper has its own historical candidate path.
sys.path[:0]=[str(CANDIDATE),str(ROOT/'tests'),str(ROOT)]
REPORT=ROOT/'reports/bank-operations-20261015'

INSTALLED=r'''
from pathlib import Path
import json,hashlib
assert all(hashlib.sha256((Path('/opt/tio-emulator')/p).read_bytes()).hexdigest()==r['after'] for p,r in request.items()),'Bank candidate is not installed'
print(json.dumps(dict(installed_files_verified=len(request))))
'''

STATE=r'''
from tio.rating_visibility import QA_LOGIN,excluded
import sqlite3,json
assert len(request)==2 and all(QA_LOGIN.fullmatch(n) for n in request)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=[]
 for n in request:
  held=db.execute('SELECT stocks,bonds FROM bank_securities WHERE account=?',(n,)).fetchone()
  rows.append(dict(wallet=list(db.execute('SELECT credits,gold FROM wallets WHERE account=?',(n,)).fetchone()),
   holdings=list(held) if held else [0,0],excluded=excluded(db,n),
   inventory=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0].hex(),
   warehouse=[bytes(r[0]).hex() for r in db.execute('SELECT item_packet FROM warehouse_items WHERE account=? ORDER BY instance_id',(n,))]))
print(json.dumps(rows))
'''


def run():
    installed=remote(INSTALLED,json.loads((REPORT/'patch-manifest.json').read_text()))
    prefix='qb'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for n in names];pin=str(secrets.randbelow(900000)+100000)
    assert all(QA_LOGIN.fullmatch(n) for n in names)
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();report=dict(passed=False,kind='two hosted TLS protocol clients and private HTTP; graphical client not checked',
        fixtures=names,installed=installed,checks=[])
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def http(kind,payload,expected=200,port=8082,authenticated=True):
        response=remote(HTTP,dict(api='v1/city',kind=kind,payload=payload,port=port,authenticated=authenticated))
        assert response['code']==expected,(kind,response['code'],expected)
        return response.get('body')
    def status(i,port=8082):return http('status',dict(username=names[i],slot=1),port=port)
    def request(i,action,nonce=None,**args):
        return dict(username=names[i],slot=1,action=action,requestId=nonce or secrets.token_hex(16),**args)
    def native(peer,text=None,packet=None):
        if text is not None:packet=b'\x21\0'+text.encode('utf-16-le')+b'\0\0'
        if packet is not None:peer.send(packet)
        # B103 is a request-specific city-service barrier; 9E is also heartbeat.
        peer.send(b'\xb1\x02');packets=[]
        for _ in range(2048):
            reply=peer.receive()
            if reply.startswith(b'\xb1\x03'):return packets
            packets.append(reply)
        raise AssertionError('Missing city service barrier')
    def state():return remote(STATE,names)
    def stock_buy(i,quote,count,nonce):return request(i,'stocks_buy',nonce,count=count,quote=quote)
    provision=None
    try:
        provision=remote(CREATE,list(zip(names,passwords)))
        report['provisioning']={k:v for k,v in provision.items() if k!='protected_before'}
        peers=[]
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,34001+i,password=password));case.enter(peer,name)
            native(peer,packet=struct.pack('<Bii',0x1b,-154,-318));peers.append(peer)
            assert status(i)['canOperate']
        assert all(s['wallet']==[3000,0] and s['excluded'] for s in state())
        quote=status(0)['quotes']['stocks']['price'];identity=secrets.token_hex(16)
        native(peers[0],f'!bank stocks buy 2 {quote} {identity}')
        after=state();assert after[0]['wallet']==[3000-2*quote,0] and after[0]['holdings']==[2,0]
        assert after[1]['wallet']==[3000,0]
        replay=http('action',stock_buy(0,quote,2,identity),port=8083)
        assert replay['replayed'] and replay['receipt']['creditsDelta']==-2*quote
        assert set(replay['receipt'])=={'requestId','action','creditsDelta','goldDelta'}
        native(peers[0],f'!bank stocks buy 2 {quote} {identity}');assert state()==after
        # Same ID belongs to this other owner independently.
        first=http('action',stock_buy(1,quote,1,identity));assert not first['replayed']
        native(peers[1],f'!bank stocks buy 1 {quote} {identity}')
        assert state()[1]['wallet']==[3000-quote,0]
        report['checks'].append('native/HTTP replay shares original receipt; account-scoped identity and balances remain independent')
        nonce=secrets.token_hex(16)
        with ThreadPoolExecutor(max_workers=1) as pool:
            submitted=pool.submit(http,'action',stock_buy(0,quote,1,nonce))
            native(peers[0],f'!bank stocks buy 1 {quote} {nonce}');submitted.result()
        after=state();assert after[0]['wallet']==[3000-3*quote,0] and after[0]['holdings']==[3,0]
        http('action',stock_buy(0,quote+1,1,secrets.token_hex(16)),409)
        http('action',dict(stock_buy(0,quote,1,secrets.token_hex(16)),owner=names[1]),400)
        http('action',request(0,'convert',gold=1),409)
        http('status',{},401,authenticated=False)
        assert state()==after
        sold=secrets.token_hex(16);native(peers[0],f'!bank stocks sell 3 {quote} {sold}')
        assert http('action',request(0,'stocks_sell',sold,count=3,quote=quote))['replayed']
        native(peers[1],f'!bank stocks sell 1 {quote} {secrets.token_hex(16)}')
        assert all(s['wallet']==[3000,0] and s['holdings']==[0,0] for s in state())
        report['checks'].append('concurrent native/HTTP request charges once; invalid/stale/Gold requests do not mutate; securities sell and replay persist')
        bonds=status(0)['quotes']['bonds'];bond_cost=0
        if bonds['saleOpen']:
            bond_cost=bonds['priceGold'];nonce=secrets.token_hex(16)
            first=http('action',request(0,'bonds_buy',nonce,count=1,quote=bond_cost));assert first['receipt']['creditsDelta']==-bond_cost
            native(peers[0],f'!bank bonds buy 1 {bond_cost} {nonce}')
            assert state()[0]['wallet']==[3000-bond_cost,0] and state()[0]['holdings']==[0,1]
            report['checks'].append('bonds use credits, retain calendar gate, and replay between website and native protocol')
        else:report['checks'].append('current bond sale window closed; calendar cases covered by automated tests')
        before=state();old_ids={i.instance_id for i in decode_item_list(bytes.fromhex(before[0]['inventory']))[1]}
        offer=next(o for o in CityCatalogs(CANDIDATE/'config/city_catalogs.json').items[0] if o.item_id==301)
        native(peers[0],packet=encode_shop_purchase(ShopPurchase(1,0,offer.unknown_u32_01,1)))
        bought=state()
        item=next(i for i in decode_item_list(bytes.fromhex(bought[0]['inventory']))[1] if i.template_id==301 and i.instance_id not in old_ids)
        nonce=secrets.token_hex(16);native(peers[0],f'!bank mark {item.instance_id} 1 {pin} {nonce}')
        marked=http('action',request(0,'mark',nonce,instanceId=item.instance_id,days=1,pin=pin))
        assert marked['replayed'];mark=next(m['id'] for m in marked['status']['marks'] if m['templateId']==301)
        nonce=secrets.token_hex(16)
        lent=http('action',request(0,'lend',nonce,markId=mark,recipientName=names[1]));assert not lent['replayed']
        native(peers[0],f'!bank lend {mark} {names[1]} {nonce}')
        loaned=state();assert any(decode_item_list(bytes.fromhex(raw))[1] for raw in loaned[1]['warehouse'])
        wrong='000000' if pin!='000000' else '000001'
        denied=http('action',request(0,'reclaim',markId=mark,pin=wrong,remove=True),409)
        assert denied['error']=='pin_rejected' and state()==loaned
        nonce=secrets.token_hex(16);native(peers[0],f'!bank reclaim {mark} {pin} {nonce} remove')
        returned=http('action',request(0,'reclaim',nonce,markId=mark,pin=pin,remove=True));assert returned['replayed']
        after=state();assert after[1]['warehouse']==[] and len(after[0]['warehouse'])==1
        assert next(m for m in returned['status']['marks'] if m['id']==mark)['state']=='removed'
        assert all(pin not in json.dumps(reply) for reply in (marked,lent,denied,returned))
        report['checks'].append('ordinary weapon purchase, marking, cross-account loan and PIN return preserve one item; wrong PIN and retries do not duplicate/debit')
        for peer in peers:peer.sock.close()
        time.sleep(1)
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,34101+i,password=password));case.enter(peer,name);native(peer)
        assert state()==after
        for port in (8082,8083):
            assert status(0,port)['balances']['credits']==after[0]['wallet'][0]
        report['checks'].append('both accounts reconnect with authoritative holdings, wallets and physical returned item')
        report['passed']=True
    finally:
        for connection in case.clients:
            try:connection.close()
            except OSError:pass
        time.sleep(1)
        try:
            if provision:
                report['cleanup']=remote(CLEANUP,dict(names=names,protected_before=provision['protected_before'],
                    require_unchanged_players=False))
        except BaseException:
            report['passed']=False;report['cleanup_failed']=True;raise
        finally:(REPORT/'hosted-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':run()
