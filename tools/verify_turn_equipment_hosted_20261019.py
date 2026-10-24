"""Audit battle outfit replacement through two excluded accounts over public TLS."""
import argparse,json,sys,time,select
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_area_fire_hosted_20261018 as qa
from tio.protocol.equipment_batch import EquipmentBatchRequest,encode_equipment_batch,STAGE,COMMIT
from tio.protocol.item_action import ItemAction
from tio.protocol.item_list import decode_item_list
qa.OUT=ROOT/'reports/turn-selection-equipment-20261019'
qa.PRIVATE=ROOT/'.secrets/turn-selection-equipment-20261019.json'
old="inv=encode_item_list(1,(item(91001,314+index,1,1,16),item(91002,14,600,0,0)))"
new="""inv=encode_item_list(1,tuple(item(91001+n,t,1,int(bool(s)),s) for n,(t,s) in enumerate(
 ((301,16),(317,128),(208,1),(210,4),(212,8),(301,0),(208,0),(210,0),(212,0),(254,0)))))"""
assert old in qa.PREPARE;qa.PREPARE=qa.PREPARE.replace(old,new).replace('weapons=[314,315]','weapons=[301,317]')
qa.STATE=r'''
import json,sqlite3,hashlib
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.battle_snapshot import loads
from tio.protocol.item_list import decode_item_list,encode_item_list
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert all(excluded(db,n) for n in names)
 row=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(names[0],)).fetchone()
 if not row:print(json.dumps(None))
 else:
  b=loads(row[1])[0]['battle'];f=b['field'];c=f.combat;turn=b['arena']._turns.get(b['room'].room_id)
  assert {r[0] for r in b['reward_roster'].values()}==set(names) and not b['bots']
  actors=[]
  for a in f._actors.values():
   items=decode_item_list(c.inventories[a.actor_id])[1]
   stable=hashlib.sha256(encode_item_list(0,tuple(replace(i,unknown_u8_01=0,location_raw=0) for i in items))).hexdigest()
   actors.append(dict(id=a.actor_id,owner=a.owner_id,account=b['reward_roster'][a.owner_id][0],ap=a.action_points,hp=a.health,
    items=[dict(id=i.instance_id,template=i.template_id,slot=i.client_slot,equipped=i.equipped) for i in items],metadata_sha256=stable))
  print(json.dumps(dict(match=row[0],finished=b['finished'],turn=turn[0] if turn else None,actors=actors)))
'''

def outfit(items):return {i['slot']:i['id'] for i in items if i['equipped']}

def inventory_request(net,index,identity,packet):
    # 9E is also an unsolicited server heartbeat. It cannot fence requests.
    # Drain queued notifications, then await this action's actual inventory.
    peer=net.peers[index];deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],0.15)[0]:
            peer.receive()
        else:break
    peer.send(packet)
    for _ in range(4096):
        reply=peer.receive()
        if reply.startswith(b'\xf0\x8a\x01\0\0'):
            raise AssertionError(reply[13:-2].decode('utf-16-le',errors='replace'))
        if reply[0]==0x30 and decode_item_list(reply)[0]==identity:return decode_item_list(reply)[1]
    raise AssertionError('Missing inventory response')

def leave(net,index):
    # Do not close on the first9E: it may predate the exit request.
    peer=net.peers[index];peer.send(b'\x2a\1');deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        if peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],0.15)[0]:peer.receive()

def run():
    data=qa.load();net=qa.Network(data)
    report=dict(passed=False,humans=2,bots=0,graphical_clients=False,public_tls=True,cases=[])
    try:
        for i in (0,1):net.connect(i)
        for i in (0,1):net.command(i,b'\xba\3\0\1')
        for i in (0,1):
            if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
        initial=qa.state(data);data['matches'].append(initial['match']);qa.save(data)
        for i in (0,1):net.command(i,b'\x36')
        completed=set();deadline=time.monotonic()+180
        while len(completed)<2 and time.monotonic()<deadline:
            frame=qa.state(data);assert frame and not frame['finished']
            actor=next(a for a in frame['actors'] if a['owner']==frame['turn']);i=data['names'].index(actor['account'])
            if i in completed or actor['ap']<6:
                time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
            identity=actor['id'];expected=outfit(actor['items']);baseline=actor['items'];meta=actor['metadata_sha256']
            def current():return next(a for a in qa.state(data)['actors'] if a['id']==identity)
            def stage(item,option,batch):
                return inventory_request(net,i,identity,encode_equipment_batch(EquipmentBatchRequest(STAGE,batch,ItemAction(identity,item,option))))
            def commit(batch):inventory_request(net,i,identity,encode_equipment_batch(EquipmentBatchRequest(COMMIT,batch)))
            for item,slot,option in ((91006,16,4),(91007,1,0),(91008,4,2),(91009,8,3)):
                preview=stage(item,option,1);expected[slot]=item
                assert {p.client_slot:p.instance_id for p in preview if p.equipped}==expected
            staged=current()
            assert staged['items']==baseline and staged['ap']==actor['ap']
            commit(1);worn=current()
            assert outfit(worn['items'])==expected and worn['ap']==actor['ap']-2 and worn['metadata_sha256']==meta
            commit(1);assert current()==worn
            # Explicitly placing already worn items never toggles them off.
            for item,option in ((91006,4),(91002,7),(91007,0),(91008,2),(91009,3)):stage(item,option,2)
            commit(2);assert current()==worn
            preview=stage(91010,2,3)
            assert {p.client_slot:p.instance_id for p in preview if p.equipped}=={16:91006,128:91002,4:91010}
            commit(3);tank=current()
            assert outfit(tank['items'])=={16:91006,128:91002,4:91010} and tank['ap']==actor['ap']-4
            assert tank['metadata_sha256']==meta
            stage(91007,0,4);commit(4);helmet=current()
            assert outfit(helmet['items'])=={16:91006,128:91002,1:91007} and helmet['ap']==actor['ap']-6
            assert helmet['metadata_sha256']==meta
            other=next(v for v in qa.state(data)['actors'] if v['id']!=identity)
            original_other=next(v for v in frame['actors'] if v['id']==other['id'])
            assert other['items']==original_other['items']
            report['cases'].append(dict(actor=identity,weapon_helmet_chest_legs_replace_only_conflicting_slot=True,
                explicit_rewear_keeps_all_items=True,tank_removes_only_head_chest_legs=True,
                replacing_tank_with_helmet_preserves_both_weapons=True,item_metadata_preserved=True,
                duplicate_confirmation_free=True,other_account_untouched=True,total_ap=6))
            completed.add(i)
        assert len(completed)==2
        report.update(passed=True,match=initial['match'],unexpected_unequips=0)
    finally:
        for i in tuple(net.peers):
            try:leave(net,i)
            except (OSError,EOFError,AssertionError):pass
        net.close();(qa.OUT/'hosted-equipment-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','state','cleanup'));a=p.parse_args()
    if a.mode=='run':run()
    elif a.mode=='state':print(json.dumps(qa.state(qa.load())))
    else:getattr(qa,a.mode)()
