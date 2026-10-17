"""Three fresh accounts on public encrypted TCP; no graphical-client claim.

Only these QA commanders receive a level4 fixture. Existing data is backed up
on the host before provisioning and compared afterward. Credentials are sent
through SSH stdin and never recorded in the report.
"""
from verify_hosted_character_onboarding import *
from contextlib import closing
import socket,subprocess,shlex,struct
from tio.protocol.binary import Reader
from tio.protocol.clans import string
from tio.protocol.item_list import decode_item_list
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.clans import DEFAULT_RIGHTS,WITHDRAW_WAREHOUSE,WITHDRAW_CREDITS


def run(host):
    prefix='qc'+secrets.token_hex(4);names=[prefix+x for x in 'abc'];passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,passed=False,checks=[],kind='Three real authenticated accounts over public encrypted TCP; no graphical clients',
        fixture='Only new QA commanders: level4; own QA clan: influence5000 and leader credits20000 for native upgrade test')
    folder=ROOT/'reports/clans';folder.mkdir(parents=True,exist_ok=True);output=folder/f'hosted-{prefix}.json'
    def remote(code,payload=names):
        p=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,encoding='utf-8')
        if p.returncode:raise RuntimeError(p.stderr)
        return p.stdout
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        s=socket.create_connection((host,port),timeout=12);case.clients.append(s);return s
    case.connect=connect;peers=[];received=[[],[],[]]
    def enter():
        peers.clear()
        for i,(n,p) in enumerate(zip(names,passwords)):
            peer=case.handoff(case.begin(n,p));original=peer.receive
            def receive(i=i,original=original):
                packet=original();received[i].append(packet);return packet
            peer.receive=receive;peers.append(peer);case.enter(peer,n)
    def close():
        for s in case.clients:s.close()
        case.clients=[]
    def settle():
        time.sleep(.6)
        for peer in peers:case.ping(peer)
    def command(i,packet):
        received[i].clear();peers[i].send(packet);case.ping(peers[i]);return received[i]
    def last(i,header,kind=None):
        packets=[p for p in received[i] if p.startswith(header) and (kind is None or decode_warehouse_list(p)[0]==kind)]
        assert packets,(i,header.hex(),[p[:5].hex() for p in received[i]])
        return packets[-1]
    def info(i):
        r=Reader(last(i,b'\x54')[1:]);cid=r.u32();name=string(r);leader=string(r)
        return cid,name,leader
    def member_id(i,name):
        r=Reader(last(i,b'\x55')[1:])
        for _ in range(r.u8()):
            mid=r.u32();n=string(r);r.read(3);r.read(13)
            if n==name.encode():return mid
        raise AssertionError('Member missing')
    def inventory(i):return decode_item_list(last(i,b'\x30'))[1]
    def assets(i):
        command(i,b'\xb8\x11');return decode_asset_count(last(i,b'\xc8\x39'))
    def exchange(i,kind,first=(),second=()):
        return command(i,encode_warehouse_transfer(WarehouseTransfer(kind,1,first,second)))
    backup=None
    try:
        backup=remote('''
import json,sys,sqlite3,tempfile,pathlib
from server.accounts import Accounts
pairs=json.load(sys.stdin);names=[n for n,p in pairs]
assert len(names)==3 and all(n.startswith('qc') and len(n)==11 for n in names)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-clans-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in pairs:a.create(n,p,character=n)
print(folder)
''',list(zip(names,passwords))).strip()
        report['backup']=backup
        enter();close();time.sleep(1)
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
names=json.load(sys.stdin)
assert len(names)==3 and all(n.startswith('qc') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n in names:
  raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]
  pet=decode_pet_info(raw,human_equipment=True)
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4})),n))
''')
        enter()
        clan_name=prefix.encode()
        command(0,b'\x52'+clan_name+b'\0');cid,actual,leader=info(0)
        assert cid and actual==clan_name and leader==names[0].encode()
        command(0,b'\x5b'+names[1].encode()+b'\0');settle()
        assert any(p.startswith(b'\x5c') for p in received[1])
        command(1,b'\x5d\1');settle();bid=member_id(0,names[1])
        report['checks'].append('Native creation, invitation and acceptance; one clan shared by two accounts')
        remote('''
import json,sys,sqlite3
data=json.load(sys.stdin);owner=data['owner'];cid=data['clan']
assert owner.startswith('qc') and len(owner)==11
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 assert db.execute('SELECT leader FROM clans WHERE id=?',(cid,)).fetchone()==(owner,)
 db.execute('UPDATE clans SET influence=5000 WHERE id=?',(cid,))
 db.execute('UPDATE wallets SET credits=20000 WHERE account=?',(owner,))
