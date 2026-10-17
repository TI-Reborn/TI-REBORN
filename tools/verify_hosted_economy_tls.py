"""Owned two-account economy acceptance over verified gameplay TLS.

Provisioning is explicit and backs up the live SQLite database first. Passwords
travel only in SSH stdin and TLS; no account/stat/inventory fixture writes are
performed. This is automated native-protocol QA, not graphical-client evidence.
Importing or --self-test never contacts production.
"""
from collections import deque
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from tools.verify_game_tls_hosted import TlsNetworkQA, tls_context
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP, PROVISION, SNAPSHOT, require
from tio.appearance import encode_request as appearance_request
from tio.city_catalogs import CityCatalogs
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.battle_attack import AttackRequest, decode_attack_result, encode_attack_request
from tio.protocol.battle_ground import decode_battle_ground
from tio.protocol.battle_move import BattleMove, decode_battle_move, encode_move_request
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.character_create import CharacterCreateRequest, encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.hire import encode_hire_request
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
from tio.ranks import kill_points, level_cap, rank_id
from tio.level_progression import BattleExperience

PRIVATE = (Path(os.environ['LOCALAPPDATA'])/'TIO-emulator/economy-qa' if os.name == 'nt'
           else ROOT/'reports/economy/private')
PINNED_SOURCES = ('tio/wallets.py', 'tio/reward_policy.py', 'tio/battle_rewards.py',
                  'tio/ranks.py', 'tio/level_progression.py', 'config/city_catalogs.json',
                  'server/team_arena.py', 'tools/loopback_exchange.py', 'config/level_progression.json',
                  'tio/durability.py', 'tio/battle_recovery.py', 'tio/shop.py', 'tio/hiring.py',
                  'tio/achievements.py', 'config/ranks.json', 'config/recovery.json', 'config/achievements.json')
# Reuse the established ownership proof format, but create NO character, gear,
# health, level or wallet via administration. Both TLS ports are guarded too.
PROVISION_ECONOMY = PROVISION.replace(
    '( sport = :28512 or sport = :28513 )',
    '( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'
).replace('create(name,password,character=name)', 'create(name,password)').replace(
    "folder=pathlib.Path(tempfile.mkdtemp", "with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as live:\n assert not live.execute(\"SELECT 1 FROM sqlite_master WHERE name='battle_checkpoint_members'\").fetchone() or live.execute('SELECT count(*) FROM battle_checkpoint_members').fetchone()[0]==0,'Retained battle present; abort before writes'\nfolder=pathlib.Path(tempfile.mkdtemp").replace(
    "data=json.load(sys.stdin);prefix=data['prefix'];pairs=data['pairs']",
    "data=json.load(sys.stdin);prefix=data['prefix'];pairs=data['pairs']\nimport hashlib\nfor p,digest in data['source_hashes'].items():assert hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==digest,'Deploy reviewed economy candidate before provisioning'")

PAIR_READY = OWNERSHIP + r'''
import subprocess
lines=subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines()
tls_sessions=subprocess.check_output(['ss','-Htn','state','established','( sport = :29513 )'],text=True).splitlines()
assert len(tls_sessions)==2 and len(lines)==2,'Only the two owned TLS sessions may be online before matchmaking'
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert db.execute('SELECT count(*) FROM battle_checkpoint_members').fetchone()[0]==0,'Retained battle present; abort before matchmaking'
print(json.dumps(dict(owned_tls_sessions=2,other_established_game_connections=0,retained_members=0)))
'''

