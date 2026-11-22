"""Post-install acceptance with three excluded accounts over production TLS.

Uses purchased ammunition, normal barter/AE/C8 requests and original receipts.
Never bids on an ordinary player's lot or a shared SC lot. No GUI acceptance.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,secrets,socket,ssl,struct,sys,time

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'work/bank-trade-release-20261015/candidate'
sys.path[:0]=[str(CANDIDATE),str(ROOT/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from test_player_auction import create_packet
from tio.protocol import player_trade as wire
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.binary import Writer
from tio.protocol.private_shops import put_price
from tio.protocol.item_list import decode_item_list
from tio.rating_visibility import QA_LOGIN
from tools.verify_game_operations_hosted import remote,CREATE
sys.path[:0]=[str(CANDIDATE),str(ROOT/'tests'),str(ROOT)]
REPORT=ROOT/'reports/trade-operations-20261015'

INSTALLED=r'''
from pathlib import Path
import json,hashlib
assert all(hashlib.sha256((Path('/opt/tio-emulator')/p).read_bytes()).hexdigest()==r['after'] for p,r in request.items()),'Trade candidate is not installed'
print(json.dumps(dict(installed_files_verified=len(request))))
'''

STATE=r'''
from tio.rating_visibility import QA_LOGIN,excluded
import sqlite3,json
assert len(request)==3 and all(QA_LOGIN.fullmatch(n) for n in request)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows={}
 for n in request:
  rows[n]=dict(wallet=list(db.execute('SELECT credits,gold FROM wallets WHERE account=?',(n,)).fetchone()),
   inventory=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0].hex(),
   warehouse=[bytes(r[0]).hex() for r in db.execute('SELECT item_packet FROM warehouse_items WHERE account=? ORDER BY instance_id',(n,))],
   shop=db.execute('SELECT id FROM private_shops WHERE account=?',(n,)).fetchone()[0]+0x40000000,excluded=excluded(db,n))
 print(json.dumps(rows))
'''

CLEANUP=r'''
import sqlite3,json,hashlib
from tio.rating_visibility import QA_LOGIN
names=request;assert len(names)==3 and len(set(names))==3 and all(QA_LOGIN.fullmatch(n) for n in names)
owners=names+['@character:'+n+':'+str(s) for n in names for s in range(2,6)]
def quote(s):return '"'+s.replace('"','""')+'"'
def hashed(rows):return hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest()
db=sqlite3.connect('/var/lib/tio-server/reservation.sqlite3',timeout=15);db.execute('BEGIN IMMEDIATE')
try:
 shops=[r[0] for r in db.execute('SELECT id FROM private_shops WHERE account IN (?,?,?)',names)]
 lots=[r[0] for r in db.execute('SELECT id FROM player_auction_lots WHERE seller IN (?,?,?)',names)]
 # Preserve real-player purchases/bids if someone interacted with a QA listing.
 for lot in lots:
  bidder=db.execute('SELECT bidder FROM player_auction_lots WHERE id=?',(lot,)).fetchone()[0]
  assert bidder is None or bidder in names,'Non-QA auction participant; preserve their transaction'
  assert all(a in names for a, in db.execute('SELECT account FROM player_auction_history WHERE lot=?',(lot,)))
 trades=[]
 for ident,raw in db.execute('SELECT id,parties FROM player_trade_receipts'):
  parties=json.loads(raw)
  if len(parties)==2 and {a for a,p in parties}<=set(names):trades.append(ident)
 tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
 schema=list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
 foreign=list(db.execute('PRAGMA foreign_key_check'));rules={};before={};triggers=[];deleted={}
 for table in tables:
  columns=[r[1] for r in db.execute('PRAGMA table_info('+quote(table)+')')];parts=[];args=[]
  for column in ('account','owner','login','username','seller','bidder'):
   if column in columns:parts.append(quote(column)+' IN ('+','.join('?' for _ in owners)+')');args+=owners
  for field,values in ([('shop',shops)] if table in ('private_shop_sales','private_shop_orders') else
                       [('lot',lots)] if table in ('player_auction_items','player_auction_history') else
                       [('id',trades)] if table=='player_trade_receipts' else []):
   if values:parts.append(quote(field)+' IN ('+','.join('?' for _ in values)+')');args+=values
  condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)
  before[table]=hashed(db.execute('SELECT * FROM '+quote(table)+' WHERE NOT COALESCE(('+condition+'),0)',args).fetchall())
  if db.execute('SELECT 1 FROM '+quote(table)+' WHERE '+condition+' LIMIT 1',args).fetchone():
   triggers+=list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=? AND upper(sql) LIKE '%BEFORE DELETE%'",(table,)))
 for name,sql in triggers:db.execute('DROP TRIGGER '+quote(name))
 for table in sorted(tables,key=lambda t:t in ('accounts','player_auction_lots','private_shops')):
  condition,args=rules[table];count=db.execute('DELETE FROM '+quote(table)+' WHERE '+condition,args).rowcount
  if count:deleted[table]=count
 for name,sql in triggers:db.execute(sql)
 assert schema==list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
 for table in tables:
  condition,args=rules[table]
  assert not db.execute('SELECT 1 FROM '+quote(table)+' WHERE '+condition+' LIMIT 1',args).fetchone()
  assert before[table]==hashed(db.execute('SELECT * FROM '+quote(table)+' WHERE NOT COALESCE(('+condition+'),0)',args).fetchall()),'Unrelated rows changed'
 assert foreign==list(db.execute('PRAGMA foreign_key_check'))
 assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
 db.commit();print(json.dumps(dict(deleted=deleted,unrelated_rows_preserved=True,schema_restored=True,integrity='ok')))
except BaseException:db.rollback();raise
finally:db.close()
'''


def run():
    installed=remote(INSTALLED,json.loads((REPORT/'patch-manifest.json').read_text()))
    prefix='qm'+secrets.token_hex(4);names=[prefix+s for s in 'abc'];passwords=[secrets.token_urlsafe(24) for n in names]
    assert all(QA_LOGIN.fullmatch(n) for n in names)
    report=dict(passed=False,kind='three production TLS protocol clients; GUI not tested',installed=installed,fixtures=names,checks=[])
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case;context=ssl.create_default_context()
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def barrier(peer,packet=None):
        if packet is not None:peer.send(packet)
        peer.send(b'\xb1\x02');result=[]
        for _ in range(2048):
            reply=peer.receive()
            if reply.startswith(b'\xb1\x03'):return result
            result.append(reply)
        raise AssertionError('Missing city barrier')
    def state():return remote(STATE,names)
    def warehouse(row):return [i for raw in row['warehouse'] for i in decode_item_list(bytes.fromhex(raw))[1]]
    provision=None
    try:
        provision=remote(CREATE,list(zip(names,passwords)));report['ranking_excluded']=provision['ranking_excluded']
        peers=[]
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,35001+i,password=password));case.enter(peer,name)
            barrier(peer,struct.pack('<Bii',0x1b,-154,-318));peers.append(peer)
        a,b,c=peers
        assert all(r['excluded'] and r['wallet']==[3000,0] for r in state().values())
        barrier(a,encode_shop_purchase(ShopPurchase(1,0,3,1)))
        remote("from tio.achievements import AchievementStore; import json; AchievementStore('/var/lib/tio-server/reservation.sqlite3').flush(request[0]); print(json.dumps({'flushed':True}))",names)
        before=state();ammo=next(i for i in decode_item_list(bytes.fromhex(before[names[0]]['inventory']))[1] if i.template_id==3 and not i.equipped)
        a.send(wire.invite_request(names[1].encode(),1));b.until(b'\x85',max_packets=1024)
        b.send(wire.answer_request(True,1));a.until(b'\x87',max_packets=1024);b.until(b'\x87',max_packets=1024)
        a.send(wire.offer_request(ammo.instance_id,7));a.until(b'\x89',max_packets=1024);b.until(b'\x8a',max_packets=1024)
        b.send(wire.offer_request(wire.CREDITS_ID,120));b.until(b'\x89',max_packets=1024);a.until(b'\x8a',max_packets=1024)
        barrier(c,wire.offer_request(ammo.instance_id,1));assert state()==before
        a.send(wire.confirm_request())
        for _ in range(1024):
            reply=a.receive()
            if reply[:1]==b'\x22' and 'ожидается подтверждение второго' in reply[reply.index(b'\0',6)+1:-2].decode('utf-16-le'):break
        else:raise AssertionError('Missing first confirmation')
        assert state()==before
        b.send(wire.confirm_request());a.until(b'\x8c',max_packets=1024);b.until(b'\x8c',max_packets=1024)
        barrier(a);barrier(b);after=state()
        assert after[names[0]]['wallet'][0]==before[names[0]]['wallet'][0]+120
        assert after[names[1]]['wallet'][0]==before[names[1]]['wallet'][0]-120 and after[names[2]]==before[names[2]]
        barrier(b,wire.confirm_request());assert state()==after
        report['checks'].append('barter waits for both confirmations, rejects third party, commits two wallets/items and ignores duplicate completion')
        sales=Writer().u8(0xae).u8(8).u8(0).u32(1).u32(ammo.instance_id).u32(10);put_price(sales,100)
        barrier(a,sales.build());identity=state()[names[0]]['shop']
        barrier(b,Writer().u8(0xae).u8(3).u32(identity).build())
        buy=Writer().u8(0xae).u8(6).u32(identity).u32(1).u32(1).u32(3).build();before=state()
        barrier(b,buy);after=state()
        assert after[names[0]]['wallet'][0]==before[names[0]]['wallet'][0]+3
        assert after[names[1]]['wallet'][0]==before[names[1]]['wallet'][0]-3
        barrier(b,buy);assert state()==after
        barrier(a,b'\xae\x08\0'+bytes(4)) # Return unsold escrow through normal cancel.
        report['checks'].append('AE private sale transfers partial stack and credits once; stale packet rejected; unsold items returned')
        before=state();item=next(i for i in warehouse(before[names[1]]) if i.template_id==3)
        create=create_packet(request=71,instance=item.instance_id,count=2,price=100,step=10,buyout=200)
        replies=barrier(b,create);added=next(p for p in replies if p.startswith(b'\xc8\x03'));lot=int.from_bytes(added[6:10],'little')
        created=state();barrier(b,create);assert state()==created
        barrier(c,Writer().u8(0xc8).u8(13).u32(lot).u32(100).u32(0).build())
        replies=barrier(b,Writer().u8(0xc8).u8(15).u32(lot).build())
        assert any(p.startswith(b'\xf0\x8a\x01\0\0') for p in replies)
        packet=Writer().u8(0xc8).u8(14).u32(lot).build()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda peer:barrier(peer,packet),(a,c)))
        assert sum(any(p.startswith(b'\xc8\x04') for p in replies) for replies in results)==1
        after=state();assert sum(r['wallet'][0] for r in after.values())==sum(r['wallet'][0] for r in before.values())
        assert sum(i.count for who in (names[0],names[2]) for i in warehouse(after[who]) if i.template_id==3)==2
        duplicate=after;barrier(a,packet);assert state()==duplicate
        report['checks'].append('C8 duplicate create keeps one pledge/escrow; bid blocks cancellation; competing buyouts deliver to one buyer and conserve total funds')
        for peer in peers:barrier(peer)
        for peer in peers:peer.sock.close()
        time.sleep(1)
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,35101+i,password=password));case.enter(peer,name);barrier(peer)
        assert state()==after
        report['checks'].append('all three accounts reconnect with persistent wallets and inventories')
        report['sc_mutations_hosted_verified']=False
        report['sc_note']='SC fees, bots, winner claim and replay tested automatically with isolated accounts; public shared lots are not touched by this hosted QA'
        report['passed']=True
    finally:
        for connection in case.clients:
            try:connection.close()
            except OSError:pass
        time.sleep(1)
        try:
            if provision:report['cleanup']=remote(CLEANUP,names)
        except BaseException:report['passed']=False;report['cleanup_failed']=True;raise
        finally:(REPORT/'hosted-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':run()
