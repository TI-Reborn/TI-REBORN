"""Own excluded pair verifies native friendship consent, persistence and online state."""
import argparse,json,select,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_area_fire_hosted_20261018 as qa
from tio.protocol.friends import decode_list
qa.OUT=ROOT/'reports/friends-fix-20261019';qa.PRIVATE=ROOT/'.secrets/friends-fix-20261019.json'
base_command=qa.Network.command
def command(self,i,packet=b'\x70',expected=None):
    p=self.peers[i]
    while p.pending or p.sock.pending() or select.select([p.sock],[],[],.05)[0]:p.receive()
    return base_command(self,i,packet,expected)
qa.Network.command=command

def listing(net,i):
    rows=net.command(i,b'\xa6',expected=b'\x9f');return decode_list(next(p for p in reversed(rows) if p[0]==0x9f))

def run():
    data=qa.load();net=qa.Network(data);r=dict(passed=False,public_tls=True,real_accounts=2,graphical_clients=False)
    try:
        for i in (0,1):net.connect(i)
        assert not listing(net,0) and not listing(net,1)
        invite=b'\xa3'+data['names'][1].encode()+b'\0'
        net.command(0,invite)
        net.command(1,expected=b'\xa0')
        net.command(1,b'\xa1\0');assert not listing(net,0) and not listing(net,1);r['decline_does_not_add']=True
        time.sleep(2.1);net.command(0,invite);net.command(1,expected=b'\xa0');net.command(1,b'\xa1\1')
        for i in (0,1):
            row=listing(net,i);assert len(row)==1 and row[0].name==data['names'][1-i].encode() and row[0].online
        r['mutual_acceptance']=True
        net.peers[1].sock.close();time.sleep(.8)
        row=listing(net,0);assert len(row)==1 and not row[0].online;r['offline_friend_preserved']=True
        net.connect(1)
        assert listing(net,1)[0].name==data['names'][0].encode();assert listing(net,0)[0].online
        r['reconnect_persistence']=True
        net.command(0,b'\xa2'+data['names'][1].encode()+b'\0')
        assert not listing(net,0) and not listing(net,1);r['mutual_removal']=True
        r['passed']=True
    finally:
        net.close();(qa.OUT/'hosted-two-account.json').write_text(json.dumps(r,indent=2))
    print(json.dumps(r))

def hold():
    data=qa.load();net=qa.Network(data);net.connect(1)
    print(json.dumps(dict(connected=True,own_qa=True)),flush=True)
    try:
        for line in sys.stdin:
            cmd=line.strip()
            if cmd=='stop':break
            if cmd=='accept':net.command(1,b'\xa1\1')
            elif cmd=='invite':net.command(1,b'\xa3'+data['names'][0].encode()+b'\0')
            elif cmd=='remove':net.command(1,b'\xa2'+data['names'][0].encode()+b'\0')
            elif cmd=='list':print(json.dumps([dict(name=p.name.decode(),online=p.online) for p in listing(net,1)]),flush=True);continue
            else:net.command(1)
            print(json.dumps(dict(command=cmd,ok=True)),flush=True)
    finally:net.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup','hold'));mode=p.parse_args().mode
    if mode in ('run','hold'):globals()[mode]()
    else:getattr(qa,mode)()