''',dict(owner=names[0],clan=cid))
        command(0,b'\x31\1');settle()
        assert last(0,b'\x54')[1+4+len(clan_name)+1+len(names[0])+1]==1
        assert assets(0).credits==5000
        report['checks'].append('Native31/1 upgrades QA clan to level1; credits20000→5000 and influence5000→0')
        # Buy an unequipped item with the original city shop, then give it to
        # the shared warehouse. No inventory fixture or direct DB transfer.
        command(1,b'\x73\0');offers=decode_item_shop(last(1,b'\x74'))[1]
        offer=next(o for o in offers if o.item_id==301)
        command(1,encode_shop_purchase(ShopPurchase(1,0,offer.unknown_u32_01,1)))
        item=next(i for i in inventory(1) if i.template_id==301 and not i.equipped and not i.slot)
        exchange(1,1,((item.instance_id,1),));shared=decode_warehouse_list(last(1,b'\x6a',1))[3]
        key=shared[0].instance_id;assert key!=item.instance_id
        exchange(1,1,second=((key,1),));assert any(p.startswith(b'\xf0') for p in received[1])
        exchange(0,1,second=((key,1),));assert not decode_warehouse_list(last(0,b'\x6a',1))[3]
        assert any(i.template_id==301 for i in inventory(0))
        report['checks'].append('Shared item from account B withdrawn by leader A; unauthorized B withdrawal rejected; IDs remapped')
        before=assets(1)
        exchange(1,2,((0xffff0001,100),(0xffff0002,50)))
        after=decode_asset_count(last(1,b'\xc8\x39'))
        assert (after.credits,after.gold)==(before.credits-100,before.gold-50)
        assert (after.unknown_u32_08,after.unknown_u32_09)==(100,50)
        assert (assets(0).unknown_u32_08,assets(0).unknown_u32_09)==(100,50)
        exchange(1,2,second=((0xffff0001,1),));assert any(p.startswith(b'\xf0') for p in received[1])
        assert (assets(2).unknown_u32_08,assets(2).unknown_u32_09)==(0,0)
        command(2,b'\x69\2');assert not decode_warehouse_list(last(2,b'\x6a',2))[3]
        assert any(p.startswith(b'\xf0') for p in received[2])
        report['checks'].append('Credits and gold conserved across wallet and treasury; separate withdrawal rights; outsider sees no funds/items')
        received[1].clear();received[2].clear()
        command(0,b'\x21\2'+'clan test'.encode('utf-16-le')+b'\0\0');settle()
        assert any(p.startswith(b'\x22') and p[5]==2 for p in received[1])
        assert not any(p.startswith(b'\x22') and p[5]==2 for p in received[2])
        close();time.sleep(1);received[:]=[[],[],[]];enter();settle()
        assert info(0)[0]==cid and info(1)[0]==cid and info(2)[0]==0
        assert (assets(0).unknown_u32_08,assets(0).unknown_u32_09)==(100,50)
        command(0,b'\x68\0'+names[1].encode()+b'\0')
        r=Reader(last(0,b'\xa7\0')[2:]);r.u32();string(r);r.u8();r.u32()
        assert (string(r),r.u32())==(clan_name,cid)
        report['checks'].append('Clan, funds and permissions survive reconnection; public profile shows clan; clan chat excludes third account')
        # Revoke viewing rights, then grant only the necessary withdrawal bit.
        command(0,b'\x98'+struct.pack('<IIB',bid,8,2));settle()
        assert assets(1).unknown_u32_08==0
        exchange(1,2,second=((0xffff0001,20),));assert any(p.startswith(b'\xf0') for p in received[1])
        rights=DEFAULT_RIGHTS|WITHDRAW_WAREHOUSE|WITHDRAW_CREDITS
        command(0,b'\x98'+struct.pack('<IIB',bid,rights,2));settle()
        exchange(1,2,second=((0xffff0001,20),));assert decode_asset_count(last(1,b'\xc8\x39')).unknown_u32_08==80
        exchange(0,2,second=((0xffff0001,80),(0xffff0002,50)))
        command(0,b'\x99'+names[1].encode()+b'\0');settle()
        command(0,b'\x98'+struct.pack('<IIB',bid,rights,2));assert any(p.startswith(b'\xf0') for p in received[0])
        command(1,b'\x5f'+names[0].encode()+b'\0');settle()
        command(0,b'\x69\1');assert any(p.startswith(b'\xf0') for p in received[0])
        command(1,b'\x53'+struct.pack('<I',cid));assert info(1)[0]==0
        report['checks'].append('Revocation takes effect on next operation; leader transfer removes old leader authority; kick revokes access; empty QA clan dissolved')
        close();time.sleep(1)
        report['storage']=json.loads(remote('''
import json,sys,sqlite3,pathlib
data=json.load(sys.stdin);backup=pathlib.Path(data['backup'])
assert backup.parent==pathlib.Path('/root') and backup.name.startswith('tio-before-clans-qa-')
with sqlite3.connect(backup/'reservation.sqlite3') as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'")]
 preserved=0
 for name in tables:
  escaped='"'+name.replace('"','""')+'"'
  before={repr(r) for r in old.execute('SELECT * FROM '+escaped)}
  after={repr(r) for r in db.execute('SELECT * FROM '+escaped)}
  assert before<=after,'Existing records changed: '+name
  preserved+=len(before)
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not db.execute('SELECT 1 FROM clan_members WHERE account IN (?,?,?)',data['names']).fetchone()
 assert not db.execute('SELECT 1 FROM clan_items').fetchone()
 print(json.dumps(dict(integrity='ok',existing_tables=len(tables),existing_rows_preserved=preserved,
  qa_operations=db.execute('SELECT count(*) FROM clan_ledger WHERE account IN (?,?,?)',data['names']).fetchone()[0])))
''',dict(names=names,backup=backup)))
        report['passed']=True
    except BaseException as exc:
        report['error']=repr(exc);raise
    finally:
        close();output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(report=str(output),passed=report['passed']),ensure_ascii=False))


if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else '185.184.42.88')
