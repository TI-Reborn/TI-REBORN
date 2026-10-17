"""Bounded checks of the actual hosted service, using two fresh QA accounts.

No graphical clients; no production fault injection or player credential use.
"""
from verify_hosted_rewards import reward_run, ROOT
from verify_hosted_player_statistics import profiles
from tio.protocol.item_list import decode_item_list
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import time

FOLDER=ROOT/'reports/stage2-admission-capacity'


def account_state(host,name):
    code='''import sqlite3,json,hashlib,sys
name=json.load(sys.stdin)
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
db.execute('BEGIN')
tables=('wallets','owned_pets','item_sequences','sc_sold','sc_cart','rentals',
        'achievement_counters','achievement_awards','achievement_prizes','achievement_upgrades')
out={}
for table in tables:
 if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():continue
 records=sorted(repr(row) for row in db.execute('SELECT * FROM "'+table+'" WHERE account=?',(name,)))
 out[table]=dict(rows=len(records),sha256=hashlib.sha256(repr(records).encode()).hexdigest())
print(json.dumps(out))'''
    completed=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
        'root@'+host,'python3 -c '+shlex.quote(code)],input=json.dumps(name),
        text=True,capture_output=True,encoding='utf-8',check=True,timeout=30)
    return json.loads(completed.stdout)


def checks(peers,names,summaries,result,case):
    profiles(peers,names,summaries,result,case)
    peer=peers[0];packets=[];previous=peer.receive
    def receive():
        packet=previous();packets.append(packet);return packet
    peer.receive=receive
    def inventory():
        peer.send(b'\x2f'+struct.pack('<HI',1,1))
        value=decode_item_list(peer.until(b'\x30',max_packets=2048))
        assert value[0]==1
        case.ping(peer)
        return value[1]
    def purchase(lot):
        start=len(packets)
        peer.send(b'\xb4\x06'+struct.pack('<III',lot,1,2))
        case.ping(peer)
        chunk=packets[start:]
        assert not any(p[0]==0xf0 for p in chunk),[p.hex() for p in chunk if p[0]==0xf0]
        item=decode_item_list(next(p for p in chunk if p[0]==0x30))[1]
        wallet=decode_asset_count(next(p for p in chunk if p[:2]==b'\xc8\x39'))
        return item,wallet
    initial=inventory()
    assert len(initial)<18
    items,wallet=purchase(100014)
    while len(items)<18:items,wallet=purchase(100314)
    assert len(items)==18
    ammo=next(i for i in items if i.template_id==14)
    full_gold=wallet.gold
    items,wallet=purchase(100014)
    assert len(items)==18 and next(i for i in items if i.instance_id==ammo.instance_id).count==ammo.count+100
    assert wallet.gold==full_gold-25
    result['inventory']=dict(initial_slots=len(initial),full_slots=len(items),ammo_after=ammo.count+100,gold=wallet.gold)
    before=account_state(sys.argv[1],names[0])
    rejected=[]
    for label,request in (
        ('SC 19th item',b'\xb4\x06'+struct.pack('<III',100314,1,2)),
        ('ordinary shop 19th item',encode_shop_purchase(ShopPurchase(1,0,81,1))),
        ('rental 19th item',b'\xb4\x10'+struct.pack('<IHIB',331410,3,1,2)),
    ):
        start=len(packets);peer.send(request);case.ping(peer)
        chunk=packets[start:]
        errors=[p for p in chunk if p[:5]==b'\xf0'+struct.pack('<I',394)]
        assert len(errors)==1,(label,[p.hex() for p in chunk])
        message=errors[0][13:-2].decode('utf-16-le')
        assert 'недостаточно свободных мест' in message,(label,message)
        assert not any(p[0]==0x30 or p[:2]==b'\xc8\x39' for p in chunk),label
        rejected.append(dict(request=label,error=message))
        case.ping(peers[1])
    assert inventory()==items
    after=account_state(sys.argv[1],names[0])
    assert before==after,(before,after)
    result['rejections']=rejected;result['rejection_state_unchanged']=before
    result['checks'].extend(['public SC fills 18 slots; existing ammo stack grows at capacity',
        'public SC, ordinary shop and rental reject 19th item with native UTF16 localized error',
        'rejected purchases preserve saved inventory, wallets, sequence, stock, cart, rentals and achievement state'])
    # Six sequential failures for our own new account: bounded QA, no flood.
    since=(datetime.now(timezone.utc)-timedelta(seconds=2)).strftime('%Y-%m-%d %H:%M:%S UTC')
    for _ in range(6):
        case.begin(names[0],password='qa-invalid-password-for-admission-check',denied=True)
        for online in peers:case.ping(online)
    result['checks'].append('six controlled invalid public login attempts close; both authenticated accounts continue replying')
    result['invalid_attempts']=6
    command=shlex.join(['journalctl','-u','tio-server','--since',since,'--no-pager'])
    log=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
        'root@'+sys.argv[1],command],capture_output=True,text=True,check=True,timeout=30).stdout
    throttled=sum('Session ended: LoginThrottled(' in line or
                  'Login rejected category=throttled ' in line for line in log.splitlines())
    assert throttled>=1,'Hosted journal did not confirm login throttling'
    result['login_journal']=dict(since=since,throttled=throttled,
        authentication_failed=sum("Session ended: ValueError('Authentication failed')" in line or
                                  'Login rejected category=credentials ' in line for line in log.splitlines()))


if __name__=='__main__':
    result=reward_run(sys.argv[1],profile_check=checks)
    result['kind']='public native TCP codec (legacy obfuscation, no TLS); automated protocol, no graphical clients'
    (FOLDER/'hosted-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
