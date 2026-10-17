"""Three disposable excluded accounts verify native barter through production TLS."""
from pathlib import Path
import hashlib,json,secrets,socket,ssl,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_english_localization_hosted import remote,CREATE,CLEANUP
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from tio.protocol import player_trade as wire
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.item_list import decode_item_list
from tio.rating_visibility import QA_LOGIN
REPORT=ROOT/'reports/direct-trade-20261014'

STATE=r'''
import sqlite3,json
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows={}
 for name in request:
  rows[name]=dict(wallet=list(db.execute('SELECT credits,gold FROM wallets WHERE account=?',(name,)).fetchone()),
   inventory=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()[0].hex())
 print(json.dumps(rows))
'''

def run():
    names=['qt'+secrets.token_hex(4)+suffix for suffix in ('a','b','c')]
    passwords=[secrets.token_urlsafe(24) for _ in names]
    assert all(QA_LOGIN.fullmatch(n) for n in names)
    report=dict(passed=False,graphical_clients_used=False,kind='three independent production TLS protocol accounts')
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context()
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect;created=False
    def state():return remote(STATE,names)
    def ask(peer,packet,prefix):peer.send(packet);return peer.until(prefix,max_packets=1024)
    def opened(a,b):
        ask(a,wire.invite_request(names[1].encode(),1),b'\x22')
        assert b.until(b'\x85',max_packets=1024)==wire.invitation(names[0].encode())
        b.send(wire.answer_request(True,1));a.until(b'\x87',max_packets=1024);b.until(b'\x87',max_packets=1024)
    try:
        report['provisioning']=remote(CREATE,list(zip(names,passwords)));created=True
        peers=[]
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,32001+i,password=password,language='english' if i else 'russian'))
            case.enter(peer,name);peers.append(peer)
        a,b,c=peers
        ask(a,encode_shop_purchase(ShopPurchase(1,0,3,1)),b'\x30');case.ping(a)
        # Flush the normal purchase achievement before measuring the exchange.
        remote("from tio.achievements import AchievementStore; import json; AchievementStore('/var/lib/tio-server/reservation.sqlite3').flush(request[0]); print(json.dumps({'flushed':True}))",names)
        initial=state();item=next(i for i in decode_item_list(bytes.fromhex(initial[names[0]]['inventory']))[1] if i.template_id==3 and not i.equipped)
        opened(a,b)
        a.send(wire.offer_request(item.instance_id,7));a.until(b'\x89',max_packets=1024);b.until(b'\x8a',max_packets=1024)
        b.send(wire.offer_request(wire.CREDITS_ID,120));b.until(b'\x89',max_packets=1024);a.until(b'\x8a',max_packets=1024)
        # An unrelated real account cannot mutate either party's draft.
        ask(c,wire.offer_request(item.instance_id,1),b'\xf0');case.ping(c)
        ask(a,wire.confirm_request(),b'\x22');case.ping(a);assert state()==initial
        b.send(wire.confirm_request());a.until(b'\x8c',max_packets=1024);b.until(b'\x8c',max_packets=1024)
        after=state();assert after[names[0]]['wallet'][0]==initial[names[0]]['wallet'][0]+120
        assert after[names[1]]['wallet'][0]==initial[names[1]]['wallet'][0]-120
        assert after[names[2]]==initial[names[2]]
        assert sum(i.count for i in decode_item_list(bytes.fromhex(after[names[1]]['inventory']))[1] if i.template_id==3)==7
        b.send(wire.confirm_request());case.ping(b);assert state()==after
        b.sock.close();time.sleep(1)
        again=tls.handoff(tls.begin(names[1],32005,password=passwords[1],language='english'));case.enter(again,names[1]);b=again
        assert state()==after
        time.sleep(2.6);opened(a,b)
        a.send(wire.offer_request(wire.CREDITS_ID,40));a.until(b'\x89',max_packets=1024);b.until(b'\x8a',max_packets=1024)
        a.send(wire.confirm_request());case.ping(a);b.sock.close();a.until(b'\x8c',max_packets=1024)
        assert state()==after
        report.update(passed=True,checks=['same-town invitation only to recipient','ordinary selected-soldier barter opens on both accounts',
            'two-way item and credit transfer is atomic','no writes after first confirmation','third account cannot change offer',
            'duplicate final confirmation is inert','reconnect retains transferred inventory and money','disconnect after first confirmation cancels without debit'],
            ranking_excluded=True,tls_certificate_validated=True,real_graphical_acceptance=False)
    finally:
        for connection in case.clients:
            try:connection.close()
            except OSError:pass
        if created:
            time.sleep(1)
            # Remove only this run's immutable QA receipts, preserving the
            # trigger in one transaction. All ordinary receipts are untouched.
            from tools.player_trade_qa_cleanup import RECEIPT_CLEANUP
            report['receipt_cleanup']=remote(RECEIPT_CLEANUP,names)
            cleanup=CLEANUP.replace('assert len(names)==2','assert len(names)==3').replace("assert not db.execute('SELECT 1 FROM accounts WHERE login IN (?,?)',names).fetchone()","assert not db.execute('SELECT 1 FROM accounts WHERE login IN (?,?,?)',names).fetchone()").replace("assert not db.execute('SELECT 1 FROM characters WHERE account IN (?,?)',names).fetchone()","assert not db.execute('SELECT 1 FROM characters WHERE account IN (?,?,?)',names).fetchone()")
            report['cleanup']=remote(cleanup,names)
        (REPORT/'hosted-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
if __name__=='__main__':run()