SNAPSHOT_BODY = r'''
import hashlib
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_list import decode_item_list
from tio.ranks import signed
def rows(table,fields,n):
 if table not in tables:return []
 return [dict(zip(fields,r)) for r in db.execute('SELECT '+','.join(fields)+' FROM '+table+' WHERE account=? ORDER BY '+','.join(fields[:2]),(n,))]
def snapshot(n):
 wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(n,)).fetchone() if 'wallets' in tables else None
 pets=[]
 if 'owned_pets' in tables:
  for owner,human,raw,inv in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(n,)):
   f=decode_pet_info(raw,human_equipment=bool(human)).fields
   pets.append(dict(id=owner,level=f['0x8c4aef'],xp=f['0x8c4b05'],hp=f['0x8c4ab1'],max_hp=f['0x8c4a07'],rank_points=signed(f['0x8c4bd0']),rank=f['0x8c4bbc'],debt=f['0x8c4be3'],
    items=[dict(id=i.instance_id,template=i.template_id,count=i.count,equipped=i.equipped,slot=i.client_slot,durability=list(i.unknown_words)) for i in decode_item_list(inv)[1]]))
 receipts=rows('battle_rewards',['match_id','result','credits','gross','rental_tax','calculation'],n)
 for r in receipts:r['calculation']=json.loads(r['calculation'])
 awards=rows('achievement_awards',['id','body','notified'],n)
 delivered=rows('achievement_prizes',['id','position','delivered'],n)
 achievement_credits=0
 for award in awards:
  body=json.loads(award.pop('body'));amount=body.get('temporary_credits',0)
  award.update(temporary_credits=amount,metric=body['metric'])
  # Temporary credits follow the originally configured non-credit prizes.
  if any(p['id']==award['id'] and p['position']==len(body['prizes']) and p['delivered'] for p in delivered):achievement_credits+=amount
 return dict(wallet=list(wallet) if wallet else None,pets=pets,receipts=receipts,
  xp_audit=rows('experience_battle_audit',['match_id','pet_id','xp_before','gain','xp_after','level_before','level_after'],n),
  rank_audit=rows('rank_battle_audit',['match_id','pet_id','before_points','earned','restored','penalty','after_points'],n),
  repairs=rows('item_repairs',['id','pet_id','item_id','kit_id','spent','max_loss'],n),
  achievement_credits=achievement_credits,awards=awards,
  checkpoints=db.execute('SELECT count(*) FROM battle_checkpoint_members WHERE account=?',(n,)).fetchone()[0] if 'battle_checkpoint_members' in tables else 0,
  characters=db.execute('SELECT count(*) FROM characters WHERE account=?',(n,)).fetchone()[0])
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 states=[snapshot(n) for n in names]
 source_hashes={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in data.get('sources',[])}
 print(json.dumps(dict(states=states,source_hashes=source_hashes,integrity=db.execute('PRAGMA integrity_check').fetchone()[0])))
'''
# All production SQL is read-only and restricted to the ownership-proven pair.
ECONOMY_SNAPSHOT = OWNERSHIP + SNAPSHOT_BODY


class EconomyFixture(FreshSurroundingsQA):
    def preflight_pair(self):
        return self.remote(PAIR_READY,self.ownership_payload())

    def snapshot_economy(self, *, sources=False):
        return self.remote(ECONOMY_SNAPSHOT, {**self.ownership_payload(),
                           'sources': list(PINNED_SOURCES) if sources else []})

    @staticmethod
    def prepare_private_directory():
        require(not PRIVATE.is_symlink(), 'Private directory cannot be a symlink')
        PRIVATE.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            from tools.offsite_backup_windows import _protect_directory
            _protect_directory(PRIVATE)
        else:
            PRIVATE.chmod(0o700)
        (PRIVATE / '.gitignore').write_text('*\n', encoding='utf-8')
        return PRIVATE

    def save_private(self):
        self.prepare_private_directory()
        path = PRIVATE / (self.prefix + '.json')
        require(not path.exists(), 'Never overwrite an existing owned fixture')
        path.write_text(json.dumps(dict(version=1, host=self.host, prefix=self.prefix,
            names=self.names, passwords=self.passwords, backup=self.backup, key=self.key))+'\n', encoding='utf-8')
        if os.name != 'nt':
            path.chmod(0o600)
        self.credential_path = str(path)
        return path

    @classmethod
    def load_private(cls, path):
        path = Path(path).resolve()
        require(path.parent == PRIVATE.resolve() and not path.is_symlink(), 'Use the owned economy private directory')
        require((PRIVATE / '.gitignore').read_text().strip() == '*', 'Private credentials must be ignored')
        data = json.loads(path.read_text(encoding='utf-8'))
        require(data.pop('version') == 1, 'Invalid fixture format')
        fixture = cls(**data, credential_path=str(path))
        import re
        require(re.fullmatch(r'qs[0-9a-f]{8}', fixture.prefix) and
            fixture.names == [fixture.prefix+'a', fixture.prefix+'b'] and len(fixture.passwords) == 2,
            'Expected exactly the two proven-owned QA accounts')
        return fixture


