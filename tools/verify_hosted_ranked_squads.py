"""Verify two disposable TrueSkill squads over production TLS."""
from collections import deque
import json
from pathlib import Path
import secrets
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]

from tools.verify_city_request_fixes_20261103 import fixture_sql, remote
from tools.verify_launcher_required_hosted_20261020 import Network
from tio.protocol.battle_move import BattleMove, encode_move_request
from tio.protocol.battle_turn import encode_end_turn
from tio.turn_repeats import END_TURN_REPEAT_SECONDS
from test_ranked_squads import join

PREPARE = r'''
import json,sqlite3
from pathlib import Path
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.locations import LocationStore,center
from tio.level_progression import FLOORS
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
path='/var/lib/tio-server/reservation.sqlite3'
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
store=OwnedPetStore(path);squads=SquadStore(path);LocationStore(path)
for name in request:
 with sqlite3.connect(path) as db:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  assert not db.execute('SELECT 1 FROM owned_pets WHERE account=?',(name,)).fetchone()
 for identity in range(1,5):
  fields={**pet.fields,'0x8c43eb':identity,'0x8c44a6':0,'0x8c4aef':4,'0x8c4b05':FLOORS[3],
          '0x8c4a07':115,'0x8c4ab1':115}
  store.ensure(name,encode_pet_info(replace(pet,fields=fields)),encode_item_list(identity,()),human=True)
 squads.assign(name,1,1)
 with sqlite3.connect(path) as db:LocationStore._save(db,name,2,*center(2))
print(json.dumps(dict(ready=True)))
'''

STATE = r'''
import sqlite3,json
from tio.battle_snapshot import loads
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(request,)).fetchone()
 b=loads(row[0])[0]['battle'];f=b['field'];p=b['points'];r=b['reward_roster']
 print(json.dumps(dict(match_id=b['match_id'],flags=p.positions,owners=p.owners,scores=p.scores,
  width=f.width,height=f.height,blocked=list(f.blocked),actors=[(a.actor_id,r[a.owner_id][0],a.x,a.y,a.action_points) for a in f._actors.values()])))
'''

CLEAN_MATCHES = r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN
names=set(request);assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3',timeout=15) as db:
 if db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?)',tuple(names)).fetchone():
  print(json.dumps(dict(match_cleanup=False)));raise SystemExit
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_matches'").fetchone():
  for match,payload in db.execute('SELECT match_id,report FROM ranked_matches').fetchall():
   owners={p[0] for team in json.loads(payload)['teams'] for p in team}
   if owners==names:db.execute('DELETE FROM ranked_matches WHERE match_id=?',(match,))
