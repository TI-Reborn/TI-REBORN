"""Four fresh owned accounts verify hosted legacy lobbies through verified TLS.

Backs up the remote database before creating QA accounts, proves ownership
before changing those QA fighters, uses native C82C/29 gameplay, then checks
pre-existing account rows. No graphical clients are launched. Credentials stay
in the existing ignored QA fixture directory, never in public evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from tools.verify_game_tls_hosted import (TlsNetworkQA, AuditedTlsSocket, tls_context,
                                         login_preface, require)
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP
from tio.protocol.wagers import decode_room_list, encode_join
from tio.protocol.battle_members import decode_battle_members


class LobbyTlsQA(TlsNetworkQA):
    def connect(self, port, *, label):
        patterns = [value.encode(encoding) for value in self.fixture.names + self.fixture.passwords
                    for encoding in ('utf-8', 'utf-16-le')]
        connection = AuditedTlsSocket((self.host, port), self.hostname, self.context, patterns=patterns)
        connection.channel['channel'] = label; self.connections.append(connection)
        return connection

    def begin(self, index):
        from test_server_deployment import Peer
        from tio.protocol.transport import (decode_initial_challenge, expected_reply_fields,
            InitialReply, encode_initial_reply, decode_initial_completion)
        from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, transform_auth_value
        from tio.protocol.server_list import ServerListRequest, encode_server_list_request, decode_server_list
        from tio.protocol.server_login import ServerLoginRequest, encode_server_login_request
        connection = self.connect(self.login_port, label='login')
        connection.sendall(login_preface(self.local_session_port)); peer = Peer(connection)
        fields = expected_reply_fields(decode_initial_challenge(peer.receive()))
        peer.send(encode_initial_reply(InitialReply(*fields, 0, bytes(3))))
        token = decode_initial_completion(peer.receive()).unknown_u32_01
        connection.capture_next_write = True
        peer.send(encode_basic_login_request(BasicLoginRequest(self.fixture.names[index].encode(),
            self.fixture.passwords[index].encode(), transform_auth_value(token))))
        require(peer.receive() == b'\x04\0', 'Owned QA TLS login failed')
        peer.send(encode_server_list_request(ServerListRequest(0, 0, b'')))
        entries = decode_server_list(peer.receive()).entries
        require(len(entries) == 1, 'Expected one hosted backend')
        entry = entries[0]
        require(entry.address_octets == socket.inet_aton('127.0.0.1')
                and entry.unknown_u16_01 == self.local_session_port, 'TLS route advertisement differs')
        require(entry.unknown_u16_02 == len(self.peers) + 1,
                'Another account connected; shared QA matchmaking stopped')
        peer.send(encode_server_login_request(ServerLoginRequest(1, bytes(8))))
        require(peer.receive() == b'\x08\0', 'TLS handoff preparation failed')
        connection.close(); return fields[1], token

    def listing(self, index):
        replies = self.command(index, b'\xba\x01')
        self.expect(index, replies, b'\xc8\x2c')
        wire = next(p for p in reversed(replies) if p.startswith(b'\xc8\x2c'))
        return decode_room_list(wire)

    def expect(self, index, replies, prefix):
        # The session's direct watchdog acknowledgement may precede packets
        # queued by the shared arena. Await the actual native reply separately.
        if not any(p.startswith(prefix) for p in replies):
            replies.append(self.peers[index].until(prefix, max_packets=4096))
        return replies

    def own_room(self, index, captain, *, predicate=lambda room: True):
        name = self.fixture.names[captain].encode()
        deadline = time.monotonic() + 20
        while True:
            for record in self.listing(index):
                if record.creator_name.startswith(name + b' \xb7 ') and predicate(record):
                    return record
            require(time.monotonic() < deadline, 'Expected authoritative lobby state did not arrive')
            time.sleep(.1)

    def absent(self, index, identity):
        deadline = time.monotonic() + 20
        while any(r.identity == identity for r in self.listing(index)):
            require(time.monotonic() < deadline, 'Closed lobby remained visible')
            time.sleep(.1)

    def create(self, captain, mode):
        replies = self.command(captain, bytes((0xba, 3, mode, 1)))
        self.expect(captain, replies, b'\x25')
        require(any(p.startswith(b'\x25') for p in replies), 'Native room creation did not return members')
        return self.own_room(captain, captain, predicate=lambda r: r.mode == mode and r.members == 1)

    def join(self, index, room, *, denied=False):
        replies = self.command(index, encode_join(room.identity))
        return self.expect(index, replies, b'\xf0\x8a\x01\0\0' if denied else b'\x25')


FIXTURE = OWNERSHIP + r'''
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.locations import LocationStore,center
from tio.level_progression import FLOORS
stage=data['stage'];assert stage in (1,2)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE')
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN ('+','.join('?' for _ in names)+')',names).fetchone()
 for index,name in enumerate(names):
  pet=decode_pet_info(db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(name,)).fetchone()[0],human_equipment=True)
  level=4 if index==1 or stage==1 and index==3 else 1
  fields={**pet.fields,'0x8c4aef':level,'0x8c4b05':FLOORS[level-1],'0x8c4a07':1000,'0x8c4ab1':1000,'0x8c44a6':1}
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(replace(pet,fields=fields)),name))
  LocationStore._save(db,name,3,*center(3))
  if index==1:
   fields.update({'0x8c43eb':2,'0x8c4489':b'Owned QA reserve','0x8c4aef':1,'0x8c4b05':0,'0x8c44a6':0})
   db.execute('INSERT OR REPLACE INTO owned_pets VALUES(?,?,?,?,?)',(name,2,1,encode_pet_info(replace(pet,fields=fields)),encode_item_list(2,())))
print(json.dumps(dict(stage=stage,owned_accounts=len(names))))
'''

SAVED_SELECTION = OWNERSHIP + r'''
from tio.protocol.pet_info import decode_pet_info
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 result=[]
 for name in names:
  result.append([(i,decode_pet_info(p,human_equipment=bool(h)).fields['0x8c44a6']) for i,h,p in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(name,))])
 assert result==[[(1,1)],[(1,1),(2,0)],[(1,1)],[(1,1)]],result
print(json.dumps(dict(saved_selection=result)))
'''

# This proof accepts only timer-owned SC lot lifecycle events. `automatic` on a
# history row records an automatic *bid*, while timer created/closed rows use 0.
# Every other pre-existing row must compare exactly, including opaque saves.
PRESERVATION = OWNERSHIP + r'''
from collections import Counter
import hashlib,subprocess
from tio.sc_auction import policy,prize
from tio.protocol.item_list import encode_item_list
for path,expected in data['source_sha256'].items():
 assert path in ('tio/sc_auction.py','config/sc_auction.json')
 assert hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()==expected
dbpath=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
baselines=[folder/'reservation.sqlite3']
if data.get('predeploy_backup'):
 baseline=pathlib.Path(data['predeploy_backup']).resolve()
 assert baseline.parent==pathlib.Path('/root') and baseline.name.startswith('tio-before-gameplay-completion-')
 baselines.append(baseline/'reservation.sqlite3')
offers={r['key']:r for r in policy()['offers']}
results=[]
with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 own_matches={m for m, in db.execute('SELECT DISTINCT match_id FROM battle_rewards WHERE account IN ('+','.join('?' for _ in names)+')',names)}
 for match in own_matches:
  assert {a for a, in db.execute('SELECT account FROM battle_rewards WHERE match_id=?',(match,))}==set(names)
 assert data['shared_match'] in own_matches
 for baseline in baselines:
  with sqlite3.connect('file:'+str(baseline)+'?mode=ro',uri=True) as old:
   tables={t for t, in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   assert tables=={t for t, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   checked={};own_added={};system_events=[];changed_lots=[];new_lots=[]
   old_history=list(old.execute('SELECT * FROM sc_auction_history'))
   history=list(db.execute('SELECT * FROM sc_auction_history'))
   assert not (Counter(old_history)-Counter(history)), 'Previous SC audit row changed'
   added_history=list((Counter(history)-Counter(old_history)).elements())
   oldmax=max((r[0] for r in old_history),default=0)
   old_lots={r[0]:r for r in old.execute('SELECT * FROM sc_auction_lots')}
   lots={r[0]:r for r in db.execute('SELECT * FROM sc_auction_lots')}
   lotcols=[r[1] for r in db.execute('PRAGMA table_info(sc_auction_lots)')]
   for event in added_history:
    identity,lot,account,action,amount,occurred,automatic=event
    assert identity>oldmax and account=='' and action in ('created','closed') and automatic==0
    row=dict(zip(lotcols,lots[lot]))
    assert row['bidder'] is None and row['bids']==0 and row['message'] is None and row['expires_at'] is None
    assert row['price']==row['start_price'] and row['state'] in ('active','unsold')
    if action=='created':
     assert lot not in old_lots and amount==row['start_price'] and occurred==row['started']
    else:
     assert row['state']=='unsold' and amount==row['price'] and occurred>=row['ends']
    assert len([r for r in history if r[1]==lot and r[3]==action])==1
    system_events.append(dict(id=identity,lot=lot,action=action,amount=amount,occurred=occurred,account_empty=True,automatic_bid_flag=automatic))
   for identity,before in old_lots.items():
    assert identity in lots, 'Previous SC lot removed'
    after=lots[identity]
    if after!=before:
     b=dict(zip(lotcols,before));a=dict(zip(lotcols,after))
     assert b['state']=='active' and a['state']=='unsold' and b['bidder'] is None and b['bids']==0
     assert {key for key in lotcols if b[key]!=a[key]}=={'state'}
     assert any(e['lot']==identity and e['action']=='closed' for e in system_events)
     changed_lots.append(dict(id=identity,from_state='active',to_state='unsold',all_other_fields_preserved=True))
   generations={key:max((r[2] for r in old_lots.values() if r[1]==key),default=0) for key in offers}
   for identity in sorted(set(lots)-set(old_lots)):
    row=dict(zip(lotcols,lots[identity]));offer=offers[row['offer_key']]
    generations[offer['key']]+=1
    assert row['generation']==generations[offer['key']]
    for field,config in (('currency','currency'),('start_price','start_price'),('fee','bid_fee'),('step','price_step'),('duration','duration'),('extension','extension')):
     assert row[field]==offer[config]
    assert row['automatic']==int(offer['automatic']) and row['ends']==row['started']+offer['duration']
    assert row['item_packet']==encode_item_list(0,(prize(offer),))
    assert any(e['lot']==identity and e['action']=='created' for e in system_events)
    new_lots.append(dict(id=identity,offer_key=offer['key'],generation=row['generation'],started=row['started'],ends=row['ends'],configuration_matched=True))
   for table in sorted(tables-{'sqlite_sequence'}):
    quoted='"'+table.replace('"','""')+'"'
    schema=old.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()[0]
    assert schema==db.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()[0]
    cols=[r[1] for r in old.execute('PRAGMA table_info('+quoted+')')]
    before=list(old.execute('SELECT * FROM '+quoted));after=list(db.execute('SELECT * FROM '+quoted))
    owned=[]
    for row in after:
     fields=dict(zip(cols,row))
     if any(fields.get(c) in names for c in ('account','login')):
      owned.append(row)
     elif table=='reward_pairs' and fields['first_account'] in names and fields['second_account'] in names:
      assert fields['match_id'] in own_matches
      owned.append(row)
     elif table=='world_city_matches' and fields['match_id'] in own_matches:
      assert fields['town']==3
      owned.append(row)
    retained=list((Counter(after)-Counter(owned)).elements())
    if table=='sc_auction_history':
     retained=list((Counter(retained)-Counter(added_history)).elements())
    elif table=='sc_auction_lots':
     retained=[old_lots[r[0]] for r in retained if r[0] in old_lots]
    assert Counter(before)==Counter(retained), 'Pre-existing rows changed in '+table
    checked[table]=dict(rows=len(before),sha256=hashlib.sha256('\n'.join(sorted(map(repr,before))).encode()).hexdigest(),unchanged=(table!='sc_auction_lots' or not changed_lots))
    if owned:own_added[table]=len(owned)
   oldseq=dict(old.execute('SELECT name,seq FROM sqlite_sequence'));seq=dict(db.execute('SELECT name,seq FROM sqlite_sequence'))
   assert not (set(oldseq)-set(seq))
   for table,previous in oldseq.items():
    assert seq[table]>=previous
    if seq[table]!=previous:assert table in own_added or table in ('sc_auction_history','sc_auction_lots')
   assert {t for t in seq if t not in oldseq}<=set(own_added)
   assert checked['accounts']['rows']==204 and checked['wallets']['rows']==202
   results.append(dict(backup=str(baseline),tables_checked=len(checked),schemas_preserved=True,existing_rows=checked,qa_owned_rows=own_added,
    timer_auction_events=system_events,timer_lots_changed=changed_lots,timer_lots_created=new_lots,
    previous_sc_history_rows_preserved=len(old_history),sequence_counters_valid=True))
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN ('+','.join('?' for _ in names)+')',names).fetchone()
 assert not db.execute('SELECT 1 FROM battle_checkpoints').fetchone()
 assert not db.execute('SELECT 1 FROM battle_settlement_jobs').fetchone()
 connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).splitlines())
 assert connections==0
 print(json.dumps(dict(passed=True,integrity='ok',accounts_before=204,accounts_after=208,original_accounts_exactly_preserved=204,
  existing_wallets_exactly_preserved=202,qa_accounts=names,qa_matches=sorted(own_matches),established_game_connections=connections,
  live_checkpoints=0,settlement_jobs=0,baselines=results,source_sha256=data['source_sha256'],remote_mutations=0,
  timer_event_proof='SCAuctionStore._tick unsold closure and tick replenishment; automatic flag distinguishes autobids, timer lifecycle rows use 0')))
'''


def preservation(fixture, *, shared_match, predeploy_backup=None):
    source_sha256 = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                     for path in ('tio/sc_auction.py', 'config/sc_auction.json')}
    return fixture.remote(PRESERVATION, {**fixture.ownership_payload(),
                          'shared_match': shared_match, 'predeploy_backup': predeploy_backup,
                          'source_sha256': source_sha256})


def complete_report(args, report):
    require(args.fixture is not None, 'A proven existing fixture is required for read-only completion')
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    raw = args.complete_report.read_bytes()
    previous = json.loads(raw)
    require(previous['accounts'] == fixture.names and len(previous['checks']) == 2
            and len(previous['observations']) == 9, 'Completed gameplay evidence differs')
    shared = previous['shared_battle']
    require(shared['humans'] == 4 and shared['bots'] == 0 and shared['scene_received_by_all'],
            'Four-account authoritative scene evidence incomplete')
    require(previous['selection_after_battle'] == previous['selection_after_reserve'],
            'Saved selection evidence differs')
    for channel in previous['tls_channels']:
        require(channel['verified_chain_and_name'] and not channel['application_sent_before_verified_tls']
                and all(not v['plaintext_secret_found'] and v['valid_tls_record_stream']
                        for v in channel['wire'].values()), 'TLS evidence incomplete')
    report.update(previous)
    report['passed'] = False
    report.pop('error_type', None)
    report.pop('assertion', None)
    report['gameplay_evidence_report'] = dict(path=str(args.complete_report), sha256=hashlib.sha256(raw).hexdigest(),
                                            original_passed=previous['passed'], completion_failure='Strict generic preservation rejected timer auction append')
    first_phase = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011/hosted-lobbies-tls-retry1.json'
    first_raw = first_phase.read_bytes(); first = json.loads(first_raw)
    require(first['accounts'] == fixture.names and first['checks'][0] == previous['checks'][0],
            'First-phase evidence differs')
    report['first_phase_evidence_report'] = dict(path=str(first_phase), sha256=hashlib.sha256(first_raw).hexdigest(),
                                               original_passed=first['passed'])
    report['preservation'] = preservation(fixture, shared_match=shared['match'], predeploy_backup=args.predeploy_backup)
    report['completion_observed_utc'] = datetime.now(timezone.utc).isoformat()
    report['completion_mode'] = 'Read-only preservation and aggregation; gameplay was not repeated'
    report['remote_mutations_during_completion'] = 0
    report['passed'] = True


def assert_room(room, *, mode, members, state):
    capacity = 2 if mode == 1 else 4
    require((room.mode, room.capacity, room.members, room.creator_level, room.level_delta,
             room.stake) == (mode, capacity, members, 2, 1, 0), 'Hosted lobby field projection differs')
    text = room.creator_name.decode('cp1251')
    require(f'{state} {members}/{capacity}' in text, 'Hosted availability/occupancy text differs')
    require(room.status == (2 if state == 'поиск' else 0), 'Hosted native status differs')
    return dict(identity=room.identity, mode=mode, members=members, capacity=capacity,
                state=state, text=text, level_range=[1, 3], status=room.status)


def observe(network, index, captain, *, mode, members, state):
    capacity = 2 if mode == 1 else 4
    record = network.own_room(index, captain, predicate=lambda r:
        (r.mode, r.capacity, r.members, r.status) == (mode, capacity, members, 2 if state == 'поиск' else 0)
        and f'{state} {members}/{capacity}' in r.creator_name.decode('cp1251'))
    return assert_room(record, mode=mode, members=members, state=state)


def error_text(replies):
    packet = next(p for p in replies if p.startswith(b'\xf0\x8a\x01\0\0'))
    require(int.from_bytes(packet[9:13], 'little') == 5, 'Expected native UTF16 rejection')
    return packet[13:-2].decode('utf-16-le')


def wait_closed(fixture):
    deadline = time.monotonic() + 15
    while fixture.readiness()['established_connections']:
        require(time.monotonic() < deadline, 'QA sockets did not release hosted sessions')
        time.sleep(.25)


def execute(args, report):
    fixture = (FreshSurroundingsQA.load_private(args.fixture) if args.fixture
               else FreshSurroundingsQA.create(args.host, 4, key=str(args.key)))
    require(fixture.host == args.host and len(fixture.names) == 4, 'Owned QA fixture target differs')
    report.update(accounts=fixture.names, backup=fixture.backup, accounts_created=0 if args.fixture else 4,
                  private_fixture=fixture.credential_path)
    fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload())
    network = None
    channels = []

    def open_network():
        net = LobbyTlsQA(fixture, args.host, args.server_name, args.login_port, args.session_port,
                         tls_context(), local_session_port=28513)
        try:
            for index in range(4):
                net.enter(index)
            return net
        except BaseException:
            net.close()
            raise

    def close_network():
        nonlocal network
        if network is not None:
            channels.extend({**c.channel, 'wire': c.audit.metadata()} for c in network.connections)
            network.close(); network = None
        wait_closed(fixture)

    try:
        if args.resume_report:
            previous = json.loads(args.resume_report.read_text(encoding='utf-8'))
            require(previous['accounts'] == fixture.names and len(previous['checks']) >= 1
                    and 'selection_after_reserve' in previous, 'Previous owned first-phase proof differs')
            report['checks'] = previous['checks'][:1]
            report['observations'] = previous['observations'][:6]
            report['selection_after_reserve'] = previous['selection_after_reserve']
            report['prior_first_phase_report'] = str(args.resume_report)
        else:
            network = open_network(); close_network()
            report['initialized'] = fixture.initialization()
            fixture.remote(FIXTURE, {**fixture.ownership_payload(), 'stage': 1})
            network = open_network()
        for mode in (() if args.resume_report else (1, 4)):
            room = network.create(0, mode)
            report['observations'].append(observe(network, 2, 0, mode=mode, members=1, state='свободно'))
            denied = error_text(network.join(3, room, denied=True))
            require('1' in denied and '3' in denied and 'бойц' in denied, 'No-level1–3 account was not rejected')
            require(any(p.startswith(b'\x25') for p in network.join(1, room)), 'Owned reserve was not admitted through native29')
            state = 'занято' if mode == 1 else 'свободно'
            report['observations'].append(observe(network, 2, 0, mode=mode, members=2, state=state))
            if mode == 1:
                require('заполнена' in error_text(network.join(2, room, denied=True)), 'A full lobby accepted another account')
            network.command(1, b'\x2a\x01')
            report['observations'].append(observe(network, 2, 0, mode=mode, members=1, state='свободно'))
            network.command(0, b'\x2a\x01')
            network.absent(2, room.identity)
        if not args.resume_report:
            report['checks'].append('Both modes: separate viewer discovers free lobby; account without level1–3 rejected; reserve level1 joins despite selected level4; leave frees a slot; captain closes lobby')
        close_network()
        report['selection_after_reserve'] = fixture.remote(SAVED_SELECTION, fixture.ownership_payload())
        fixture.remote(FIXTURE, {**fixture.ownership_payload(), 'stage': 2})
        network = open_network()
        wall = network.create(0, 4)
        for index in (1, 2, 3):
            require(any(p.startswith(b'\x25') for p in network.join(index, wall)), 'Wall native join failed')
        report['observations'].append(observe(network, 3, 0, mode=4, members=4, state='занято'))
        network.command(3, b'\x2a\x01')
        report['observations'].append(observe(network, 3, 0, mode=4, members=3, state='свободно'))
        network.command(0, b'\x2a\x01')
        network.absent(3, wall.identity)
        first = network.create(0, 1); network.join(1, first)
        second = network.create(2, 1); network.join(3, second)
        network.command(1, b'\x2c\x01'); network.command(3, b'\x2c\x01')
        starts = {i: len(network.received[i]) for i in range(4)}
        network.command(0, b'\x2e')
        report['observations'].append(observe(network, 2, 0, mode=1, members=2, state='поиск'))
        network.command(2, b'\x2e')
        grounds = []
        for index in range(4):
            network.ping(network.peers[index])
            packets = network.received[index][starts[index]:]
            if b'\x41' not in packets:
                network.peers[index].until(b'\x41', max_packets=4096)
                packets = network.received[index][starts[index]:]
            require(b'\x41' in packets, 'One account did not receive the battle scene')
            grounds.append(next(p for p in packets if p.startswith(b'\x35')))
            members = decode_battle_members(next(p for p in reversed(packets) if p.startswith(b'\x25')))[2]
            require({m.name.decode() for m in members} == set(fixture.names), 'Shared Team battle did not contain exactly four owned accounts')
            network.command(index, b'\x36')
        require(len(set(grounds)) == 1, 'Accounts received different authoritative BattleGround bytes')
        snapshot = fixture.snapshot(fixture.names)
        require(snapshot['bots'] == 0 and {a['account'] for a in snapshot['actors']} == set(fixture.names), 'QA Team battlefield included bots or unrelated accounts')
        report['shared_battle'] = dict(match=snapshot['match'], humans=4, bots=0,
                                      ground_sha256=snapshot['ground_sha256'], scene_received_by_all=True)
        report['checks'].append('Wall occupancy4/4 and release3/4; searching Team remains visible; two teams of two real accounts share one authoritative scene with no bots')
        for index in range(4):
            network.command(index, b'\x2a\x01')
        close_network()
        report['selection_after_battle'] = fixture.remote(SAVED_SELECTION, fixture.ownership_payload())
        report['preservation'] = preservation(fixture, shared_match=report['shared_battle']['match'],
                                              predeploy_backup=args.predeploy_backup)
        report['passed'] = True
    finally:
        if network is not None:
            for index, peer in network.peers.items():
                try:
                    network.command(index, b'\x2a\x01')
                except (OSError, EOFError, AssertionError, ValueError):
                    pass
            close_network()
        report['tls_channels'] = channels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='185.184.42.88')
    parser.add_argument('--server-name', default='ti-reborn.com')
    parser.add_argument('--login-port', type=int, default=29512)
    parser.add_argument('--session-port', type=int, default=29513)
    parser.add_argument('--key', type=Path, default=Path.home() / '.ssh/tio_server')
    parser.add_argument('--fixture', type=Path, help='Reuse a proven owned ignored QA fixture')
    parser.add_argument('--resume-report', type=Path, help='Reuse completed first-phase evidence for the same owned fixture')
    parser.add_argument('--complete-report', type=Path, help='Complete existing gameplay proof with read-only preservation; no gameplay or fixture writes')
    parser.add_argument('--predeploy-backup', help='Existing hosting backup directory for an additional predeployment preservation proof')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011/hosted-lobbies-tls.json')
    args = parser.parse_args()
    report = dict(passed=False, kind=__doc__, observed_utc=datetime.now(timezone.utc).isoformat(),
                  checks=[], observations=[], graphical_clients_started=0,
                  limitations=['Automated TLS protocol clients; rendered real game clients not tested',
                               'Four human Team combatants; Wall lobby occupancy tested without starting Wall combat'])
    try:
        if args.complete_report:
            complete_report(args, report)
        else:
            execute(args, report)
    except BaseException as error:
        # Protocol fixture exceptions can include secret frames; retain type only.
        report['error_type'] = type(error).__name__
        if isinstance(error, AssertionError):
            report['assertion'] = str(error)[:240]
        print('FAIL: ' + type(error).__name__)
        return 1
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PASS: fresh four-account hosted TLS lobbies, joins, reserve admission and shared Team scene')
    return 0


if __name__ == '__main__':
    sys.exit(main())