class EconomyNetwork(TlsNetworkQA):
    def attach(self, index, *, fresh=False):
        peer = self.handoff(self.begin(index))
        self.received[index] = []
        receive = peer.receive
        def record():
            packet = receive()
            self.received[index].append(packet)
            return packet
        peer.receive = record
        self.peers[index] = peer
        records = self.case.character_screen(peer)
        if fresh:
            require(records == (), 'Fresh account already has a character')
            sex = index+1
            peer.send(encode_character_create(CharacterCreateRequest(self.fixture.names[index].encode(), 0, (sex,0,0,0))))
            require(peer.receive() == b'\x12\x05', 'Normal character creation failed')
            require(decode_character_list(peer.receive())[0].resource_type == sex, 'Character resource mismatch')
            peer.send(bytes.fromhex('1701000000'))
            require(peer.receive() == b'\x12\x05' and peer.receive()[0] == 0x10, 'Missing first appearance menu')
            initial = bytes((sex,5 if sex == 1 else 12,1 if sex == 1 else 0,3,0,0))
            peer.send(appearance_request(1, initial))
            peer.until(b'\x10')
        else:
            require(len(records) == 1 and records[0].name_bytes == self.fixture.names[index].encode(), 'Saved character missing')
        peer.send(bytes.fromhex('1701000000'))
        require(peer.receive()[0] == 0x18, 'City selection failed')
        peer.send(b'\x19')
        peer.until(b'\x66')
        self.ping(peer)
        return peer


def only_pet(state):
    require(len(state['pets']) == 1 and state['pets'][0]['id'] == 1, 'Unexpected starter roster')
    return state['pets'][0]


def item(state, template):
    values = [i for i in state['pets'][0]['items'] if i['template'] == template]
    require(len(values) == 1, 'Expected exactly one owned item or merged stack')
    return values[0]


def summary(raw):
    require(raw[0] == 0x4c and len(raw) >= 29, 'Malformed battle result')
    values = dict(zip(('kills','losses','damage_dealt','damage_received','credits','rental_tax'), struct.unpack_from('<6I', raw, 4)))
    values['result'] = raw[3]
    count = raw[28]
    require(count == 1 and len(raw) == 29 + count*109, 'Expected exactly one native result XP recipient')
    values['native_xp_recipients'] = count
    values['xp_actor'] = struct.unpack_from('<I',raw,29)[0]
    values['xp_gain'] = struct.unpack_from('<I', raw, 33)[0]
    return values


def path_to_adjacent(start, target, blocked, width, height):
    goals = {(target[0]+dx,target[1]+dy) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1))}
    if start in goals:
        return ()
    queue, previous = deque([start]), {start:None}
    while queue:
        x,y = queue.popleft()
        for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if cell in previous or cell in blocked or cell == target or not (0<=cell[0]<width and 0<=cell[1]<height):
                continue
            previous[cell] = x,y
            if cell in goals:
                route = []
                while cell != start:
                    route.append(cell)
                    cell = previous[cell]
                return tuple(reversed(route))
            queue.append(cell)
    raise AssertionError('Own multiplayer opponent cannot be reached')


