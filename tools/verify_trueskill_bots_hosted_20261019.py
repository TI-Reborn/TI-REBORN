"""Two ranking-excluded real accounts, public TLS, authoritative AI and reload."""
import argparse,json,select,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_area_fire_hosted_20261018 as qa
qa.OUT=ROOT/'reports/trueskill-bots-20261019';qa.PRIVATE=ROOT/'.secrets/trueskill-bots-20261019.json'
qa.PREPARE=qa.PREPARE.replace("'0x8c4aef':10","'0x8c4aef':4").replace('FLOORS[9]','FLOORS[3]').replace('level=10','level=4')
marker='print(json.dumps(dict(only_owned_fixtures=True'
at=qa.PREPARE.index(marker)
qa.PREPARE=qa.PREPARE[:at]+'''
for name in request:
 store=OwnedPetStore(path);_,raw,inventory=store.list(name)[0]
 pet=decode_pet_info(raw,human_equipment=True)
 from tio.protocol.item_list import decode_item_list
 _,items,flag=decode_item_list(inventory)
 for identity in (2,3,4):
  clone=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':identity,'0x8c44a6':0}))
  inv=encode_item_list(identity,tuple(replace(i,instance_id=i.instance_id+identity*1000) for i in items),flag)
  store.ensure(name,clone,inv,human=True)
'''+qa.PREPARE[at:]
qa.STATE='''import json,sqlite3
from tio.rating_visibility import QA_LOGIN,excluded
from tio.battle_snapshot import loads
from tio.protocol.item_list import decode_item_list
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(names[0],)).fetchone()
 if not row:print(json.dumps(None))
 else:
  b=loads(row[1])[0]['battle'];f=b['field'];c=f.combat
  assert {r[0] for r in b['reward_roster'].values()}==set(names)
  turn=b['arena']._turns.get(b['room'].room_id)
  ratings=[]
  if db.execute("select 1 from sqlite_master where name='ranked_players'").fetchone():
   ratings=db.execute('select * from ranked_players where account in (?,?) order by account',names).fetchall()
  print(json.dumps(dict(match=row[0],finished=b['finished'],faulted=b.get('faulted',False),mode=b['room'].request.mode,
   actors=[dict(id=a.actor_id,owner=a.owner_id,side=f.teams[a.owner_id],x=a.x,y=a.y,hp=a.health,ap=a.action_points,
    bot=a.owner_id in b['bots'],generation=f._ability_turns[a.actor_id],
    inventory=[dict(template=i.template_id,count=i.count,equipped=i.equipped) for i in decode_item_list(c.inventories[a.actor_id])[1]],
    persisted=a.actor_id in c.persistence) for a in f._actors.values()],
   humans={str(o):r[0] for o,r in b['reward_roster'].items()},bots=sorted(b['bots']),turn=turn[0] if turn else None,
   scores=b['points'].scores,ranked_teams=b['ranked_teams'],ratings=ratings,
   ranking_excluded=all(excluded(db,n) for n in names))))
'''
base_command=qa.Network.command
def command(self,i,packet=b'\x70',expected=None):
    peer=self.peers[i]
    while peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],.05)[0]:peer.receive()
    return base_command(self,i,packet,expected)
qa.Network.command=command

def join(count):return b'\xc6\x21'+bytes(2)+struct.pack('<I',count)+b''.join(struct.pack('<II',i,0)+b'\0' for i in range(1,count+1))

def leave(net,i):
    peer=net.peers[i];peer.send(b'\x2a\1');deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        if peer.pending or peer.sock.pending() or select.select([peer.sock],[],[],.1)[0]:peer.receive()

def heal(data):
    qa.remote('''import sqlite3,json
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for name in request:
  assert QA_LOGIN.fullmatch(name) and excluded(db,name)
  assert not db.execute('select 1 from battle_checkpoint_members where account=?',(name,)).fetchone()
  for identity,human,raw in db.execute('select pet_id,human,pet_packet from owned_pets where account=?',(name,)).fetchall():
   pet=decode_pet_info(raw,human_equipment=bool(human));fields={**pet.fields,'0x8c4ab1':pet.fields['0x8c4a07']}
   db.execute('update owned_pets set pet_packet=? where account=? and pet_id=?',(encode_pet_info(replace(pet,fields=fields)),name,identity))
print(json.dumps(dict(only_owned_qa=True,healed=True)))
''',data['names'])

def finish():
    data=qa.load()
    for i in (0,1):
        net=qa.Network(data)
        try:net.connect(i);leave(net,i)
        finally:net.close()
    print(json.dumps(qa.state(data)))

