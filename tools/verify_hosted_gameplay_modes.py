"""Four fresh owned accounts: FFA and wagers through verified native TLS.

Run only after a reviewed deployment. This tool does not provision accounts,
reset saves, assign gameplay fixtures or deploy code. Supply two previously
provisioned empty Stage7 pairs (or one owned fresh four-account fixture).
Characters and all gameplay changes use ordinary client packets. Remote SQL
is read-only. Automated protocol evidence is separate from graphical QA.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from tools.verify_game_tls_hosted import TlsNetworkQA, tls_context
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, require
from tools.verify_hosted_stage7 import Stage7Fixture
from tio.appearance import encode_request as appearance_request
from tio.protocol.character_create import CharacterCreateRequest, encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.world_bootstrap import decode_mychar_info
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.arena import ArenaCreateRequest, encode_create_request
from tio.protocol.battle_members import decode_battle_members
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.wagers import decode_room_list, encode_join


# Credentials remain in the private local fixture. Only ownership proofs and
# salted credential comparisons occur remotely; neither is returned publicly.
SNAPSHOT = r'''
import hashlib,json,pathlib,re,sqlite3,subprocess,sys
from contextlib import closing
from tio.character_identity import alias
from tio.protocol.pet_info import decode_pet_info
from tio.weapon_proficiency import SAVED,BASE,CAPS
from tio.battle_snapshot import loads
data=json.load(sys.stdin);names=data['names']
assert len(names)==4 and len(set(names))==4
assert all(re.fullmatch(r'qs[0-9a-f]{8}[a-h]',n) for n in names)
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db,db:
 db.execute('BEGIN')
 proven=[]
 for fixture in data['fixtures']:
  folder=pathlib.Path(fixture['backup']).resolve();pair=fixture['names']
  assert folder.parent==pathlib.Path('/root') and folder.name.startswith('tio-before-surroundings-qa-')
  proof=json.loads((folder/'qa-owned.json').read_text());assert pair==proof['names']
  with closing(sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True)) as old,old:
   assert not any(old.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in pair)
  for n in pair:
   row=db.execute('SELECT hex(salt),hex(digest),iterations FROM accounts WHERE login=?',(n,)).fetchone()
   assert row and list(row)==proof['credentials'][n]
  proven.extend(pair)
 assert proven==names
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 owned=[o for n in names for o in (n,alias(n,2))];marks=','.join('?' for _ in owned)
 def rows(table,account,n):
  return list(db.execute('SELECT * FROM "'+table+'" WHERE "'+account+'"=? ORDER BY 1,2',(n,))) if table in tables else []
 states=[]
 for n in names:
  character=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(n,)).fetchone() if 'characters' in tables else None
  identities=list(db.execute('SELECT slot,owner FROM character_identities WHERE login=?',(n,))) if 'character_identities' in tables else []
  assert not identities,'This QA creates only ordinary primary characters'
  wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(n,)).fetchone() if 'wallets' in tables else None
  pets=[]
  for identity,human,raw in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(n,)) if 'owned_pets' in tables else []:
   f=decode_pet_info(raw,human_equipment=bool(human)).fields
   keys=(*SAVED,*BASE,*CAPS,'0x8c4aef','0x8c4b05','0x8c4bbc','0x8c4bd0','0x8c4be3','0x8c4bf6')
   pets.append(dict(id=identity,progression={key:f[key] for key in keys},sha256=hashlib.sha256(raw).hexdigest()))
  rank={table:rows(table,'account',n) for table in ('soldier_ranks','rank_clock','ranked_players')}
  states.append(dict(account=n,name=character[0].decode('ascii') if character else None,wallet=list(wallet) if wallet else None,pets=pets,ranks=rank))
 foreign={}
 for table in sorted(tables-{'sqlite_sequence'}):
  quoted='"'+table.replace('"','""')+'"';columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
  account=next((c for c in ('account','login','owner') if c in columns),None)
  if account:
   query='SELECT * FROM '+quoted+' WHERE "'+account+'" NOT IN ('+marks+')';args=owned
  elif 'sender' in columns and 'recipient' in columns:
   query='SELECT * FROM '+quoted+' WHERE sender NOT IN ('+marks+') AND recipient NOT IN ('+marks+')';args=owned+owned
  else:continue
  frozen=sorted(map(repr,db.execute(query,args)))
  foreign[table]=dict(rows=len(frozen),sha256=hashlib.sha256(json.dumps(frozen).encode()).hexdigest())
 checkpoints=[]
 if 'battle_checkpoints' in tables:
  for match,payload,status in db.execute('SELECT match_id,payload,status FROM battle_checkpoints WHERE match_id IN (SELECT match_id FROM battle_checkpoint_members WHERE account IN ('+marks+'))',owned):
   battle=loads(payload)[0]['battle'];field=battle['field'];room=battle['room'];turn=battle['arena']._turns.get(room.room_id)
   roster=battle['reward_roster'];assert {r[0] for r in roster.values()}<=set(names),'Unrelated account joined owned QA battle'
   checkpoints.append(dict(match=match,status=status,kind=battle.get('kind','ordinary'),finished=battle['finished'],
    wager_active=battle.get('wager_active',False),bots=len(battle['bots']),loading=len(battle['arena']._loading[room.room_id]),
    members=[dict(owner=o,account=roster[o][0],side=roster[o][2]) for o in room.members],
    turn=turn[0] if turn else None,turn_seconds=room.request.unknown_u32_01,
    sides=len(field.living_sides()),width=field.width,height=field.height,
    actors=[dict(id=a.actor_id,owner=a.owner_id,x=a.x,y=a.y,hp=a.health,ap=a.action_points,blocked=(a.x,a.y) in field.blocked) for a in field._actors.values()]))
 wagers=[]
 if 'wager_matches' in tables:
  for match,status,stake,pot,outcome in db.execute('SELECT match_id,status,stake,pot,outcome FROM wager_matches WHERE match_id IN (SELECT match_id FROM wager_members WHERE account IN ('+marks+')) ORDER BY created_at,match_id',owned):
   members=list(db.execute('SELECT account,side,forfeited FROM wager_members WHERE match_id=? ORDER BY account',(match,)))
   assert {r[0] for r in members}<=set(names),'Unrelated account in owned QA escrow'
   receipts=list(db.execute('SELECT account,kind,amount FROM wager_receipts WHERE match_id=? ORDER BY account',(match,)))
   wagers.append(dict(match=match,status=status,stake=stake,pot=pot,outcome=json.loads(outcome) if outcome else None,members=members,receipts=receipts))
 leases=list(db.execute('SELECT account,match_id FROM wager_leases WHERE account IN ('+marks+')',owned)) if 'wager_leases' in tables else []
 idle={t:db.execute('SELECT count(*) FROM "'+t+'"').fetchone()[0] if t in tables else 0 for t in ('battle_checkpoints','battle_settlement_jobs')}
 sources={name:hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest() for name in data['source_hashes']}
 assert sources==data['source_hashes'],'Reviewed deployment sources changed'
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0];assert integrity=='ok'
connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
print(json.dumps(dict(states=states,foreign=foreign,checkpoints=checkpoints,wagers=wagers,leases=leases,idle=idle,integrity=integrity,source_sha256=sources,game_connections=connections)))
'''


def deployment_hashes(path,*,deployed_only=False):
    proof=json.loads(Path(path).read_text(encoding='utf-8'))
    require(proof.get('source_parity') is True,'Reviewed successful source parity required')
    values=proof.get('source_sha256')
    require(isinstance(values,dict) and 1<=len(values)<=512,'Bounded deployment source proof required')
    required={'tio/wagers.py','server/wager_arena.py','server/team_arena.py','tio/team_scene.py','tio/battle_rewards.py','tio/matchmaking.py'}
    require(required<=values.keys(),'Deployment proof does not cover gameplay modes')
    for name,digest in values.items():
        require(isinstance(name,str) and re.fullmatch(r'(?:tio|server|tools|config|evidence)/[A-Za-z0-9_./-]+',name) and '..' not in Path(name).parts,'Unsafe source path')
        require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest),'Invalid reviewed source digest')
        if not deployed_only:
            require(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,'Local/deployed reviewed source mismatch')
    return values


class FourFixture:
    def __init__(self, fixtures):
        self.fixtures=tuple(fixtures)
        self.names=[n for fixture in fixtures for n in fixture.names]
        self.passwords=[p for fixture in fixtures for p in fixture.passwords]
        require(len(self.names)==4 and len(set(self.names))==4,'Four distinct owned accounts required')
        require(all(f.backup and f.host==fixtures[0].host and f.key==fixtures[0].key for f in fixtures),'Provisioned fixtures must share host and SSH identity')
        self.host=fixtures[0].host

    def status(self, hashes):
        return self.fixtures[0].remote(SNAPSHOT,dict(names=self.names,fixtures=[f.ownership_payload() for f in self.fixtures],source_hashes=hashes))


class FourNetwork(TlsNetworkQA):
    def connect(self, port, *, label):
        connection=super().connect(port,label=label)
        for value in self.fixture.names[2:]+self.fixture.passwords[2:]:
            for encoding in ('utf-8','utf-16-le'):connection.audit.add_pattern(value.encode(encoding))
        return connection

    def begin(self,index):
        # The shared helper guards a pair. Four pending native handoffs already
        # count as authenticated accounts; retain that guard with a bound of four.
        import socket
        from test_server_deployment import Peer
        from tools.verify_game_tls_hosted import login_preface
        from tio.protocol.transport import (decode_initial_challenge,expected_reply_fields,
            InitialReply,encode_initial_reply,decode_initial_completion)
        from tio.protocol.login import BasicLoginRequest,encode_basic_login_request,transform_auth_value
        from tio.protocol.server_list import ServerListRequest,encode_server_list_request,decode_server_list
        from tio.protocol.server_login import ServerLoginRequest,encode_server_login_request
        connection=self.connect(self.login_port,label='login');connection.sendall(login_preface(self.local_session_port));peer=Peer(connection)
        fields=expected_reply_fields(decode_initial_challenge(peer.receive()))
        peer.send(encode_initial_reply(InitialReply(*fields,0,bytes(3))))
        token=decode_initial_completion(peer.receive()).unknown_u32_01
        connection.capture_next_write=True
        peer.send(encode_basic_login_request(BasicLoginRequest(self.fixture.names[index].encode(),self.fixture.passwords[index].encode(),transform_auth_value(token))))
        require(peer.receive()==b'\x04\0','Verified TLS account login failed')
        peer.send(encode_server_list_request(ServerListRequest(0,0,b'')));entries=decode_server_list(peer.receive()).entries
        require(len(entries)==1,'One shared hosted backend required');entry=entries[0]
        require(entry.address_octets==socket.inet_aton('127.0.0.1') and entry.unknown_u16_01==self.local_session_port,'Verified TLS handoff loopback route differs')
        require(entry.unknown_u16_02<=4,'Other players online; abort owned matchmaking')
        peer.send(encode_server_login_request(ServerLoginRequest(1,bytes(8))))
        require(peer.receive()==b'\x08\0','Ordinary native handoff preparation failed');connection.close()
        return fields[1],token

    def attach(self,index,key,*,fresh=True,expected_wallet=None):
        peer=self.handoff(key);self.received[index]=[];original=peer.receive
        def receive():
            packet=original();self.received[index].append(packet);return packet
        peer.receive=receive;self.peers[index]=peer
        records=self.case.character_screen(peer)
        name=self.fixture.names[index].encode()
        if fresh:
            require(not records,'Fresh empty owned character screen required')
            peer.send(encode_character_create(CharacterCreateRequest(name,0,(index%2+1,0,0,0))))
            require(peer.receive()==b'\x12\x05','Ordinary primary character creation failed')
            editing=decode_character_list(peer.receive())
            require(len(editing)==1 and editing[0].record_id==1 and editing[0].name_bytes==name and len(editing[0].optional_six)==6,'Native free appearance editor missing')
            peer.send(appearance_request(1,editing[0].optional_six));records=decode_character_list(peer.until(b'\x10'))
        require([(r.record_id,r.name_bytes) for r in records]==[(1,name)],'Ordinary primary slot missing')
        peer.send(b'\x17\x01\0\0\0');require(peer.receive().startswith(b'\x18'),'Native slot selection failed')
        peer.send(b'\x19');character=decode_mychar_info(peer.until(b'\x1a'))
        require((character.character_id,character.name_bytes)==(1,name),'Native own character identity differs')
        assets=decode_asset_count(peer.until(b'\xc8\x39'));pet=decode_pet_info(peer.until(b'\x66'),human_equipment=True)
        require([assets.credits,assets.gold]==(expected_wallet or [3000,0]) and pet.fields['0x8c4aef']==1 and pet.fields['0x8c4b05']==0,'Ordinary owned level-one character or lawful wallet differs')
        self.ping(peer)

    def sync(self,indices=range(4)):
        for index in indices:self.ping(self.peers[index])


def wait_state(fixture,hashes,predicate,*,seconds=15):
    deadline=time.monotonic()+seconds
    while True:
        state=fixture.status(hashes)
        if predicate(state):return state
        require(time.monotonic()<deadline,'Authoritative gameplay state deadline exceeded')
        time.sleep(.15)


def one_battle(state,indices,names):
    require(len(state['checkpoints'])==1,'Exactly one owned shared checkpoint required')
    battle=state['checkpoints'][0]
    require({r['account'] for r in battle['members']}=={names[i] for i in indices} and not battle['bots'],'Owned real accounts must fill the entire shared battle')
    require(battle['status']=='active' and not battle['finished'],'Active shared checkpoint required')
    return battle


def progression(state):
    return [(r['account'],[(p['id'],p['progression']) for p in r['pets']],r['ranks']) for r in state['states']]


def balances(state):return [r['wallet'] for r in state['states']]


def validate_resumed_state(state,names):
    expected={name:3000 for name in names}
    for wager in state['wagers']:
        require(wager['status'] in ('settled','refunded'),'Resume cannot reset or reuse pending wagers')
        accounts=[r[0] for r in wager['members']];receipts=wager['receipts']
        require(len(accounts)==len(set(accounts)) and set(accounts)<=set(names) and {r[0] for r in receipts}==set(accounts) and len(receipts)==len(accounts),'Owned prior wager receipts are incomplete')
        require(wager['pot']==wager['stake']*len(accounts) and sum(r[2] for r in receipts)==wager['pot'],'Owned prior escrow does not conserve its pot')
        for account,kind,amount in receipts:
            require(kind in ('win','lose','refund') and type(amount) is int and amount>=0,'Invalid owned prior receipt')
            if wager['status']=='refunded':require(kind=='refund' and amount==wager['stake'],'Prior refund differs from reserved stake')
            else:require(kind!='refund' and (kind!='lose' or amount==0),'Prior settlement receipt differs')
            expected[account]+=amount-wager['stake']
    for row,name in zip(state['states'],names):
        require(row['account']==name and row['name']==name and len(row['pets'])==1 and row['pets'][0]['id']==1,'Resume requires the same ordinary primary characters')
        profile=row['pets'][0]['progression']
        require(profile['0x8c4aef']==1 and profile['0x8c4b05']==0,'Resume requires original level-one zero-XP owned starters')
        require(row['wallet']==[expected[name],0],'Existing owned wallet is not explained by starting funds and durable wager receipts')
    return [expected[name] for name in names]


def wait_native(net,index,start,predicate,*,seconds=4):
    deadline=time.monotonic()+seconds
    while True:
        matches=[packet for packet in net.received[index][start:] if predicate(packet)]
        if matches:return matches[-1]
        require(time.monotonic()<deadline,'Native asynchronous reply deadline exceeded')
        time.sleep(.15);net.ping(net.peers[index])


def wait_wager_room(net,index,creator,request,prior_ids,*,seconds=6):
    deadline=time.monotonic()+seconds;observations=[]
    while True:
        packets=net.command(index,b'\xba\x01');matched=[]
        for packet in packets:
            if not packet.startswith(b'\xc8\x2c'):continue
            rooms=decode_room_list(packet)
            candidates=[room for room in rooms if room.identity not in prior_ids and room.creator_name==creator and room.mode==request.mode and room.capacity==request.players_count and room.stake==request.stake]
            observations.append(dict(rows=len(rooms),matching=len(candidates)))
            matched.extend(candidates)
        identities={room.identity for room in matched}
        require(len(identities)<=1,'Multiple owned new rooms match the native request')
        if matched:return matched[-1],observations
        require(time.monotonic()<deadline,'Native list never exposed the newly created owned wager room')
        time.sleep(.2)


def wait_ready(net,indices,start,names):
    expected={names[i].encode() for i in indices}
    captain=names[indices[0]].encode()
    def ready(packet):
        if not packet.startswith(b'\x25'):return False
        records=decode_battle_members(packet)[2]
        return {r.name for r in records}==expected and all(r.ready for r in records if r.name!=captain)
    wait_native(net,indices[0],start,ready)


def preserve(before,after):
    # New account-scoped tables with zero foreign rows are harmless. Global
    # receipt/match tables intentionally are not frozen by this comparison.
    for table,value in before['foreign'].items():
        require(after['foreign'].get(table)==value,'Foreign account rows changed: '+table)
    require(all(not value['rows'] for table,value in after['foreign'].items() if table not in before['foreign']),'New foreign account rows appeared during owned QA')
    require(after['integrity']=='ok','Database integrity failed')
    return {table:value['rows'] for table,value in before['foreign'].items()}


def load_battle(net,fixture,hashes,indices,offsets):
    for index in indices:
        start=offsets[index]
        if b'\x41' not in net.received[index][start:]:net.peers[index].until(b'\x41',max_packets=4096)
        packets=net.received[index][start:]
        require(any(p.startswith(b'\x35') for p in packets),'Native combat scene missing')
    loading=fixture.status(hashes);battle=one_battle(loading,indices,fixture.names)
    require(battle['loading']==0 and battle['turn'] is None,'Turn began before native loading acknowledgements')
    for index in indices[:-1]:net.command(index,b'\x36')
    partial=one_battle(fixture.status(hashes),indices,fixture.names)
    require(partial['loading']==len(indices)-1 and partial['turn'] is None,'Incomplete loading barrier admitted a turn')
    net.command(indices[-1],b'\x36')
    active=wait_state(fixture,hashes,lambda s:len(s['checkpoints'])==1 and s['checkpoints'][0]['turn'] is not None)
    battle=one_battle(active,indices,fixture.names);net.sync(indices)
    require(battle['loading']==len(indices),'All real participants must acknowledge scene loading')
    return active,battle


def exit_results(net,fixture,hashes,indices):
    net.sync(indices)
    for index in indices:net.command(index,b'\x2a\x01')
    net.sync(indices)
    return wait_state(fixture,hashes,lambda s:not s['checkpoints'] and not s['leases'] and not any(s['idle'].values()))


def verify_survival(net,fixture,hashes,report):
    offsets={i:len(net.received[i]) for i in range(4)}
    for index in range(4):net.command(index,b'\xba\x03\0\x01')
    active,battle=load_battle(net,fixture,hashes,list(range(4)),offsets)
    require(battle['sides']==4,'Four-player survival must have four independent sides')
    cells=[(a['x'],a['y']) for a in battle['actors']]
    require(len(cells)==4 and len(set(cells))==4 and all(a['hp']>0 and not a['blocked'] and 0<=a['x']<battle['width'] and 0<=a['y']<battle['height'] for a in battle['actors']),'Four real starter actors need distinct legal spawns')
    by_owner={m['owner']:fixture.names.index(m['account']) for m in battle['members']};visited=[]
    for _ in range(4):
        owner=battle['turn'];visited.append(owner);index=by_owner[owner]
        require(any(p.startswith(b'\x38') for p in net.received[index]),'Native YourTurn packet missing')
        net.command(index,encode_end_turn())
        active=wait_state(fixture,hashes,lambda s:len(s['checkpoints'])==1 and s['checkpoints'][0]['turn'] not in (None,owner))
        battle=one_battle(active,list(range(4)),fixture.names);net.sync()
    require(len(set(visited))==4 and battle['turn']==visited[0],'Survival did not complete the four-account turn circle')
    for index in (1,2,3):net.command(index,b'\x2a\x01')
    wait_state(fixture,hashes,lambda s:s['checkpoints'] and s['checkpoints'][0]['finished'])
    exit_results(net,fixture,hashes,list(range(4)))
    report['survival4']=dict(players=4,bots=0,loading_barrier=True,turn_circle=4,native_scene=True)


def verify_wager(net,fixture,hashes,report,count,mode):
    indices=list(range(count));before=fixture.status(hashes);wallets=balances(before);old_matches={w['match'] for w in before['wagers']}
    request=ArenaCreateRequest(mode,2,count,2,40,1,1,0,100)
    prior_ids={room.identity for packets in net.received.values() for p in packets if p.startswith(b'\xc8\x2c') for room in decode_room_list(p)}
    room_start=len(net.received[0]);net.command(0,encode_create_request(request))
    wait_native(net,0,room_start,lambda p:p.startswith(b'\x6c'))
    room,observations=wait_wager_room(net,count-1,fixture.names[0].encode(),request,prior_ids)
    report.setdefault('native_room_list_observations',{})['wager'+str(count)]=observations
    for index in indices[1:]:net.command(index,encode_join(room.identity))
    for index in indices[1:]:net.command(index,b'\x2c\x01')
    wait_ready(net,indices,room_start,fixture.names)
    start=time.monotonic();held_start=len(net.received[0]);net.command(0,b'\x2e')
    wait_native(net,0,held_start,lambda p:p.startswith(b'\xc8\x39') and decode_asset_count(p).credits==wallets[0][0]-100,seconds=2)
    net.command(indices[-1],b'\x2c\x00')
    require(time.monotonic()-start<5,'Cancellation was not sent within the five-second countdown')
    net.sync(indices);cancelled=fixture.status(hashes)
    new=[w for w in cancelled['wagers'] if w['match'] not in old_matches]
    require(len(new)==1 and new[0]['status']=='refunded' and new[0]['pot']==count*100,'Countdown cancellation did not persist a full-pot refund')
    require(new[0]['receipts']==sorted([[fixture.names[i],'refund',100] for i in indices]) and balances(cancelled)==wallets and not cancelled['leases'] and not cancelled['checkpoints'],'Cancellation must refund every real account once')
    ready_start=len(net.received[0])
    for index in indices[1:]:net.command(index,b'\x2c\x01')
    wait_ready(net,indices,ready_start,fixture.names)
    offsets={i:len(net.received[i]) for i in indices}
    net.command(0,b'\x2e');active,battle=load_battle(net,fixture,hashes,indices,offsets)
    wager=next(w for w in active['wagers'] if w['match']==battle['match'])
    expected=[list(w) for w in wallets]
    for index in indices:expected[index][0]-=100
    require(wager['status']=='active' and wager['pot']==count*100 and balances(active)==expected and battle['wager_active'],'Shared active wager did not retain all stakes')
    require(battle['turn_seconds']==40 and battle['sides']==(count if mode==0 else 2),'Wager turn duration or team configuration differs')
    losers=[1] if count==2 else [1,3]
    for index in losers:net.command(index,b'\x2a\x01')
    settled=wait_state(fixture,hashes,lambda s:any(w['match']==battle['match'] and w['status']=='settled' for w in s['wagers']))
    winners=[i for i in indices if i not in losers]
    for index in winners:expected[index][0]+=count*100//len(winners)
    receipt=next(w for w in settled['wagers'] if w['match']==battle['match'])
    require(balances(settled)==expected and receipt['receipts']==sorted([[fixture.names[i],'lose' if i in losers else 'win',0 if i in losers else count*100//len(winners)] for i in indices]),'Forfeit did not distribute the pot once to eligible winners')
    require(progression(settled)==progression(before),'Wager changed XP, skills, ranks or player rating')
    after=exit_results(net,fixture,hashes,indices)
    for index in winners:net.command(index,b'\x2a\x01')
    replay=fixture.status(hashes)
    require(balances(replay)==expected and next(w for w in replay['wagers'] if w['match']==battle['match'])==receipt and progression(replay)==progression(before),'Repeated native finish changed wager payout or progression')
    report['wager'+str(count)]=dict(mode=mode,players=count,stake=100,pot=count*100,countdown_cancel_refund=True,forfeit_payout=True,once_only_receipts=True,xp_skills_rank_unchanged=True)
    return after


def run(fixture,args,report,hashes):
    before=fixture.status(hashes)
    require(before['game_connections']==0 and not any(before['idle'].values()) and not before['leases'],'Other players or retained battles present; abort matchmaking QA')
    resumed=getattr(args,'resume_owned',False);cases=getattr(args,'case',None) or ['survival4','wager2','wager4']
    if resumed:report['resume_owned_wallets']=validate_resumed_state(before,fixture.names)
    else:require(all(r['name'] is None and not r['pets'] and r['wallet'] is None for r in before['states']),'Fresh empty accounts required; use explicit owned resume without resetting characters')
    report['requested_cases']=cases;report['resumed_owned_characters']=resumed
    net=FourNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        # Native one-use handoffs expire after ten seconds. Create each primary
        # character immediately after its login, using the four-account guard.
        for index in range(4):net.attach(index,net.begin(index),fresh=not resumed,expected_wallet=before['states'][index]['wallet'] if resumed else None)
        created=fixture.status(hashes)
        require(all(len(r['pets'])==1 for r in created['states']) and balances(created)==(balances(before) if resumed else [[3000,0]]*4),'Ordinary creation/login changed lawful owned wallets')
        for case in cases:
            case_before=fixture.status(hashes)
            if case=='survival4':verify_survival(net,fixture,hashes,report)
            elif case=='wager2':verify_wager(net,fixture,hashes,report,2,0)
            elif case=='wager4':verify_wager(net,fixture,hashes,report,4,1)
            else:raise ValueError('Unknown bounded QA case')
            case_after=fixture.status(hashes)
            report.setdefault('case_preservation',{})[case]=preserve(case_before,case_after)
    finally:
        # Failed owned QA must release a waiting room or a loading/active scene
        # through the same ordinary Leave packet. Never administratively reset it.
        for index in tuple(net.peers):
            try:net.command(index,b'\x2a\x01')
            except Exception:pass
        net.close();report['tls_channels']=[c.metadata() for c in net.connections]
        # Capture foreign-row preservation even when a native assertion failed.
        # A retained owned scene remains a reported cleanup limitation, never a
        # reason to reset the SQLite or lose the first failure's evidence.
        try:
            final=wait_state(fixture,hashes,lambda s:s['game_connections']==0)
            report['preservation']=dict(integrity='ok',foreign_account_rows=preserve(before,final))
            report['cleanup']=dict(game_connections=final['game_connections'],owned_leases=len(final['leases']),retained=final['idle'])
        except Exception as error:report['preservation_error_type']=type(error).__name__
    after=wait_state(fixture,hashes,lambda s:s['game_connections']==0 and not any(s['idle'].values()) and not s['leases'])
    report.update(source_sha256=hashes,preservation=dict(integrity='ok',foreign_account_rows=preserve(before,after)),disconnected_game_connections=0,passed=True)


def load_fixtures(paths):
    require(len(paths) in (1,2),'Use one fresh four-account fixture or two Stage7 pair fixtures')
    fixtures=[Stage7Fixture.load(path) for path in paths] if len(paths)==2 else [FreshSurroundingsQA.load_private(paths[0])]
    return FourFixture(fixtures)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,action='append',required=True)
    parser.add_argument('--resume-owned',action='store_true',help='Reuse only original level-one primary characters with receipt-explained wallets; never reset them')
    parser.add_argument('--case',choices=('survival4','wager2','wager4'),action='append',help='Run selected cases; default is all three')
    parser.add_argument('--deployment',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--deployed-only',action='store_true',help='Validate reviewed remote sources on every snapshot while local development continues')
    parser.add_argument('--host',default='185.184.42.88');parser.add_argument('--server-name',default='ti-reborn.com')
    parser.add_argument('--login-port',type=int,default=29512);parser.add_argument('--session-port',type=int,default=29513)
    parser.add_argument('--loopback-session-port',type=int,default=28513);parser.add_argument('--ca-file',type=Path)
    args=parser.parse_args(argv)
    if args.output.exists():parser.error('Preserve existing evidence; choose a fresh output')
    if any(not 1024<=p<=65535 for p in (args.login_port,args.session_port,args.loopback_session_port)):parser.error('Invalid port')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),kind='four ordinary accounts; authoritative gameplay over verified native TLS',
        limitations=['automated protocol validation; no graphical clients started','forfeit finishes exercise payout; no weapon damage or perk training attempted','no production restart, database fault injection or account reset'])
    try:
        fixture=load_fixtures(args.fixture);require(fixture.host==args.host,'Fixtures belong to another host')
        report['local_source_check']=not args.deployed_only
        run(fixture,args,report,deployment_hashes(args.deployment,deployed_only=args.deployed_only))
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__
        report['error_locations']=[dict(file=Path(frame.filename).name,line=frame.lineno) for frame in traceback.extract_tb(error.__traceback__)]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,graphical_clients_started=0)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