def fight(net, fixture):
    fixture.preflight_pair()
    starts = [len(net.received[i]) for i in (0,1)]
    for i in (0,1):
        net.peers[i].send(b'\xba\x03\0\1')
    for i in (0,1):
        net.peers[i].until(b'\x41', max_packets=4096)
    state = fixture.snapshot(fixture.names)
    require(state['bots'] == 0 and len(state['actors']) == 2 and
        {a['account'] for a in state['actors']} == set(fixture.names), 'QA match must contain exactly the two owned humans')
    grounds = [next(p for p in net.received[i][starts[i]:] if p[0] == 0x35) for i in (0,1)]
    require(grounds[0] == grounds[1], 'Authoritative map differs between accounts')
    ground = decode_battle_ground(grounds[0])
    ordered = [next(a for a in state['actors'] if a['account'] == n) for n in fixture.names]
    ids = [a['id'] for a in ordered]
    positions = [(a['x'],a['y']) for a in ordered]
    offsets, done, turn, dealt, shots = starts[:], [None,None], [False,False], [0,0], [0,0]
    def refresh(i):
        for p in net.received[i][offsets[i]:]:
            if p[0] == 0x38: turn[i] = True
            if p[0] == 0x39: turn[i] = False
            if p[0] == 0x3d:
                move = decode_battle_move(p)
                if move.actor_id in ids and move.path:
                    positions[ids.index(move.actor_id)] = move.path[-1]
            if p[0] == 0x4b:
                attack = decode_attack_result(p)
                if attack.actor_id == ids[i]:
                    shots[i] += 1
                    dealt[i] += sum(h.damage for h in attack.hits if h.actor_id == ids[1-i])
            if p[0] == 0x4c:
                done[i], turn[i] = p, False
        offsets[i] = len(net.received[i])
    for i in (0,1):
        net.peers[i].send(b'\x36')
    for cycle in range(80):
        for i in sorted((0,1), key=lambda i: ids[i]):
            peer = net.peers[i]
            refresh(i)
            while not turn[i] and done[i] is None:
                peer.receive()
                refresh(i)
            if done[i] is not None:
                continue
            for _ in range(30):
                route = path_to_adjacent(positions[i], positions[1-i], set(map(tuple,state['blocked'])), ground.width, ground.height)
                if i == 1 and dealt[i] > 0:
                    break
                # After A's first successful shot, give B an ordinary turn to
                # establish active participation before shooting to victory.
                if i == 0 and dealt[0] > 0 and dealt[1] == 0:
                    break
                packet = encode_move_request(BattleMove(ids[i],route[:5])) if route else encode_attack_request(AttackRequest(ids[i],*positions[1-i]))
                packets = net.command(i, packet)
                refresh(i)
                if not turn[i] or done[i] is not None or any(p[0] == 0xf0 for p in packets):
                    break
            if turn[i]:
                net.command(i, encode_end_turn())
                refresh(i)
        if all(done):
            break
    require(all(done) and all(d>0 for d in dealt), 'Both owned humans must deal damage and finish normally')
    summaries = [summary(p) for p in done]
    require([s['result'] for s in summaries] == [1,0], 'Unexpected PvP outcome')
    witnesses = []
    for i in (0,1):
        packets = net.received[i][starts[i]:]
        witnesses.append([dict(actor=struct.unpack_from('<I',p,1)[0],xp=struct.unpack_from('<I',p,13)[0])
                          for p in packets if len(p)==18 and p[0]==0x4e and p[5:13]==struct.pack('<II',1,2)])
    return dict(match=state['match'],summaries=summaries,accepted_shots=shots,actor_ids=ids,xp_absolute_updates=witnesses,
                map_sha256=state['ground_sha256'],bots=0,humans=2)


def receipt_for(state, match):
    values = [r for r in state['receipts'] if r['match_id'] == match]
    require(len(values) == 1, 'Expected one immutable receipt for own account/match')
    return values[0]


def wait_city_awards(net, fixture):
    deadline = time.monotonic()+6
    while True:
        for i in (0,1): net.ping(net.peers[i])
        states = fixture.snapshot_economy()['states']
        if all(all(a['notified'] for a in s['awards']) for s in states): return states
        require(time.monotonic()<deadline, 'Normal city achievement delivery did not finish')
        time.sleep(.1)


