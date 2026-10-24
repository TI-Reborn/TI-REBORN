"""Owned excluded accounts; main-list merge/removal over the public TLS service."""
import argparse,json,select,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_area_fire_hosted_20261018 as qa
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.wagers import decode_room_list,encode_join,encode_room_removed
qa.OUT=ROOT/'reports/wager-list-fix-20261019';qa.PRIVATE=ROOT/'.secrets/wager-list-fix-20261019.json'
qa.PREPARE=qa.PREPARE.replace("'0x8c4aef':10","'0x8c4aef':2").replace('FLOORS[9]','FLOORS[1]').replace('level=10','level=2').replace('name,2,*center(2)','name,3,*center(3)').replace('town=2','town=3')
base_command=qa.Network.command
def command(self,i,packet=b'\x70',expected=None):
    p=self.peers[i]
    while p.pending or p.sock.pending() or select.select([p.sock],[],[],.05)[0]:p.receive()
    return base_command(self,i,packet,expected)
qa.Network.command=command

def leave(net,i):
    p=net.peers[i];p.send(b'\x2a\1');deadline=time.monotonic()+1.5
    while time.monotonic()<deadline:
        if p.pending or p.sock.pending() or select.select([p.sock],[],[],.1)[0]:p.receive()

def wait_for(net,i,predicate,cut,timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        net.command(i)
        rows=net.received[i][cut:]
        if predicate(rows):return rows
        time.sleep(.15)
    raise AssertionError('Expected shared list update did not arrive')

def run():
    data=qa.load();net=qa.Network(data);report=dict(passed=False,public_tls=True,real_accounts=2,graphical_clients=False)
    request=encode_create_request(ArenaCreateRequest(0,2,2,2,40,1,1,0,1))
    try:
        for i in (0,1):net.connect(i)
        def create():
            cut=len(net.received[1]);net.command(0,request,expected=b'\x6c')
            rows=wait_for(net,1,lambda rows:any(p[:2]==b'\xc8\x2c' and any(r.creator_name.decode('cp1251')==data['names'][0] for r in decode_room_list(p)) for p in rows),cut)
            records=[r for p in rows if p[:2]==b'\xc8\x2c' for r in decode_room_list(p) if r.creator_name.decode('cp1251')==data['names'][0]]
            return records[-1].identity
        a=create();cut=len(net.received[1]);leave(net,0)
        packets=wait_for(net,1,lambda rows:encode_room_removed(a) in rows,cut)
        removal=packets.index(encode_room_removed(a))
        assert any(p[:2]==b'\xc8\x2c' and a not in {r.identity for r in decode_room_list(p)} for p in packets[removal+1:])
        report['creator_close_removed_without_refresh']=True
        b=create();cut=len(net.received[1]);net.peers[0].sock.close()
        wait_for(net,1,lambda rows:encode_room_removed(b) in rows,cut)
        report['creator_disconnect_removed_without_refresh']=True
        net.connect(0);c=create();cut=len(net.received[1]);net.command(1,b'\xba\1')
        packets=wait_for(net,1,lambda rows:b'\x28' in rows and any(p[:2]==b'\xc8\x2c' and c in {r.identity for r in decode_room_list(p)} for p in rows),cut)
        report['explicit_refresh_clears_stale_rows_and_preserves_active']=True
        net.command(1,encode_join(c),expected=b'\x6c');net.command(1,b'\x2c\1');net.command(0,b'\x2e')
        for i in (0,1):wait_for(net,i,lambda rows:any(p[0]==0x41 for p in rows),0)
        battle=qa.state(data);assert battle and not battle['finished']
        data['matches'].append(battle['match']);qa.save(data)
        for i in (0,1):net.command(i,b'\x36')
        leave(net,0);leave(net,1);assert qa.state(data) is None
        for i in (0,1):
            cut=len(net.received[i]);net.command(i,b'\xba\1')
            packets=wait_for(net,i,lambda rows:b'\x28' in rows and any(p[:2]==b'\xc8\x2c' for p in rows),cut)
            assert all(c not in {r.identity for r in decode_room_list(p)} for p in packets if p[:2]==b'\xc8\x2c')
        report.update(passed=True,finished_battle_not_listed=True,owned_room_ids=[a,b,c],match=battle['match'])
    finally:
        for i in tuple(net.peers):
            try:leave(net,i)
            except Exception:pass
        net.close();(qa.OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','state','cleanup'));mode=p.parse_args().mode
    if mode=='run':run()
    elif mode=='state':print(json.dumps(qa.state(qa.load())))
    else:getattr(qa,mode)()