print(json.dumps(dict(match_cleanup=True)))
'''


def route(snapshot: dict, actor: list, destination) -> tuple:
    start = tuple(actor[2:4])
    if destination(start):
        return ()
    blocked = {tuple(cell) for cell in snapshot['blocked']}
    blocked.update(tuple(other[2:4]) for other in snapshot['actors'] if other[0]!=actor[0])
    queue = deque([start])
    paths = {start: ()}
    while queue:
        x,y = queue.popleft()
        for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if (cell in blocked or cell in paths or not 0<=cell[0]<snapshot['width']
                    or not 0<=cell[1]<snapshot['height']):
                continue
            paths[cell] = (*paths[x,y],cell)
            if destination(cell):
                return paths[cell]
            queue.append(cell)
    raise AssertionError('No reachable destination')


def run_battle(net: Network, names: list[str], count: int) -> str:
    peers = [net.connect(i) for i in range(2)]
    selection=join(tuple(range(1,count+1)))
    assert not any(p[:2]==b'\xc6\x04' for p in net.command(0,selection))
    other_size=(2,1,4,3)[count-1]
    assert not any(p[:2]==b'\xc6\x04' for p in net.command(1,join(tuple(range(1,other_size+1)))))
    peers[1].send(selection)
    for peer in peers:
        peer.until(b'\x41',max_packets=1024)
        peer.send(b'\x36')
    peer = peers[0]
    peer.until(b'\x38',max_packets=1024)
    snapshot = remote(STATE,names[0]);match_id = snapshot['match_id']
    ours = [a for a in snapshot['actors'] if a[1]==names[0]]
    assert len(ours)==count and len(snapshot['actors'])==2*count and all(a[4]>0 for a in ours)
    assert all(a[4]==0 for a in snapshot['actors'] if a[1]!=names[0])
    for actor in ours:
        snapshot=remote(STATE,names[0])
        actor=next(a for a in snapshot['actors'] if a[0]==actor[0])
        path=route(snapshot,actor,lambda cell:cell!=tuple(actor[2:4]))
        replies=net.command(0,encode_move_request(BattleMove(actor[0],path)),expected=b'\x3d')
        assert any(p[:5]==b'\x3d'+struct.pack('<I',actor[0]) for p in replies)

    if count<4:
        next_turn(net)
        finish_from_edge(net,names[0],ours)
        peers[1].until(b'\x4c',max_packets=1024);net.command(1,b'\x2a\1')
        return match_id

    target=tuple(snapshot['flags'][2]);runner=ours[0][0]
    near=lambda cell:sum(abs(a-b) for a,b in zip(cell,target))<=2
    for _ in range(16):
        snapshot=remote(STATE,names[0]);actor=next(a for a in snapshot['actors'] if a[0]==runner)
        path=route(snapshot,actor,near)
        if not path:
            break
        if actor[4]:
            for start in range(0,min(len(path),actor[4]),4):
                net.command(0,encode_move_request(BattleMove(runner,path[start:min(start+4,actor[4])])))
        snapshot=remote(STATE,names[0]);actor=next(a for a in snapshot['actors'] if a[0]==runner)
        if near(tuple(actor[2:4])):
            break
        next_turn(net)
    else:
        raise AssertionError('Center flag was not reached')
    assert snapshot['owners'][2]==0
    time.sleep(END_TURN_REPEAT_SECONDS)
    peer.send(encode_end_turn())
    for player in peers:
        for _ in range(256):
            packet=player.receive()
            if packet[:2]==b'\xc6\x16' and struct.unpack('<7I',packet[2:])[3]==10:
                break
        else:
            raise AssertionError('Missing updated flag income')

    # Keep the disposable checkpoint from outliving the fixture cleanup.
    peers[1].until(b'\x38',max_packets=1024)
    time.sleep(END_TURN_REPEAT_SECONDS)
    net.command(1,encode_end_turn());peers[0].until(b'\x38',max_packets=1024)
    finish_from_edge(net,names[0],ours)
    peers[1].until(b'\x4c',max_packets=1024);net.command(1,b'\x2a\1')
    return match_id


def next_turn(net: Network) -> None:
    time.sleep(END_TURN_REPEAT_SECONDS)
    net.command(0,encode_end_turn())
    net.peers[1].until(b'\x38',max_packets=1024)
    time.sleep(END_TURN_REPEAT_SECONDS)
    net.command(1,encode_end_turn())
    net.peers[0].until(b'\x38',max_packets=1024)


def finish_from_edge(net: Network, name: str, actors: list) -> None:
    for _ in range(16):
        snapshot=remote(STATE,name)
        def edge(cell):
            return cell[0] in (1,snapshot['width']-2) or cell[1] in (1,snapshot['height']-2)
        for original in actors:
            snapshot=remote(STATE,name)
            actor=next(a for a in snapshot['actors'] if a[0]==original[0])
            path=route(snapshot,actor,edge)
            for start in range(0,min(len(path),actor[4]),4):
                net.command(0,encode_move_request(BattleMove(actor[0],path[start:min(start+4,actor[4])])))
        if all(edge(tuple(a[2:4])) for a in remote(STATE,name)['actors'] if a[1]==name):
            net.command(0,b'\x2a\1')
            return
        next_turn(net)
    raise AssertionError('Squad did not reach the exit')


def main(count: int) -> None:
    if count not in (1,2,3,4):raise ValueError('Expected squad size from 1 to 4')
    setup=fixture_sql();prefix='qt'+secrets.token_hex(4)
    names=[prefix+s for s in 'ab'];passwords=[secrets.token_urlsafe(24) for _ in names]
    created=remote(setup['CREATE'],list(zip(names,passwords)))
    net=None;match_id=None
    try:
        remote(PREPARE,names)
        net=Network(dict(names=names,passwords=passwords))
        match_id=run_battle(net,names,count)
    finally:
        if net:net.close()
        for _ in range(38):
            if remote(CLEAN_MATCHES,names)['match_cleanup']:
                break
            time.sleep(5)
        else:
            raise RuntimeError('QA battle is still retained')
        remote(setup['CLEANUP'],dict(names=names,protected_before=created['protected_before'],require_unchanged_players=False))
    print(json.dumps(dict(passed=True,match_id=match_id,tls=True,accounts=2,fighters_per_side=count,graphical_clients=False)))


if __name__=='__main__':
    main(int(sys.argv[1]) if len(sys.argv)>1 else 4)