def verify_settlement(before, after, battle, ordinal):
    factor = Fraction(1 if ordinal <= 3 else '1/2')
    records = []
    xp_policy = BattleExperience()
    for i in (0,1):
        old, new = before[i], after[i]
        p, enemy = only_pet(old), only_pet(before[1-i])
        result = battle['summaries'][i]
        receipt = receipt_for(new,battle['match'])
        audit = receipt['calculation']
        require(audit['version'] == 2 and Fraction(audit['repeat']) == factor and
            Fraction(audit['progression_repeat']) == factor and Fraction(audit['experience_factor']) == factor,
            'Repeated pair credit/XP factors differ from policy')
        require(Fraction(audit['rank_positive_factor']) == factor*(2 if i == 0 else 1), 'Rank repeat factor mismatch')
        gross = int(Fraction(audit['base'])*Fraction(audit['outcome'])*Fraction(audit['strength'])*
            audit['participation']*Fraction(audit['repeat'])*Fraction(100+audit['rank_percent'],100)*audit['city_profit'])
        require(gross == receipt['gross'] == result['credits'] and receipt['rental_tax'] == result['rental_tax'] == 0,
            'Actual native result differs from exact authoritative credit formula')
        require(new['wallet'][0]-old['wallet'][0] == gross and new['wallet'][1] == old['wallet'][1] == 0,
            'Settlement wallet delta must be only its ordinary battle credit')
        own_strength = (p['level'],rank_id(p['rank_points']),Fraction(0))
        enemy_strength = (enemy['level'],rank_id(enemy['rank_points']),Fraction(0))
        # No healing, armor, enhancement or other actors are used in this QA.
        raw_xp = int((4*min(result['damage_dealt'],enemy['max_hp']) +
                      2*min(result['damage_received'],p['max_hp']))*xp_policy.factor(own_strength,enemy_strength))
        expected_xp = int(raw_xp*factor)
        xp = [a for a in new['xp_audit'] if a['match_id'] == battle['match']]
        require(len(xp) == 1 and xp[0]['gain'] == expected_xp and
                result['xp_gain'] == expected_xp and result['xp_actor'] == battle['actor_ids'][i] and
                xp[0]['xp_before'] == p['xp'] and xp[0]['xp_after'] == p['xp']+expected_xp,
                'Actual damage XP differs from independently derived strength/repeat calculation')
        require(dict(actor=battle['actor_ids'][i],xp=p['xp']+expected_xp) in battle['xp_absolute_updates'][i],
                'Own native4E absoluteXP update missing or assigned to the other account')
        rank = [a for a in new['rank_audit'] if a['match_id'] == battle['match']]
        expected_rank = min(int(kill_points(p['level'],p['rank_points'],enemy['level'],enemy['rank_points'])*2*factor),
                            max(0,level_cap(only_pet(new)['level'])-p['rank_points'])) if i == 0 else 0
        require(len(rank) == 1 and rank[0]['earned'] == expected_rank and rank[0]['penalty'] == (0 if i == 0 else 5),
                'Positive rank must discount; ordinary PvP death penalty must remain5')
        old_ammo, new_ammo = item(old,3), item(new,3)
        old_gun, new_gun = item(old,301), item(new,301)
        require(old_ammo['count']-new_ammo['count'] == battle['accepted_shots'][i] and
                old_gun['durability'][0]-new_gun['durability'][0] == 3*battle['accepted_shots'][i],
                'Accepted Beretta shots must consume one round and wear3 each')
        records.append(dict(result=result,credit_calculation=audit,xp= xp[0],rank=rank[0],
                            ammo_spent=battle['accepted_shots'][i],weapon_wear=3*battle['accepted_shots'][i]))
    return records


