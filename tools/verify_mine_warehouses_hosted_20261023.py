"""Two excluded disposable accounts use native warehouse packets over public TLS."""
import argparse
import json
from pathlib import Path
import secrets
import select
import socket
import ssl
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
saved=list(sys.path)
from tools.verify_game_operations_hosted import CREATE,CLEANUP,remote
sys.path[:]=saved
from tools.clan_icons_hosted_20261018 import Clients
sys.path[:]=saved
from tools.verify_launcher_required_hosted_20261020 import identity
sys.path[:]=saved
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.protocol.warehouse_capacity import OPT_IN,decode as decode_capacity
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.item_list import decode_item_list

OUT=ROOT/'reports/mine-warehouses-20261023'
PRIVATE=ROOT/'.secrets/mine-warehouses-20261023.json'

PREPARE=r'''
import json,sqlite3
from pathlib import Path
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.locations import LocationStore,center
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.warehouse import WarehouseStore
from tio.wallets import WalletStore
from tio.level_progression import FLOORS
path='/var/lib/tio-server/reservation.sqlite3'
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4,'0x8c4b05':FLOORS[3],'0x8c4a07':115,'0x8c4ab1':115}))
for index,name in enumerate(request):
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:
  assert excluded(db,name) and not db.execute('SELECT 1 FROM owned_pets WHERE account=?',(name,)).fetchone()
 def item(i,t,n=1,d=1):return ItemRecord(i,t,bytes(2),n,0,0,(d,d,d),bytes(4),None,bytes(3))
 OwnedPetStore(path).ensure(name,raw,encode_item_list(1,(item(100,30,10+index),item(200,17,d=328),item(300,301,d=300))),human=True)
 SquadStore(path).assign(name,1,1);LocationStore(path);WarehouseStore(path);WalletStore(path).ensure(name)
 with sqlite3.connect(path) as db:LocationStore._save(db,name,13,*center(13))
print(json.dumps(dict(owned_fixtures_only=True,ranking_excluded=True)))
'''

MOVE=r'''
import sqlite3,json
from tio.rating_visibility import QA_LOGIN,excluded
from tio.locations import LocationStore,center,MINE_LOCATIONS
assert request['town'] in (*MINE_LOCATIONS,3)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for name in request['names']:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(name,)).fetchone()
  assert not db.execute('SELECT 1 FROM map_journeys WHERE account=?',(name,)).fetchone()
  LocationStore._save(db,name,request['town'],*center(request['town']))
print(json.dumps(dict(town=request['town'],only_owned_fixtures=True)))
'''


