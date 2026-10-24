"""Two disposable excluded accounts exercise stock repair over public game TLS."""
import json,secrets,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
saved=list(sys.path)
from tools import verify_warehouse_counters_hosted_20261018 as v
sys.path[:]=saved
OUT=ROOT/'reports/repair-from-warehouse-20261020'
PRIVATE=ROOT/'.secrets/repair-from-warehouse-20261020.json'

def provision():
    assert not PRIVATE.exists()
    prefix='qt'+secrets.token_hex(4)
    data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision']=v.remote(v.CREATE,list(zip(data['names'],data['passwords'])))
    PRIVATE.write_text(json.dumps(data),encoding='utf-8')
    prepare=v.PREPARE.replace("item(9001,301,current=50,maximum=350,equip=1),",
        "item(9001,301,current=50,maximum=350,equip=1),item(9002,301,current=50,maximum=1350),item(9003,301,current=50,maximum=10050),")
    start=prepare.index(' entries=');end=prepare.index('\n with sqlite3.connect',start)
    prepare=prepare[:start]+" entries=(item(1001,30,3),item(1002,17,current=600),item(1003,18,current=1200),item(1004,19,current=3600),item(1005,19,current=3600),item(1006,17,current=550,maximum=600)) if index==0 else (item(2001,30,7),item(2002,18,current=1200))"+prepare[end:]
    result=v.remote(prepare,data['names'])
    result.pop('expected',None)
    (OUT/'fixture-provisioning.json').write_text(json.dumps(result,indent=2))

def run():
    data=json.loads(PRIVATE.read_text());net=v.Network(data)
    report=dict(passed=False,public_tls=True,graphical_clients=False,checks={})
    def bag(index):
        rows=net.command(index,b'\x2f\x01\0\x01\0\0\0',expected=b'\x30')
        return v.decode_item_list([r for r in rows if r[0]==0x30][-1])[1]
    def stock(index):
        rows=net.command(index,b'\x69\0',expected=b'\x6a')
        return tuple(i for p in rows if p[0]==0x6a for i in v.decode_warehouse_list(p)[3])
    def points(index):return v.values(v.assets(net,index))
    try:
        for index in (0,1):net.connect(index)
        initial=[points(i) for i in (0,1)]
        assert initial[0]==[3,9550,73,72,71,2,1],initial
        assert initial[1]==[7,1200,74,73,72,3,1],initial
        assert not any(i.template_id in (17,18,19) for i in bag(0))
        report['initial']=initial;report['checks']['9550_points_with_no_bag_kit']=True
        def fix(target):
            rows=net.command(0,b'\xc2\x03'+struct.pack('<II',1,target),expected=b'\xc8\x39')
            a=v.decode_asset_count(next(p for p in rows if p[:2]==b'\xc8\x39'))
            return rows,a
        rows,a=fix(9001)
        assert a.unknown_u32_08==9259,a
        gear=next(i for i in bag(0) if i.instance_id==9001)
        assert gear.unknown_words==(341,341,350),gear
        kit=next(i for i in stock(0) if i.instance_id==1002)
        assert kit.durability==309
        report['checks']['repair_consumes291_from_stock_kit_and_immediate_counter']=True
        try:fix(9001)
        except AssertionError as e:assert 'не нуждается' in str(e),str(e)
        else:raise AssertionError('Repeated full repair accepted')
        assert points(0)[1]==9259
        report['checks']['repeated_repair_has_no_additional_debit']=True
        _,a=fix(9002)
        assert a.unknown_u32_08==7997,a
        saved=stock(0)
        assert 1002 not in {i.instance_id for i in saved}
        assert next(i for i in saved if i.instance_id==1003).durability==247
        report['checks']['repair_spans_kits_and_removes_exhausted_kit']=True
        _,a=fix(9003)
        assert a.unknown_u32_08==0,a
        assert not any(i.template_id in (17,18,19) for i in stock(0))
        gear=next(i for i in bag(0) if i.instance_id==9003)
        assert gear.unknown_words==(8047,9810,10050),gear
        report['checks']['insufficient_points_partial_repair_exhausts_remaining_stock']=True
        assert points(1)==initial[1]
        final=points(0);assert final==[3,0,73,72,71,2,1],final
        assert next(i for i in stock(1) if i.template_id==18).durability==1200
        assert not any(i.template_id in (17,18,19) for i in bag(0))
        report['checks']['other_account_and_unrelated_assets_preserved']=True
        report['final']=final
    finally:net.close()
    net=v.Network(data)
    try:
        for i in (0,1):net.connect(i)
        assert points(0)==report['final'] and points(1)==initial[1]
        assert next(i for i in bag(0) if i.instance_id==9001).unknown_words==(341,341,350)
        assert not any(i.template_id in (17,18,19) for i in stock(0))
        report['checks']['authoritative_repair_and_debits_survive_reconnect']=True
        report['passed']=True
    finally:
        net.close();(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

def cleanup():
    data=json.loads(PRIVATE.read_text())
    report=v.remote(v.CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (OUT/'fixture-cleanup.json').write_text(json.dumps(report,indent=2));PRIVATE.unlink();print(json.dumps(report))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup'));args=p.parse_args();globals()[args.mode]()
