"""Excluded two-account battle, native scope9 over public TLS; no bots."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_area_fire_hosted_20261018 as qa
from tools.inspect_training_base_20261018 import remote as inspect_remote
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request
qa.OUT=ROOT/'reports/sniper-rifles-20261019';qa.PRIVATE=ROOT/'.secrets/sniper-rifles-20261019.json'
qa.PREPARE=qa.PREPARE.replace('314+index','(5013,313)[index]').replace('91002,14,600','91002,6,60').replace('weapons=[314,315]','weapons=[5013,313]')
start=qa.STATE.index('   def aim_at(actor):');end=qa.STATE.index('   aim=aim_at(a)',start)
qa.STATE=qa.STATE[:start]+'''   assert w.max_range in (15,16)
   result['range']=w.max_range;result['weapon']=weapon;result['required_ap']=3+w.attack_ap;result['shot_ap']=w.attack_ap;result['bullets']=w.bullets_count
   result['reject_aim']=next(([x,y] for x in range(f.width) for y in range(f.height) if combat_distance((a.x,a.y),(x,y))==w.max_range+1 and (x,y) not in f.blocked and field_sight(f,(a.x,a.y),(x,y))),None)
   def aim_at(actor):
    p=enemy.x,enemy.y
    if combat_distance((actor.x,actor.y),p)==w.max_range and field_sight(f,(actor.x,actor.y),p):return p
'''+qa.STATE[end:]
anchor="  if request.get('plan')"
qa.STATE=qa.STATE.replace(anchor,"""  from tio.visibility import visible_actors
  from tio.battle_item_visuals import visible_cells
  result['visible']={str(owner):sorted(visible_actors(f,owner)) for owner in b['views']}
  result['views']={str(owner):sorted(view.visible) for owner,view in b['views'].items()}
  result['cells']={str(owner):visible_cells(f,owner) for owner in b['views']}
  result['scope_areas']=len(c.item_effects['recon']) if hasattr(c,'item_effects') else 0
"""+anchor)

def denied(net,i,packet):
    peer=net.peers[i];peer.send(packet);peer.send(b'\x70');rows=[]
    for _ in range(4096):
        r=peer.receive();rows.append(r)
        if r==b'\x9e':break
    assert any(r.startswith(b'\xf0\x8a\1\0\0') for r in rows)

def run():
    data=qa.load();net=qa.Network(data);report=dict(passed=False,humans=2,bots=0,graphical_clients=False,cases=[])
    try:
        for i in (0,1):net.connect(i)
        for i in (0,1):net.command(i,b'\xba\3\0\1')
        for i in (0,1):
            if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
        b=qa.state(data);data['matches'].append(b['match']);qa.save(data)
        for i in (0,1):net.command(i,b'\x36')
        completed=set();deadline=time.monotonic()+240
        while len(completed)<2 and time.monotonic()<deadline:
            f=qa.state(data,True);assert f and not f['finished']
            a=next(v for v in f['actors'] if v['owner']==f['turn']);i=data['names'].index(a['account'])
            if i in completed or a['ap']<f['required_ap']:time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
            if f.get('route'):
                net.command(i,encode_move_request(BattleMove(a['id'],tuple(map(tuple,f['route'])))),expected=b'\x3d');continue
            if not f.get('aim'):time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
            enemy=next(v for v in f['actors'] if v['id']!=a['id'])
            assert not f['enemy_visible']
            packet=encode_ability_cast(AbilityCast(9,a['id'],0,*f['aim']))
            denied(net,1-i,packet)
            assert qa.state(data)['actors']==f['actors']
            denied(net,i,encode_ability_cast(AbilityCast(9,a['id'],0,*f['reject_aim'])))
            assert qa.state(data)['actors']==f['actors']
            rows=net.command(i,packet);after=qa.state(data)
            own=next(v for v in after['actors'] if v['id']==a['id'])
            assert own['ap']==a['ap']-3 and own['items'][0]['wear']==a['items'][0]['wear']-3
            assert own['items'][1]['count']==a['items'][1]['count']
            assert enemy['id'] in after['visible'][str(a['owner'])] and enemy['id'] in after['views'][str(a['owner'])]
            assert any(p[0]==0x3b and int.from_bytes(p[1:5],'little')==enemy['id'] for p in rows),'Missing native reveal3B'
            cells=after['cells'][str(a['owner'])]
            assert 1<=len(cells)<=5 and not after['cells'][str(enemy['owner'])]
            assert all((x-f['aim'][0])**2+(y-f['aim'][1])**2<=1 for x,y,_ in cells)
            shot=net.command(i,encode_attack_request(AttackRequest(a['id'],enemy['x'],enemy['y'])),expected=b'\x4b')
            attack=decode_attack_result(next(p for p in shot if p[0]==0x4b));end=qa.state(data)
            own_end=next(v for v in end['actors'] if v['id']==a['id'])
            assert own_end['ap']==a['ap']-f['required_ap'] and own_end['items'][1]['count']==a['items'][1]['count']-f['bullets']
            assert attack.weapon_id==f['weapon'] and attack.hits
            net.command(1-i)
            report['cases'].append(dict(actor=a['id'],weapon=f['weapon'],distance=f['range'],hidden_before=True,revealed_by_packet3B=True,
                scope_ap=3,scope_wear=3,scope_ammo=0,cells=after['cells'][str(a['owner'])],
                rejected_distance=f['range']+1,rejected_other_owner=True,shot_ap=f['shot_ap'],shot_ammo=f['bullets'],damage=attack.hits[0].damage,
                checkpoint_roundtrip=True,opponent_no_recon_leak=True))
            completed.add(i)
        assert len(completed)==2
        report.update(passed=True,match=b['match'])
    finally:
        for i in tuple(net.peers):
            try:net.command(i,b'\x2a\1')
            except Exception:pass
        net.close();(qa.OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

def hold():
    from tools import verify_groza_hosted_20261019 as g
    g.OUT=qa.OUT;g.PRIVATE=qa.PRIVATE;g.STATE=qa.STATE
    g.hold()

def heal():
    print(qa.remote('''import sqlite3,json
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  assert not db.execute('select 1 from battle_checkpoint_members where account=?',(name,)).fetchone()
  human,raw=db.execute('select human,pet_packet from owned_pets where account=? and pet_id=1',(name,)).fetchone()
  pet=decode_pet_info(raw,human_equipment=bool(human))
  db.execute('update owned_pets set pet_packet=? where account=? and pet_id=1',(encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000})),name))
print(json.dumps(dict(only_owned_fixtures=True,healed=2)))
''',qa.load()['names']))

def leave():
    data=qa.load()
    for i in (0,1):
        net=qa.Network(data)
        try:
            net.connect(i);net.command(i,b'\x2a\1')
        except Exception:pass
        finally:net.close()
    print(json.dumps(qa.state(data)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','hold','state','leave','heal','cleanup'));a=p.parse_args()
    if a.mode=='state':print(json.dumps(qa.state(qa.load(),True)))
    elif a.mode in ('provision','cleanup'):getattr(qa,a.mode)()
    else:globals()[a.mode]()