class Network(Clients):
    def __init__(self,data):
        super().__init__(data)
        proof=identity()
        context=ssl.create_default_context()
        def connect(kind,*,preface=None,**kwargs):
            raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
            channel=context.wrap_socket(raw,server_hostname='ti-reborn.com')
            self.case.clients.append(channel)
            port=int.from_bytes(preface[6:8],'big') if preface else 37001
            flags=preface[5] if preface else 0
            channel.sendall(struct.pack('!4sBBH',b'TIOT',2,flags,port)+proof)
            return channel
        self.tls.connect=connect

    def request(self,i,packet,*,reject=False):
        peer=self.peers[i]
        # Discard earlier passive snapshots before issuing a new fenced request.
        while peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],.03)[0]:
            peer.receive()
        peer.send(packet);peer.send(b'\x70')
        rows=[]
        fence=False
        def complete():
            if reject:return any(p[:5]==b'\xf0\x8a\x01\0\0' for p in rows)
            if packet[:1]==b'\x69':
                return (any(p[:3]==b'\xfa\1\1' and decode_capacity(p).kind==packet[1] for p in rows)
                        and any(p[:1]==b'\x6a' and decode_warehouse_list(p)[0]==packet[1] for p in rows))
            if packet[:1]==b'\x6b':
                bags=[n for n,p in enumerate(rows) if p[:1]==b'\x30']
                return bool(bags) and any(n>bags[-1] and p[:2]==b'\xc8\x39' for n,p in enumerate(rows))
            if packet[:1]==b'\x2f':return any(p[:1]==b'\x30' for p in rows)
            if packet[:1]==b'\x52':return any(p[:1]==b'\x5e' for p in rows)
            return True
        for _ in range(4096):
            p=peer.receive();rows.append(p)
            if p==b'\x9e':fence=True
            if fence and complete():break
        else:raise AssertionError('Missing ping fence')
        errors=[p for p in rows if p[:5]==b'\xf0\x8a\x01\0\0']
        with (OUT/'wire-events.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps(dict(account_index=i,request=packet.hex(),packets=[p.hex() for p in rows if p[:1] in (b'\xfa',b'\x6a') or p[:2]==b'\xc8\x39']))+'\n')
        assert bool(errors)==reject, [('opcode',p[:5].hex()) for p in errors]
        return rows


def view(net,i,town,kind=0):
    rows=net.request(i,bytes((0x69,kind)))
    snapshots=[decode_capacity(p) for p in rows if p[:3]==b'\xfa\1\1' and decode_capacity(p).kind==kind]
    assert snapshots and snapshots[-1].town==town, (town,snapshots,[p[:16].hex() for p in rows])
    # Passive refreshes can repeat a complete one-segment list before the ping
    # fence. The native client replaces the old snapshot, rather than appends.
    lists=[decode_warehouse_list(p) for p in rows if p[:1]==b'\x6a' and decode_warehouse_list(p)[0]==kind]
    assert lists and lists[-1][1:3]==(1,0)
    entries=list(lists[-1][3])
    assert snapshots[-1].used==len(entries) and snapshots[-1].capacity==32, (snapshots[-1],[(e.instance_id,e.template_id,e.count) for e in entries])
    return entries


def transfer(net,i,*,first=(),second=(),reject=False,kind=0):
    return net.request(i,encode_warehouse_transfer(WarehouseTransfer(kind,1,first,second)),reject=reject)


def shared_clan_checks(data,report):
    net=Network(data)
    try:
        for i in (0,1):net.connect(i)
        rows=net.request(0,b'\x52'+('QM '+data['names'][0]).encode()+b'\0')
        data['clan']=struct.unpack_from('<I',next(p for p in rows if p[:1]==b'\x5e'),1)[0]
        PRIVATE.write_text(json.dumps(data))
        net.request(0,b'\x5b'+data['names'][1].encode()+b'\0')
        net.request(1,b'\x5d\1')
        info=remote(r'''
import sqlite3,json
from tio.rating_visibility import excluded,QA_LOGIN
from tio.clan_ratings import clans
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert all(QA_LOGIN.fullmatch(n) and excluded(db,n) for n in request['names'])
 assert db.execute('SELECT leader FROM clans WHERE id=?',(request['clan'],)).fetchone()==(request['names'][0],)
 assert request['clan'] not in [r['id'] for r in clans(db)]
 member=db.execute('SELECT id FROM clan_members WHERE account=? AND clan_id=?',(request['names'][1],request['clan'])).fetchone()[0]
 print(json.dumps({'ranking_excluded':True,'member':member}))
''',dict(names=data['names'],clan=data['clan']))
    finally:net.close()
    time.sleep(.5)
    for town in (13,14,15,16):
        remote(MOVE,dict(names=data['names'],town=town))
        net=Network(data)
        try:
            for i in (0,1):net.connect(i);net.request(i,OPT_IN)
            # Default member rights permit reading, not withdrawing.
            net.request(0,b'\x98'+struct.pack('<IIB',info['member'],8|32768,0))
            rows=net.request(0,b'\x2f\x01\0\x01\0\0\0')
            bag=decode_item_list([p for p in rows if p[:1]==b'\x30'][-1])[1]
            gun=next(i.instance_id for i in bag if i.template_id==301)
            kit=next(i.instance_id for i in bag if i.template_id==30)
            for kind,identity in ((1,gun),(2,kit)):
                transfer(net,0,kind=kind,first=((identity,1),))
                leader=view(net,0,town,kind);member=view(net,1,town,kind)
                assert leader==member and len(member)==1
                key=member[0].instance_id
                transfer(net,1,kind=kind,second=((key,1),),reject=True)
                assert view(net,1,town,kind)==member
                transfer(net,0,kind=kind,second=((key,1),))
                assert view(net,1,town,kind)==[]
            report['mines'][str(town)]['shared_clan_warehouse_safe_and_permissions']=True
        finally:net.close()
        time.sleep(.5)
    report['checks'].append('clan warehouse and safe are authoritative for both accounts in every mine; member permissions enforced')


def provision():
    assert not PRIVATE.exists()
    prefix='qm'+secrets.token_hex(4)
    data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])))
    PRIVATE.write_text(json.dumps(data),encoding='utf-8')
    report=remote(PREPARE,data['names'])
    (OUT/'fixture-provisioning.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


def run():
    data=json.loads(PRIVATE.read_text())
    report=dict(passed=False,public_tls=True,accounts=2,graphical_clients=False,mines={},checks=[])
    deposits={}
    try:
        for town in (13,14,15,16):
            remote(MOVE,dict(names=data['names'],town=town))
            net=Network(data)
            try:
                for i in (0,1):
                    net.connect(i);net.request(i,OPT_IN)
                    assert view(net,i,town)==[]
                deposits[town]=[]
                for i in (0,1):
                    rows=transfer(net,i,first=((100,1+i),))
                    assets=decode_asset_count([p for p in rows if p[:2]==b'\xc8\x39'][-1])
                    assert assets.unknown_u32_09==1+i, (i,assets)
                    entries=view(net,i,town)
                    assert len(entries)==1 and entries[0].template_id==30 and entries[0].count==1+i
                    deposits[town].append(entries[0].instance_id)
                # Same numeric item IDs belong to different accounts; another
                # character's transfer must not change this owner's count.
                assert view(net,0,town)[0].count==1 and view(net,1,town)[0].count==2
                # Full gun move, replay rejection and withdrawal exercise both
                # 6B arrays independently of the split stack kept in this mine.
                transfer(net,0,first=((300,1),))
                transfer(net,0,first=((300,1),),reject=True)
                transfer(net,0,second=((300,1),))
                if town!=13:
                    transfer(net,0,second=((deposits[13][0],1),),reject=True)
                report['mines'][str(town)]=dict(native_69_6b=True,captions=True,resource_counters=True,
                                               private_counts=[1,2],replay_rejected=True)
            finally:net.close()
            time.sleep(.5)
        # Reconnect to every checkpoint and retrieve the saved stack, proving
        # that the server commits location and account scopes, not UI caches.
        for town in (13,14,15,16):
            remote(MOVE,dict(names=data['names'],town=town))
            net=Network(data)
            try:
                for i in (0,1):
                    net.connect(i);net.request(i,OPT_IN)
                    entries=view(net,i,town)
                    assert [(v.instance_id,v.count) for v in entries]==[(deposits[town][i],1+i)]
                    transfer(net,i,second=((deposits[town][i],1+i),))
                    assert view(net,i,town)==[]
                report['mines'][str(town)]['saved_reconnect_and_withdrawal']=True
            finally:net.close()
            time.sleep(.5)
        remote(MOVE,dict(names=data['names'],town=3))
        net=Network(data)
        try:
            for i in (0,1):
                net.connect(i);net.request(i,OPT_IN)
                assert view(net,i,3)==[]
                rows=net.request(i,b'\x2f\x01\0\x01\0\0\0')
                bag=decode_item_list([p for p in rows if p[:1]==b'\x30'][-1])[1]
                assert sum(v.count for v in bag if v.template_id==30)==10+i
                assert sum(v.count for v in bag if v.template_id==301)==1
            report['checks']=['all four checkpoints have independent persistent storage',
                'two simultaneous authenticated accounts remain isolated',
                'native captions and resource counters match saved items',
                'full and partial transfers conserve quantities; replay and remote-mine selection rejected',
                'all items retrieved after reconnect; city warehouse remains separate']
        finally:net.close()
        time.sleep(.5)
        shared_clan_checks(data,report)
        report['passed']=True
    finally:
        (OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


def cleanup():
    data=json.loads(PRIVATE.read_text())
    time.sleep(1)
    code=CLEANUP
    if data.get('clan'):
        code=code.replace("tables=[r[0]", "cid=request['clan'];assert db.execute('SELECT leader FROM clans WHERE id=?',(cid,)).fetchone()==(names[0],)\n assert {r[0] for r in db.execute('SELECT account FROM clan_members WHERE clan_id=?',(cid,))}<=set(names)\n tables=[r[0]")
        old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
        new="\n  if 'clan_id' in columns:parts.append(quote('clan_id')+'=?');args.append(cid)\n  if table=='clans':parts.append('id=?');args.append(cid)\n  condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
        assert old in code
        code=code.replace(old,new)
    result=remote(code,dict(names=data['names'],clan=data.get('clan'),protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2))
    PRIVATE.unlink()
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('provision','run','cleanup'))
    globals()[parser.parse_args().mode]()