def rating_state(data):
    return qa.remote('''import sqlite3,json
from tio.rating_visibility import QA_LOGIN
assert all(QA_LOGIN.fullmatch(n) for n in request['names'])
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 players=[];matches=[]
 if db.execute("select 1 from sqlite_master where name='ranked_players'").fetchone():
  players=db.execute('select * from ranked_players where account in (?,?) order by account',request['names']).fetchall()
 if request['matches'] and db.execute("select 1 from sqlite_master where name='ranked_matches'").fetchone():
  matches=db.execute('select match_id,report from ranked_matches where match_id in ('+','.join('?' for _ in request['matches'])+') order by match_id',request['matches']).fetchall()
 print(json.dumps(dict(players=players,matches=matches)))
''',dict(names=data['names'],matches=data['matches']))

def case(data,counts):
    heal(data);net=qa.Network(data);report=dict(counts=counts,passed=False,graphical_clients=False)
    try:
        for i in (0,1):net.connect(i)
        # A single search still waits for a real opponent and can be cancelled.
        net.command(0,join(counts[0]));assert qa.state(data) is None
        net.command(0,b'\xc6\x23');net.command(0,join(counts[0]))
        rows=net.command(1,join(counts[1]));assert any(p[:2]==b'\xc6\x04' for p in rows)
        for i in (0,1):
            if not any(p[0]==0x41 for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
        before=qa.state(data);data['matches'].append(before['match']);qa.save(data)
        prior_rating=rating_state(data)
        assert before['mode']==21 and not before['faulted'] and before['ranking_excluded']
        assert len(before['actors'])==8 and len(before['bots'])==8-sum(counts)
        for side in (0,1):assert sum(a['side']==side for a in before['actors'])==4
        assert all(not a['persisted'] and not a['inventory'] for a in before['actors'] if a['bot'])
        assert {a['owner'] for a in before['actors'] if not a['bot']}==set(map(int,before['humans']))
        for i in (0,1):net.command(i,b'\x36')
        after=before;deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            after=qa.state(data);assert after and not after['faulted'] and not after['finished']
            if not after['bots'] or all(a['generation']>0 for a in after['actors'] if a['bot']):break
            if str(after['turn']) in after['humans']:
                name=after['humans'][str(after['turn'])];i=data['names'].index(name)
                time.sleep(1.05);net.command(i,b'\x3a'+bytes(4))
            else:time.sleep(.15)
        else:raise AssertionError('Bots did not complete their first turn cycle')
        if after['bots']:
            initial={a['id']:a for a in before['actors']}
            assert any((a['x'],a['y'])!=(initial[a['id']]['x'],initial[a['id']]['y']) for a in after['actors'] if a['bot'])
            assert sum(after['scores'])>0
        # Native reconnect must restore the same eight actors and bot IDs.
        net.peers[0].sock.close();net.connect(0);net.command(0,b'\x36')
        recovered=qa.state(data)
        assert {a['id'] for a in recovered['actors']}=={a['id'] for a in before['actors']}
        assert recovered['bots']==before['bots']
        net.command(0,b'\x2a\1');time.sleep(.4);net.command(1)
        ended=qa.state(data)
        final_rating=rating_state(data)
        if before['bots']:assert final_rating==prior_rating,'Bot battle changed rating or created a rated receipt'
        else:
            assert len(final_rating['players'])==2 and final_rating['players']!=prior_rating['players']
            assert any(match==before['match'] for match,raw in final_rating['matches'])
        if ended:
            assert ended['finished']
            if before['bots']:assert ended['ratings']==before['ratings']
            else:assert len(ended['ratings'])==2 and ended['ratings']!=before['ratings']
        report.update(passed=True,humans=2,bots=len(before['bots']),total_fighters=8,real_opponent_required=True,
            native_acceptance=True,bot_turns_verified=bool(before['bots']),scores_advance=bool(sum(after['scores'])),
            reconnect_same_actors=True,unrated_when_bots=bool(before['bots']),rating_before=prior_rating,rating_after=final_rating,
            real_match_rated=not bool(before['bots']),before=before,after_turns=after,after_end=ended)
    finally:
        for i in tuple(net.peers):
            try:leave(net,i)
            except Exception:pass
        net.close();(qa.OUT/f'hosted-{counts[0]}v{counts[1]}.json').write_text(json.dumps(report,indent=2))
    assert qa.state(data) is None
    return {k:v for k,v in report.items() if k not in ('before','after_turns','after_end')}

def run():
    data=qa.load();cases=[case(data,c) for c in ((1,1),(4,1),(4,4))]
    report=dict(passed=True,public_tls=True,real_accounts=2,graphical_clients=False,cases=cases)
    (qa.OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','state','finish','cleanup'));a=p.parse_args()
    if a.mode=='state':print(json.dumps(qa.state(qa.load())))
    elif a.mode in ('provision','cleanup'):getattr(qa,a.mode)()
    else:globals()[a.mode]()
