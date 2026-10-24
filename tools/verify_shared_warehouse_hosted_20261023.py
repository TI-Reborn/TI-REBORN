"""Two excluded QA logins exercise native warehouse packets on public TLS.

Fixture-only relocation changes authoritative locations between requests; it
does not claim the native GUI or full map journeys were visually tested.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools import verify_mine_warehouses_hosted_20261023 as qa
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.warehouse_capacity import OPT_IN
from tio.protocol.item_list import decode_item_list

OUT=ROOT/'reports/shared-warehouse-20261023'
qa.OUT=OUT
qa.PRIVATE=ROOT/'.secrets/shared-warehouse-20261023.json'
qa.MOVE=qa.MOVE.replace('assert request[\'town\'] in (*MINE_LOCATIONS,3)',
    'from tio.cities import CITIES\nassert request[\'town\'] in (*CITIES,9,*MINE_LOCATIONS)')

SEED=r'''
from pathlib import Path
import sqlite3,json
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.item_list import ItemRecord,encode_item_list
assert all(QA_LOGIN.fullmatch(n) for n in request)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 assert all(excluded(db,n) for n in request)
 name=request[0]
 for identity,template,resource,town in ((500,301,300,2),(501,17,123,14)):
  item=ItemRecord(identity,template,bytes(2),1,0,0,(resource,600,600) if template==17 else (resource,)*3,bytes(4),None,bytes(3))
  db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',(name,identity,encode_item_list(0,(item,))))
  db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?)',(name,identity,'city',town,'old-town-fixture'))
print(json.dumps(dict(passed=True,fixture_only=True,preexisting_town_tags=[2,14])))
'''

RESET_TRAVEL=r'''
import sqlite3,json
from tio.locations import LocationStore,center
from tio.rating_visibility import QA_LOGIN,excluded
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  db.execute('DELETE FROM map_journeys WHERE account=?',(name,))
  LocationStore._save(db,name,3,*center(3))
print(json.dumps(dict(passed=True,owned_fixture_journeys_only=True)))
'''


def connect(data):
    net=qa.Network(data)
    try:
        for i in (0,1):
            net.connect(i)
            net.request(i,OPT_IN)
        return net
    except BaseException:
        net.close()
        raise


def run():
    data=json.loads(qa.PRIVATE.read_text(encoding='utf-8'))
    report=dict(passed=False,public_tls=True,simultaneous_accounts=2,graphical_clients=False,
                fixture_relocations=True,locations={},checks=[])
    net=None
    try:
        net=connect(data)
        initial=[qa.view(net,i,13) for i in (0,1)]
        assert {i.instance_id for i in initial[0]} in ({500,501},{100,500,501})
        assert {i.instance_id for i in initial[1]} in (set(),{100})
        for i,count in ((0,10),(1,11)):
            rows=qa.transfer(net,i,first=((100,count),)) if not any(e.instance_id==100 for e in initial[i]) else net.request(i,b'\xb8\x11')
            assets=decode_asset_count([p for p in rows if p[:2]==b'\xc8\x39'][-1])
            assert assets.unknown_u32_09==count
        qa.transfer(net,0,first=((300,1),))
        qa.transfer(net,0,first=((300,1),),reject=True)
        qa.transfer(net,1,second=((500,1),),reject=True)
        for town in (13,14,15,16,3,2,4,5,8,9,18):
            qa.remote(qa.MOVE,dict(names=data['names'],town=town))
            for i in (0,1):
                entries=qa.view(net,i,town)
                assert {e.instance_id for e in entries}==({100,300,500,501} if i==0 else {100})
                assert sum(e.count for e in entries if e.template_id==30)==10+i
                assets=net.request(i,b'\xb8\x11')
                value=decode_asset_count([p for p in assets if p[:2]==b'\xc8\x39'][-1])
                assert (value.unknown_u32_09,value.unknown_u32_08)==(10+i,123 if i==0 else 0)
            report['locations'][str(town)]=dict(shared_saved_items=True,capacity=32,private_accounts=True,counters_match=True)
            print(json.dumps(dict(checked_town=town)),flush=True)
        # An item deposited/tagged in Denver can be retrieved in Detroit.
        qa.transfer(net,0,second=((500,1),))
        qa.remote(qa.MOVE,dict(names=data['names'],town=13))
        qa.transfer(net,0,second=((500,1),),reject=True)
        rows=qa.transfer(net,0,second=((100,4),))
        bag=decode_item_list([p for p in rows if p[:1]==b'\x30'][-1])[1]
        split=next(i.instance_id for i in bag if i.template_id==30)
        assert split!=100
        qa.transfer(net,0,first=((split,4),))
        # A real 1B travel request must immediately revoke warehouse mutations.
        net.request(0,b'\x1b'+struct.pack('<ii',190,-20))
        net.request(0,b'\x69\0',reject=True)
        qa.transfer(net,0,second=((100,1),),reject=True)
        net.close();net=None
        time.sleep(.5)
        qa.remote(RESET_TRAVEL,data['names'])
        net=connect(data)
        for i in (0,1):
            entries=qa.view(net,i,3)
            qa.transfer(net,i,second=tuple((e.instance_id,e.count) for e in entries))
            assert qa.view(net,i,3)==[]
            rows=net.request(i,b'\x2f\x01\0\x01\0\0\0')
            bag=decode_item_list([p for p in rows if p[:1]==b'\x30'][-1])[1]
            assert sum(e.count for e in bag if e.template_id==30)==10+i
            assert sum(e.count for e in bag if e.template_id==301)==(2 if i==0 else 1)
            assert sum(e.count*e.unknown_words[0] for e in bag if e.template_id==17)==(451 if i==0 else 328)
        report['checks']=['same personal stock in all 11 eligible locations',
            'old city/mine tags are accessible without migration',
            'two simultaneous real accounts remain private',
            'native 69/6B lists, FA capacities and C8/39 counters agree',
            'full/partial transfers conserve quantities, identities and durability',
            'repeated transfers and foreign item selections rejected',
            'actual map travel revokes access',
            'reconnect in another city retains all items; complete retrieval verified']
        report['passed']=True
    finally:
        if net is not None:net.close()
        (OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('provision','run','cleanup'))
    mode=parser.parse_args().mode
    if mode=='provision':
        qa.provision()
        result=qa.remote(SEED,json.loads(qa.PRIVATE.read_text())['names'])
        (OUT/'fixture-seed.json').write_text(json.dumps(result,indent=2))
    elif mode=='cleanup':qa.cleanup()
    else:run()
