"""Two excluded disposable accounts exercise real hosted dog encounters over TLS.

No graphical rendering claim. Read only each QA account's checkpoint to choose
a route; send all gameplay through the public native protocol. Never alter a
live battle or a real player's state.
"""
import hashlib
import json
from pathlib import Path
import secrets
import socket
import ssl
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'work/encounter-movement-20261017/candidate'
sys.path[:0]=[str(CANDIDATE),str(CANDIDATE/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
saved_path=list(sys.path)
from tools.verify_game_operations_hosted import remote,CREATE,CLEANUP
sys.path[:]=saved_path
from tio.rating_visibility import QA_LOGIN
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_turn import encode_end_turn
REPORT=ROOT/'reports/encounter-movement-20261017'

PREPARE=r'''
import json,sqlite3
from pathlib import Path
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
path='/var/lib/tio-server/reservation.sqlite3'
raw=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex'])
pet=decode_pet_info(raw,human_equipment=True)
raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4a07':200,'0x8c4ab1':200}))
for name in request:
 assert QA_LOGIN.fullmatch(name)
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(name,)).fetchone()
  assert not db.execute('SELECT 1 FROM owned_pets WHERE account=?',(name,)).fetchone()
 OwnedPetStore(path).ensure(name,raw,encode_item_list(1,()),human=True)
 SquadStore(path).assign(name,1,1)
print(json.dumps(dict(owned_fixtures_only=True,health=200)))
'''

PLAN=r'''
import json,sqlite3
from collections import deque
from tio.rating_visibility import QA_LOGIN
from tio.battle_snapshot import loads
from tio.visibility import visible_actors
from tio.protocol.battle_move import BattleMove,decode_battle_move
name=request['name'];assert QA_LOGIN.fullmatch(name)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m ON m.match_id=c.match_id WHERE m.account=?',(name,)).fetchall()
if not rows:print(json.dumps(dict(active=False)))
else:
 assert len(rows)==1
 match,payload=rows[0];data=loads(payload)[0]
 assert data['kind']=='private' and data['account']==name
 arena=data['arena'];room=arena.rooms.snapshot()[0];field=arena._fields[room.room_id]
 assert field.scene_metadata['profile']=='infected_dogs'
 owner=room.owner_id;actor=field.actor(field.actor_ids(owner)[0]);start=(actor.x,actor.y)
 dogs=[a for a in field._actors.values() if not field.allied(a.owner_id,owner) and a.health]
 known=visible_actors(field,owner);occupied={(a.x,a.y) for a in field._actors.values() if a.actor_id!=actor.actor_id and a.health}
 candidates=[]
 if request['mode']=='dog':
  for dog in sorted(dogs,key=lambda a:a.actor_id in known):
   goal=(dog.x,dog.y);queue=deque([start]);previous={start:None}
   while queue and goal not in previous:
    x,y=queue.popleft()
    for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
     if cell in previous or not field.inside(*cell) or cell in field.blocked or cell in occupied and cell!=goal:continue
     previous[cell]=(x,y);queue.append(cell)
   if goal not in previous:continue
   path=[];p=goal
   while previous[p] is not None:path.append(p);p=previous[p]
   path=tuple(reversed(path))
   if 1<len(path)<=actor.action_points:candidates.append((path,dog.actor_id not in known));break
 else:
  for p in ((actor.x-1,actor.y),(actor.x+1,actor.y),(actor.x,actor.y-1),(actor.x,actor.y+1)):
   if field.inside(*p) and p not in field.blocked|occupied and actor.action_points:candidates.append(((p,),False));break
 assert candidates,'No bounded movement route for QA'
 path,hidden=candidates[0];before_ap=actor.action_points
 moved=decode_battle_move(field.move(owner,BattleMove(actor.actor_id,path)))
 after=field.actor(actor.actor_id)
 print(json.dumps(dict(active=True,match=match,actor=actor.actor_id,owner=owner,path=path,expected=moved.path,
  before=start,ap_before=before_ap,ap_after=after.action_points,hidden_dog=hidden,
  turn=arena._turns.get(room.room_id,(None,))[0],hp=actor.health)))
'''

REMAINING=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN
assert all(QA_LOGIN.fullmatch(n) for n in request)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 print(json.dumps(db.execute('SELECT account,match_id FROM battle_checkpoint_members WHERE account IN (?,?)',request).fetchall()))
'''


def main():
    expected=json.loads((REPORT/'patch-manifest.json').read_text())['tio/battle_state.py']['after']
    actual=remote("from pathlib import Path\nimport hashlib,json\nprint(json.dumps(hashlib.sha256(Path('tio/battle_state.py').read_bytes()).hexdigest()))",None)
    assert actual==expected,'Hosted patch is not installed'
    names=['qm'+secrets.token_hex(4)+suffix for suffix in ('a','b')]
    assert all(QA_LOGIN.fullmatch(n) for n in names)
    passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(passed=False,graphical_clients=False,fixtures=names,clients=[],runtime_sha256=actual)
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();peers=[];provision=None
    frames=[dict(turn=False,loaded=False,moves=[],dog_moves=0,attacks=0) for n in names]
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def command(index,packet=None):
        peer=peers[index];state=frames[index]
        if packet is not None:peer.send(packet)
        peer.send(b'\x70');packets=[]
        for _ in range(4096):
            reply=peer.receive()
            if reply==b'\x9e':return packets
            packets.append(reply)
            if reply==b'\x41':state['loaded']=True
            elif reply[0]==0x38:state['turn']=True
            elif reply[0]==0x39:state['turn']=False
            elif reply[0]==0x3d:
                m=decode_battle_move(reply);state['moves'].append(m)
                if m.actor_id>=0x71000000:state['dog_moves']+=1
            elif reply[0]==0x4b:state['attacks']+=1
            if reply.startswith(b'\xf0\x8a\x01\0\0'):
                raise AssertionError('Native gameplay command rejected')
        raise AssertionError('Missing ping fence')
    def move(index,mode):
        plan=remote(PLAN,dict(name=names[index],mode=mode))
        assert plan['active'] and plan['turn']==plan['owner']
        path=tuple(map(tuple,plan['path']));wanted=tuple(map(tuple,plan['expected']))
        replies=command(index,encode_move_request(BattleMove(plan['actor'],path)))
        movement=[decode_battle_move(p) for p in replies if p[0]==0x3d and int.from_bytes(p[1:5],'little')==plan['actor']]
        assert len(movement)==1 and movement[0].path==wanted,(movement,wanted)
        from tio.protocol.action_points import encode_action_points
        assert encode_action_points(plan['actor'],plan['ap_after']) in replies
        result={k:plan[k] for k in ('match','hidden_dog','ap_before','ap_after')}
        result.update(requested_steps=len(path),travelled_steps=len(wanted),position=wanted[-1])
        if mode=='dog':assert 0<len(wanted)<len(path),'Route did not stop before the dog'
        return result
    try:
        provision=remote(CREATE,list(zip(names,passwords)))
        report['ranking_excluded']=provision['ranking_excluded'];report['fixture_setup']=remote(PREPARE,names)
        for index in range(2):
            peer=tls.handoff(tls.begin(names[index],35001+index,password=passwords[index]));case.enter(peer,names[index]);peers.append(peer)
            command(index,struct.pack('<Bii',0x1b,400,300))
        deadline=time.monotonic()+150
        while not all(f['loaded'] for f in frames):
            if time.monotonic()>=deadline:raise AssertionError('Natural dog encounter timed out')
            for index in range(2):command(index)
            time.sleep(.5)
        for index in range(2):command(index,b'\x36')
        for index in range(2):
            contact=move(index,'dog');continuation=move(index,'free')
            command(index,encode_end_turn(0))
            deadline=time.monotonic()+25
            while not frames[index]['turn']:
                if time.monotonic()>=deadline:raise AssertionError('Next player turn timed out')
                command(index);time.sleep(.2)
            next_turn=move(index,'free')
            report['clients'].append(dict(contact=contact,continuation=continuation,next_turn=next_turn,
                dog_move_packets=frames[index]['dog_moves'],attack_packets=frames[index]['attacks']))
        assert len({c['contact']['match'] for c in report['clients']})==2
        report['passed']=True
    finally:
        for index in range(len(peers)):
            try:command(index,b'\x2a\1')
            except (OSError,EOFError,AssertionError):pass
        for sock in case.clients:
            try:sock.close()
            except OSError:pass
        (REPORT/'hosted-verification.json').write_text(json.dumps(report,indent=2))
        if provision:
            remaining=remote(REMAINING,names)
            if remaining:raise RuntimeError('Owned QA checkpoint remains; retain fixtures for safe cleanup')
            report['cleanup']=remote(CLEANUP,dict(names=names,protected_before=provision['protected_before'],require_unchanged_players=False))
        (REPORT/'hosted-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()
