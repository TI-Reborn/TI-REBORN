"""Two excluded production TLS clients: 1A speed, actual 1B routes and 1E stops."""
import argparse
import json
from pathlib import Path
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools import verify_mine_warehouses_hosted_20261023 as qa
from tio.protocol.world_bootstrap import decode_mychar_info

OUT=ROOT/'reports/map-speed-20261023'
qa.OUT=OUT;qa.PRIVATE=ROOT/'.secrets/map-speed-20261023.json'

class Clients(qa.Network):
    def __init__(self,data):
        super().__init__(data)
        self.received={0:[],1:[]}

    def connect(self,index):
        peer=self.tls.handoff(self.tls.begin(self.data['names'][index],37001+index,password=self.data['passwords'][index]))
        original=peer.receive
        def receive():
            value=original();self.received[index].append((time.monotonic(),value));return value
        peer.receive=receive
        self.case.enter(peer,self.data['names'][index]);self.peers[index]=peer
        return peer


ROUTES=r'''
import json,sqlite3,time
from tio.rating_visibility import excluded,QA_LOGIN
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=[]
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  route=db.execute('SELECT x,y,tx,ty,started,arrives FROM map_journeys WHERE account=?',(name,)).fetchone()
  point=db.execute('SELECT town_id,x,y FROM character_locations WHERE account=?',(name,)).fetchone()
  rows.append(dict(route=route,point=point))
 print(json.dumps(dict(states=rows,utc=time.time())))
'''


def run():
    data=json.loads(qa.PRIVATE.read_text());net=Clients(data)
    report=dict(passed=False,public_tls=True,simultaneous_accounts=2,graphical_clients=False,checks=[])
    try:
        for i in (0,1):net.connect(i)
        speeds=[]
        for i in (0,1):
            bootstrap=[decode_mychar_info(p) for _,p in net.received[i] if p[:1]==b'\x1a'][-1]
            assert bootstrap.unknown_u16==12
            speeds.append(bootstrap.unknown_u16)
        starts={};targets=[(-190,-318),(-118,-318)]
        for i in (0,1):
            starts[i]=time.monotonic()
            rows=net.request(i,b'\x1b'+struct.pack('<ii',*targets[i]))
            assert any(p[:1]==b'\x1d' for p in rows)
        state=qa.remote(ROUTES,data['names'])
        durations=[]
        for i,value in enumerate(state['states']):
            route=value['route'];assert route is not None,'Need a live saved route to measure authority'
            assert route[2:4]==list(targets[i]) and abs(route[5]-route[4]-3)<.00001
            durations.append(route[5]-route[4])
        deadline=time.monotonic()+8
        elapsed={}
        while time.monotonic()<deadline and len(elapsed)<2:
            for i in (0,1):
                net.request(i,b'\x70')
                for stamp,p in net.received[i]:
                    if stamp>=starts[i] and p[:1]==b'\x1e' and struct.unpack_from('<ii',p,5)==targets[i]:
                        elapsed[i]=stamp-starts[i]
            if len(elapsed)<2:time.sleep(.05)
        assert len(elapsed)==2,elapsed
        assert all(2.8<=seconds<5.0 for seconds in elapsed.values()),elapsed
        final=qa.remote(ROUTES,data['names'])
        assert all(v['route'] is None for v in final['states'])
        report.update(passed=True,advertised_speeds=speeds,old_speed=6,new_speed=12,
                      distance_per_route=36,server_durations=durations,observed_stop_seconds=elapsed,
                      checks=['1A advertises speed12 to both accounts','genuine 1B creates independent 3-second durable routes',
                              '1D starts movement and 1E stops at each requested target','saved journeys complete under the new speed'])
    finally:
        net.close();(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('provision','run','cleanup'));mode=parser.parse_args().mode
    if mode=='provision':
        qa.provision();data=json.loads(qa.PRIVATE.read_text());qa.remote(qa.MOVE,dict(names=data['names'],town=3))
    elif mode=='cleanup':qa.cleanup()
    else:run()
