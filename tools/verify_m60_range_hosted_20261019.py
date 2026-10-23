"""Two excluded accounts prove M60 range12 and atomic rejection13 over public TLS."""
import argparse,json,sys,time
from pathlib import Path
from tools import verify_area_fire_hosted_20261018 as qa
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.combat_distance import combat_distance

qa.OUT=qa.ROOT/'reports/m60-range-20261019'
qa.PRIVATE=qa.ROOT/'.secrets/m60-range-20261019.json'
qa.PREPARE=qa.PREPARE.replace('314+index','314').replace('weapons=[314,315]','weapons=[314,314]')
start=qa.STATE.index('   def aim_at(actor):');end=qa.STATE.index('   aim=aim_at(a)',start)
qa.STATE=qa.STATE[:start]+'''   assert w.max_range==12
   result['weapon_max_range']=w.max_range
   result['reject_aim']=next(([x,y] for x in range(f.width) for y in range(f.height) if combat_distance((a.x,a.y),(x,y))==13),None)
   def aim_at(actor):
    p=enemy.x,enemy.y
    if combat_distance((actor.x,actor.y),p)==12 and field_sight(f,(actor.x,actor.y),p):return p
'''+qa.STATE[end:]


def rejected(net,i,packet):
    peer=net.peers[i];peer.send(packet);peer.send(b'\x70');rows=[]
    for _ in range(4096):
        r=peer.receive();rows.append(r)
        if r==b'\x9e':break
    else:raise AssertionError('Missing rejection fence')
    assert any(r.startswith(b'\xf0\x8a\x01\0\0') for r in rows)
    assert not any(r[0]==0x4b for r in rows)


def run():
    data=qa.load();net=qa.Network(data);report=dict(passed=False,graphical_clients=False,humans=2,bots=0,shots=[])
    try:
        for i in (0,1):net.connect(i)
        for i in (0,1):net.command(i,b'\xba\3\0\1')
        for i in (0,1):
            if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
        battle=qa.state(data);data['matches'].append(battle['match']);qa.save(data)
        for i in (0,1):net.command(i,b'\x36')
        fired=set();deadline=time.monotonic()+180
        while time.monotonic()<deadline and len(fired)<2:
            frame=qa.state(data,True);assert frame and not frame['finished']
            actor=next(a for a in frame['actors'] if a['owner']==frame['turn']);i=data['names'].index(actor['account'])
            if i in fired or actor['ap']<9:time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
            if frame.get('route'):
                net.command(i,encode_move_request(BattleMove(actor['id'],tuple(map(tuple,frame['route'])))),expected=b'\x3d');continue
            if not frame.get('aim'):time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
            assert combat_distance((actor['x'],actor['y']),frame['aim'])==12
            assert combat_distance((actor['x'],actor['y']),frame['reject_aim'])==13
            rejected(net,i,encode_attack_request(AttackRequest(actor['id'],*frame['reject_aim'])))
            after_denial=qa.state(data);assert after_denial['actors']==frame['actors'],'Rejected shot changed HP/AP/ammo'
            rows=net.command(i,encode_attack_request(AttackRequest(actor['id'],*frame['aim'])),expected=b'\x4b')
            attack=decode_attack_result(next(r for r in rows if r[0]==0x4b));after=qa.state(data)
            own=next(v for v in after['actors'] if v['id']==actor['id']);enemy=next(v for v in after['actors'] if v['id']!=actor['id']);prior=next(v for v in frame['actors'] if v['id']==enemy['id'])
            assert attack.weapon_id==314 and attack.target==tuple(frame['aim'])
            assert enemy['hp']<prior['hp'] and own['ap']==actor['ap']-9
            assert next(v['count'] for v in own['items'] if v['template']==14)==next(v['count'] for v in actor['items'] if v['template']==14)-20
            from tio.protocol.health import encode_health
            net.command(1-i)
            packets=net.received[1-i]
            animated=any(h.actor_id==enemy['id'] and h.left_hp==enemy['hp'] for r in packets if r[0]==0x4b for h in decode_attack_result(r).hits)
            absolute=encode_health(enemy['id'],enemy['hp']) in packets
            assert animated or absolute,'Opponent did not receive authoritative HP'
            report['shots'].append(dict(actor=actor['id'],distance=12,range=frame['weapon_max_range'],damage=prior['hp']-enemy['hp'],ap_spent=9,ammo_spent=20,rejected_distance=13,rejection_atomic=True,opponent_hp_verified=True))
            fired.add(i)
        assert len(fired)==2
        report.update(passed=True,match=battle['match'])
    finally:
        for i in tuple(net.peers):
            try:net.command(i,b'\x2a\1')
            except (OSError,EOFError,AssertionError):pass
        net.close();(qa.OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup'));args=p.parse_args()
    if args.mode=='run':run()
    else:getattr(qa,args.mode)()