def run_economy(fixture, args, report):
    initial = fixture.snapshot_economy(sources=True)
    require(initial['integrity'] == 'ok', 'SQLite integrity failed')
    require(initial['source_hashes'] == {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PINNED_SOURCES},
            'Hosted economic code/config differ from the reviewed local candidate')
    resume = getattr(args,'resume_onboarding_report',None)
    if resume:
        resume = Path(resume).resolve()
        require(resume.parent == (ROOT/'reports/stage4-economy').resolve(), 'Only the recorded own Stage4 report may resume onboarding')
        prior = json.loads(resume.read_text(encoding='utf-8'))
        require(prior['accounts'] == fixture.names and prior['source_hashes'] == initial['source_hashes'] and
                prior['passed'] is False and not prior['battles'], 'Resume requires the recorded failure before any battle')
        require(all(s['wallet'] == [3000,0] for s in prior['onboarding']) and
                all(s['wallet'] == [3050,0] for s in prior['first_purchase']), 'Initial ordinary wallet/purchase evidence is missing')
        for s in initial['states']:
            p = only_pet(s)
            require(s['characters'] == 1 and not s['receipts'] and not s['xp_audit'] and not s['rank_audit'] and not s['repairs'] and
                    s['checkpoints'] == 0 and s['wallet'] == [3050,0] and s['achievement_credits'] == 100 and
                    p['level'] == 1 and p['xp'] == p['rank_points'] == 0 and p['hp'] == p['max_hp'] == 100 and
                    len(p['items']) == 2 and item(s,3)['count'] == 50 and item(s,301)['durability'] == [300,300,300] and
                    item(s,301)['count'] == 1 and item(s,301)['equipped'] == 1 and item(s,301)['slot'] == 16 and
                    {a['id'] for a in s['awards']} == {38}, 'Resume refuses altered, progressed or partially played accounts')
        report['continued_onboarding_evidence'] = dict(path=str(resume),sha256=hashlib.sha256(resume.read_bytes()).hexdigest())
    else:
        require(all(s['characters'] == 0 and not s['pets'] and not s['receipts'] and s['checkpoints'] == 0 for s in initial['states']),
                'Use fresh admin-created accounts; no existing character/save is altered')
    net = EconomyNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,
                         tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    report['source_hashes'] = initial['source_hashes']
    report['accounts'] = fixture.names
    report['pre_provision_backup'] = fixture.backup
    report['private_fixture'] = fixture.credential_path
    try:
        for i in (0,1): net.attach(i,fresh=not resume)
        if resume:
            report['onboarding'] = prior['onboarding']
            bought = initial['states']
        else:
            initialized = fixture.snapshot_economy()['states']
            require(all(s['wallet'] == [3000,0] and only_pet(s)['level'] == 1 and only_pet(s)['xp'] == 0 and
                        item(s,301)['durability'] == [300,300,300] and not any(i['template'] == 3 for i in only_pet(s)['items']) for s in initialized),
                    'Normal fresh onboarding must have3000credits/0Gold/freeBeretta/noammo')
            report['onboarding'] = initialized
            for i in (0,1):
                packets = net.command(i,encode_shop_purchase(ShopPurchase(1,0,3,1)))
                assets = [decode_asset_count(p).credits for p in packets if p[:2] == b'\xc8\x39']
                require(assets and assets[0] == 2950, 'Ammo debit must be50 before separate achievement payout')
                net.command(i,encode_item_action(ItemAction(1,item(initialized[i],301)['id'],4)))
            bought = wait_city_awards(net,fixture)
        report['first_purchase'] = bought
        require(all(s['wallet'] == [3050,0] and s['achievement_credits'] == 100 and item(s,3)['count'] == 50 and
                    item(s,301)['equipped'] for s in bought), 'First shop achievement must be separately paid100 exactly once')
        report['first_purchase'] = bought
        report['battles'], report['treatment'] = [], []
        for ordinal in range(1,5):
            before = fixture.snapshot_economy()['states']
            battle = fight(net,fixture)
            settled = fixture.snapshot_economy()['states']
            battle['verified_accounts'] = verify_settlement(before,settled,battle,ordinal)
            battle['ordinal'] = ordinal
            report['battles'].append(battle)
            # Native Finish precedes its treatment submission. Preserve actual
            # global battle actor IDs and exercise the retained account mapping.
            for i in (0,1): net.command(i,b'\x2a\1')
            costs = []
            for i in (0,1):
                pre = fixture.snapshot_economy()['states'][i]
                net.command(i,b'\x7c\1'+struct.pack('<I',battle['actor_ids'][i]))
                post = fixture.snapshot_economy()['states'][i]
                cost = pre['wallet'][0]-post['wallet'][0]
                require(0 <= cost <= 2*(only_pet(pre)['max_hp']-only_pet(pre)['hp']) and
                        cost%2 == 0 and only_pet(post)['hp'] == only_pet(post)['max_hp'], 'Native treatment tariff/health mismatch')
                # Free ten-second recovery may occur between two SSH snapshots.
                costs.append(dict(charged=cost,max_from_pre_snapshot=2*(only_pet(pre)['max_hp']-only_pet(pre)['hp']),
                                  free_recovery_can_reduce_cost=True))
            require(costs[1]['charged'] > 0, 'PvP loser must pay a real treatment expense')
            report['treatment'].append(costs)
            dismissed = fixture.snapshot_economy()['states']
            for i in (0,1):
                packets = net.command(i,b'\x2a\1')
                require(not any(p[0] == 0x4c for p in packets), 'Repeated dismissal emitted another reward result')
            replay = fixture.snapshot_economy()['states']
            require(all(a['wallet'] == b['wallet'] and a['receipts'] == b['receipts'] and
                        a['xp_audit'] == b['xp_audit'] and a['rank_audit'] == b['rank_audit'] and
                        a['achievement_credits'] == b['achievement_credits'] for a,b in zip(dismissed,replay)), 'Replay changed money, progression or achievement delivery')
            for i in (0,1): net.command(i,b'\x50\3')
            wait_city_awards(net,fixture)
        # Buy a real450-credit repair kit, repair worn gear via native C2/03;
        # verify its independent resource/max-loss receipt, not just a UI reply.
        for i in (0,1):
            before_kit = fixture.snapshot_economy()['states'][i]
            net.command(i,encode_shop_purchase(ShopPurchase(1,0,14,1)))
            pre = fixture.snapshot_economy()['states'][i]
            require(before_kit['wallet'][0]-pre['wallet'][0] == 450, 'A real repair kit must debit450credits')
            gun, kit = item(pre,301), item(pre,17)
            deficit = gun['durability'][1]-gun['durability'][0]
            restored = min(kit['durability'][0],(100*deficit+51)//103)
            loss = deficit-restored if restored == (100*deficit+51)//103 else (restored*3+50)//100
            net.command(i,b'\xc2\3'+struct.pack('<II',1,gun['id']))
            post = fixture.snapshot_economy()['states'][i]
            require(item(post,301)['durability'][:2] == [gun['durability'][0]+restored,gun['durability'][1]-loss] and
                    item(post,17)['durability'][0] == kit['durability'][0]-restored and
                    post['repairs'][-1]['spent'] == restored and post['repairs'][-1]['max_loss'] == loss,
                    'Ordinary repair resource and3%max-loss mismatch')
        report['after_repairs'] = wait_city_awards(net,fixture)
        # Zero Gold must reject a priced native premium purchase, unchanged.
        catalogs = CityCatalogs(ROOT/'config/city_catalogs.json')
        offer = catalogs.premium_items[0]
        for i in (0,1):
            pre = fixture.snapshot_economy()['states'][i]
            packets = net.command(i,b'\x78'+struct.pack('<5IQI',1,offer.offer_id,1,1,0,catalogs.price_revision,0))
            post = fixture.snapshot_economy()['states'][i]
            require(any(p[0] == 0xf0 for p in packets) and pre['wallet'] == post['wallet'] and
                    pre['pets'] == post['pets'], '0Gold purchase must reject before debit or granting gear')
        # Normal100-credit hire; stale offer repeat must not grant a free second actor.
        for i in (0,1):
            pre = fixture.snapshot_economy()['states'][i]
            net.command(i,encode_hire_request(2))
            post = fixture.snapshot_economy()['states'][i]
            require(pre['wallet'][0]-post['wallet'][0] == 100 and len(post['pets']) == 2 and not post['pets'][1]['items'],
                    'Ordinary hire must cost100 and begin with empty equipment')
            net.command(i,encode_hire_request(2))
            duplicate = fixture.snapshot_economy()['states'][i]
            require(post['wallet'] == duplicate['wallet'] and post['pets'] == duplicate['pets'], 'Stale hire offer granted or debited twice')
        before_relog = fixture.snapshot_economy()['states']
        net.close()
        time.sleep(1)
        for i in (0,1): net.attach(i)
        after_relog = fixture.snapshot_economy()['states']
        require(before_relog == after_relog and all(s['checkpoints'] == 0 and len(s['receipts']) == 4 and
                len(s['xp_audit']) == 4 and len(s['rank_audit']) == 4 for s in after_relog),
                'Relog changed persisted economy or left a battle checkpoint')
        report['final_states'] = after_relog
        report['passed'] = True
        report['checks'] = ['fresh normal onboarding3000/0', '50-round pack debit50 + first shop achievement100 separately',
            'four shared PvP matches, two real accounts, authoritative damage, no bots',
            'actual native credits/XP/rank receipts; repeat factors1,1,1,1/2; death penalty unchanged',
            'ammo/weapon wear, paid treatment,450-credit kit repair,0Gold denial,100-credit hire/stale offer',
            'result replay/achievement delivery and relog persistence; no owned checkpoint remains']
    finally:
        # Ordinary leave retires an interrupted own match; never delete DB state.
        if not report.get('passed'):
            for i in tuple(net.peers):
                try: net.command(i,b'\x2a\1')
                except Exception: pass
        report['tls_channels'] = [c.channel for c in net.connections]
        net.close()


def self_test(args, report):
    from test_multi_account import MultiAccountTests
    from server.config import TLSConfig
    case = MultiAccountTests()
    case.setUp()
    cert_dir = args.test_cert_dir
    ports = []
    for _ in (0,1):
        with socket.socket() as conn:
            conn.bind(('127.0.0.1',0)); ports.append(conn.getsockname()[1])
    case.config = replace(case.config,tls=TLSConfig(True,*ports,cert_dir/'valid-chain.pem',cert_dir/'valid-key.pem'))
    names = ['qsecofixturea','qsecofixtureb']
    for name in names: case.accounts.create(name,'local-only-economy-password123')
    def remote(code,payload):
        source = code[len(OWNERSHIP):] if code.startswith(OWNERSHIP) else code
        source = source.replace('/var/lib/tio-server/reservation.sqlite3',case.config.database.as_posix())
        source = source.replace('names=json.load(sys.stdin)', 'names=data["names"]')
        source = 'import json,pathlib,sqlite3,sys\ndata=json.load(sys.stdin);names=data["names"]\n'+source
        output = io.StringIO()
        with patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),redirect_stdout(output):
            exec(compile(source,'<owned local read-only economy snapshot>','exec'),{})
        return json.loads(output.getvalue())
    fixture = EconomyFixture('127.0.0.1','local',names,['local-only-economy-password123']*2,'local-only')
    fixture.remote = remote
    fixture.snapshot = lambda selected: remote(SNAPSHOT,dict(names=selected))
    fixture.preflight_pair = lambda: require(set(case.server.multi.active_accounts) == set(names), 'Only local own pair may match')
    local_args = SimpleNamespace(host='127.0.0.1',server_name='localhost',login_port=ports[0],session_port=ports[1],
                                ca_file=cert_dir/'ca.pem',loopback_session_port=31003)
    try:
        case.start()
        run_economy(fixture,local_args,report)
        report['remote_contacted'] = False
    finally: case.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='185.184.42.88')
    parser.add_argument('--server-name',default='ti-reborn.com')
    parser.add_argument('--login-port',type=int,default=29512)
    parser.add_argument('--session-port',type=int,default=29513)
    parser.add_argument('--loopback-session-port',type=int,default=28513)
    parser.add_argument('--ca-file',type=Path)
    parser.add_argument('--provision-owned',action='store_true',help='Explicitly create only two fresh own QA accounts; stdin passwords, consistent backup first')
    parser.add_argument('--fixture',type=Path)
    parser.add_argument('--resume-onboarding-report',type=Path,help='Only recover the recorded initialized owned pair before its first match; strict no-progression guard')
    parser.add_argument('--key',default=str(Path.home()/'.ssh/tio_server'))
    parser.add_argument('--self-test',action='store_true',help='Temporary localhost real TLS backend; never production')
    parser.add_argument('--test-cert-dir',type=Path,default=ROOT/'tests/fixtures/game_tls')
    parser.add_argument('--output',type=Path,default=ROOT/'reports/economy/hosted-economy-verification.json')
    args = parser.parse_args()
    if not args.self_test and bool(args.provision_owned) == bool(args.fixture): parser.error('Choose --provision-owned or --fixture')
    if args.resume_onboarding_report and not args.fixture: parser.error('Resume requires the same owned --fixture')
    if any(not 1024<=p<=65535 for p in (args.login_port,args.session_port,args.loopback_session_port)): parser.error('Invalid port')
    report = dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),
        kind='automated native protocol over verified TLS; no graphical game clients',checks=[],
        limitations=['one public origin; not a physical two-user graphical economy acceptance',
                     'XP uses accepted damage, not a fixed universal battles-per-level claim',
                     'read-only treatment snapshots can straddle the ordinary10-second free recovery tick'])
    try:
        if args.self_test:
            self_test(args,report)
        else:
            if args.provision_owned:
                EconomyFixture.prepare_private_directory()
                prefix = 'qs'+secrets.token_hex(4)
                fixture = EconomyFixture(args.host,prefix,[prefix+'a',prefix+'b'],[secrets.token_urlsafe(24) for _ in (0,1)],'',args.key)
                provision = fixture.remote(PROVISION_ECONOMY,dict(prefix=prefix,pairs=list(zip(fixture.names,fixture.passwords)),
                    source_hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PINNED_SOURCES}))
                report['provision'] = provision
                fixture.backup = provision['backup']
                fixture.save_private()
            else: fixture = EconomyFixture.load_private(args.fixture)
            require(fixture.host == args.host, 'Fixture belongs to a different host')
            run_economy(fixture,args,report)
    except BaseException as error:
        # Exceptions may contain native fields or credentials; persist only type
        # and our source line numbers. Never captured SSH stderr or raw packets.
        report['error_type'] = type(error).__name__
        import traceback
        report['error_locations'] = [dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),graphical_clients_started=0,credentials_printed=False)))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
