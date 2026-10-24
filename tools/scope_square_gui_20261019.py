"""Pinned release candidate, own excluded account, genuine native hosted GUI."""
import hashlib,json,sys,types,time,select
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_scope_square_hosted_20261019 as scope
from tools import groza_gui_20261019 as gui
from tio.protocol.battle_move import BattleMove,encode_move_request
qa=scope.qa;OUT=qa.OUT
# GUI fixture prefers a nearby legal diagonal; on a blocked diagonal centre
# use the enemy's walkable cell. Dedicated protocol QA tests both diagonals.
qa.STATE=qa.STATE.replace('p=enemy.x-1,enemy.y-1',
    'p=enemy.x-1,enemy.y-1; p=(enemy.x,enemy.y) if p in f.blocked or not f.inside(*p) else p')
qa.STATE=qa.STATE.replace('combat_distance((actor.x,actor.y),p)==18',
    '10<=combat_distance((actor.x,actor.y),p)<=18')

def hold():
    data=qa.load();net=qa.Network(data)
    try:
        for i in (0,1):net.connect(i)
        for i in (0,1):net.command(i,b'\xba\3\0\1')
        for i in (0,1):
            if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
        b=qa.state(data);data['matches'].append(b['match']);qa.save(data)
        for i in (0,1):net.command(i,b'\x36')
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            f=qa.state(data,True);a=next(v for v in f['actors'] if v['owner']==f['turn'])
            i=data['names'].index(a['account'])
            if i==0 and f.get('aim') and a['ap']>=3:break
            if i==0 and f.get('route'):
                net.command(i,encode_move_request(BattleMove(a['id'],tuple(map(tuple,f['route'])))),expected=b'\x3d')
            else:time.sleep(1.05);net.command(i,b'\x3a'+bytes(4))
        else:raise AssertionError('No legal GUI scope position')
        net.peers[0].sock.close()
        for connection in net.case.clients[:2]:connection.close()
        (OUT/'gui-ready.json').write_text(json.dumps(f,indent=2))
        print(json.dumps(dict(ready_for_native_reconnect=True,state=f)),flush=True)
        for line in sys.stdin:
            cmd=line.strip()
            if cmd=='stop':break
            if cmd=='turn':net.command(1,b'\x3a'+bytes(4))
            print(json.dumps(qa.state(data,True)),flush=True)
    finally:
        try:scope.leave_client(net,1)
        except Exception:pass
        net.close()

def launch():
    launcher=ROOT/'work/scope-square-20261019/launcher/TIO Launcher.exe'
    sha=hashlib.sha256(launcher.read_bytes()).hexdigest()
    source=(ROOT/'tools/hosted_graphical_qa_bridge.py').read_text(encoding='utf-8')
    old='d135224ae3803dfcaaaa3602cc2a1cfabe042a03a3c30238b81ddf4a1996dda8'
    assert source.count(old)==1
    auth=types.ModuleType('scope_square_guarded_bridge');auth.__file__=str(ROOT/'tools/hosted_graphical_qa_bridge.py')
    sys.modules[auth.__name__]=auth
    exec(compile(source.replace(old,sha),auth.__file__,'exec'),auth.__dict__)
    auth.static_guards=gui.guards
    data=qa.load();root=gui.WORK/'game-a'
    bridge=auth.HostedGraphicalQaBridge(root,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),
        auto_select=True,launcher=launcher)
    print(json.dumps(dict(pid=bridge.pid,launcher_sha256=sha,started=True,own_qa=True)),flush=True)
    (OUT/'gui-client.json').write_text(json.dumps(dict(pid=bridge.pid,launcher_sha256=sha,root=str(root)),indent=2))
    try:
        for line in sys.stdin:
            cmd=line.strip()
            if cmd=='stop':break
            if cmd=='connect':print(json.dumps(bridge.start_connect()),flush=True)
            elif cmd=='status':print(json.dumps(bridge.status()),flush=True)
    finally:
        (OUT/'gui-guards.json').write_text(json.dumps(bridge.events,indent=2))
        bridge.release(cleanup=True)

if __name__=='__main__':globals()[sys.argv[1]]()
