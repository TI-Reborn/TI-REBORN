"""Two retained owned accounts exercise deployed mine hunters over strict TLS.

Only normal login, mine admission, movement, EndTurn, Loaded and Leave packets
are sent. Remote SQL is read-only; actor positions/HP/AP/memory are never edited.
The access fixtures are previously audited synthetic Lv4, not earned progress.
This is automated protocol evidence, with no graphical clients started.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from tools import verify_hosted_mine_completion as retained
from tools import verify_hosted_gameplay_modes as modes
from tio.protocol.battle_attack import decode_attack_result
from tio.protocol.battle_move import BattleMove, decode_battle_move, encode_move_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.battle_turn import encode_end_turn

REQUIRED = {'tio/mining_ai.py', 'tio/training_bot.py', 'tools/mining_scene.py'}


def _extend_snapshot():
    code = retained.SNAPSHOT
    old = 'sides=len(field.living_sides()),width=field.width,height=field.height,'
    new = old + '''
    round=field.mining.round,move_cost=field.step_cost,
    bot_actor_ids=sorted(getattr(field,'individual_bot_sight',())),
    hunter_state={str(i):s for i,s in getattr(field,'mine_hunter_state',{}).items()},
    patrol_progress=getattr(field,'patrol_progress',{}),
    retired_actors=[dict(id=a.actor_id,owner=a.owner_id,hp=a.health,ap=a.action_points)
                    for units in battle.get('mine_retired',{}).values() for a in units.values()],
    raider_exits=list(field.mining.layout.raider_exits),
    exit_deadlines=field.mining.exit_blocked_until_by_owner,
    turn_remaining=max(0,turn[2]-__import__('time').monotonic()) if turn else 0,
'''
    assert code.count(old) == 1
    code = code.replace(old, new)
    old = 'ap=a.action_points,blocked='
    new = '''ap=a.action_points,sight=a.sight_radius,
    turn_ap=field._turn_points[a.actor_id],generation=field._ability_turns[a.actor_id],
    attack_ap=a.weapons[0].attack_ap if a.weapons else None,blocked='''
    assert code.count(old) == 1
    code = code.replace(old, new)
    old = 'source_sha256=sources,game_connections=connections)))'
    new = '''source_sha256=sources,game_connections=connections,
 service=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ActiveState','-p','ExecMainStatus'],text=True).strip())))'''
    assert code.count(old) == 1
    code = code.replace(old, new)
    compile(code, 'read-only-hunter-snapshot', 'exec')
    return code


SNAPSHOT = _extend_snapshot()


class Fixture(retained.Fixture):
    def status(self, source):
        return self.fixtures[0].remote(SNAPSHOT, dict(
            names=self.names, fixtures=[f.ownership_payload() for f in self.fixtures],
            source_hashes=source))


def progress(stage, **values):
    print(json.dumps(dict(stage=stage, **values)), flush=True)


def deployment_hashes(paths):
    result = {}
    for path in paths:
        data = json.loads(path.read_text(encoding='utf-8'))
        modes.require(data.get('source_parity') is True, 'Successful deployed source proof required')
        values = data.get('source_sha256', {})
        modes.require(isinstance(values, dict) and 1 <= len(values) <= 256,
                      'Bounded deployed source hashes required')
        for name, digest in values.items():
            modes.require(isinstance(name, str) and
                          re.fullmatch(r'(?:tio|server|tools|config|evidence)/[A-Za-z0-9_./-]+', name)
                          and '..' not in Path(name).parts, 'Unsafe source proof path')
            modes.require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest),
                          'Invalid deployed source hash')
            if name in result:
                modes.require(result[name] == digest, 'Conflicting deployed source proofs')
            result[name] = digest
    modes.require(REQUIRED <= result.keys(), 'Mine hunter deployment proof is incomplete')
    return result


def route(battle, actor, goals):
    """Shortest cardinal route through the current authoritative free cells."""
    start = (actor['x'], actor['y'])
    blocked = {tuple(p) for p in battle['blocked']}
    blocked.update((a['x'], a['y']) for a in battle['actors']
                   if a['hp'] and a['id'] != actor['id'])
    goals = {tuple(p) for p in goals} - blocked
    if start in goals:
        return ()
    previous = {start: None}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for cell in ((x - 1, y), (x, y - 1), (x, y + 1), (x + 1, y)):
            if (cell in previous or cell in blocked or
                    not (0 <= cell[0] < battle['width'] and 0 <= cell[1] < battle['height'])):
                continue
            previous[cell] = (x, y)
            if cell in goals:
                path = []
                while cell != start:
                    path.append(cell)
                    cell = previous[cell]
                return tuple(reversed(path))
            queue.append(cell)
    return None


def hunter_route(battle, actor):
    ids = set(battle['bot_actor_ids'])
    goals = []
    for npc in battle['actors']:
        if npc['id'] not in ids or not npc['hp']:
            continue
        x, y = npc['x'], npc['y']
        goals.extend(((x - 1, y), (x, y - 1), (x, y + 1), (x + 1, y)))
    return route(battle, actor, goals)


def owned_battle(state, names, *, expected=None, exact=True):
    modes.require(len(state['checkpoints']) == 1, 'Exactly one shared owned mine required')
    battle = state['checkpoints'][0]
    members = {m['account'] for m in battle['members']}
    modes.require(battle['kind'] == 'mine' and members <= set(names[:2]),
                  'Unrelated mine participant; stop owned verification')
    if exact:
        modes.require(members == set(names[:2]), 'Both authenticated accounts must share the mine')
    if expected is not None:
        modes.require(battle['match'] == expected, 'The authoritative mine was replaced')
    return battle


def actor_for(battle, account):
    owners = [m['owner'] for m in battle['members'] if m['account'] == account]
    return next((a for a in battle['actors'] if owners and a['owner'] == owners[0]), None)


def current_client(battle, names):
    account = next((m['account'] for m in battle['members'] if m['owner'] == battle['turn']), None)
    return names.index(account) if account in names[:2] else None


def human_signature(battle, names):
    ids = {a['id'] for name in names[:2] for a in [actor_for(battle, name)] if a}
    return [dict(a) for a in battle['actors'] if a['id'] in ids]


def read_events(net, cursors, bot_ids, human_ids):
    attacks, movements, ap = [], [], []
    sequence = []
    for index in (0, 1):
        packets = net.received.get(index, [])
        for packet in packets[cursors.get(index, 0):]:
            if packet[:1] == b'\x4b':
                result = decode_attack_result(packet)
                if result.actor_id in bot_ids:
                    sequence.append(dict(observer=index, actor=result.actor_id, kind='attack'))
                    attacks.append(dict(observer=index, actor=result.actor_id,
                        origin=list(result.origin), target=list(result.target),
                        hits=[dict(actor=h.actor_id, damage=h.damage, hp=h.left_hp)
                              for h in result.hits if h.actor_id in human_ids]))
            elif packet[:1] == b'\x3d':
                result = decode_battle_move(packet)
                if result.actor_id in bot_ids:
                    sequence.append(dict(observer=index, actor=result.actor_id, kind='move', steps=len(result.path)))
                    movements.append(dict(observer=index, actor=result.actor_id,
                                          path=[list(p) for p in result.path]))
            elif packet[:1] == b'\x4e' and len(packet) == 18:
                actor = int.from_bytes(packet[1:5], 'little')
                count = int.from_bytes(packet[5:9], 'little')
                kind = int.from_bytes(packet[9:13], 'little')
                value = int.from_bytes(packet[13:17], 'little')
                if actor in bot_ids and count == 1 and kind == 10:
                    ap.append(dict(observer=index, actor=actor, ap=value))
                    sequence.append(dict(observer=index, actor=actor, kind='ap', ap=value))
            elif packet[:1] == b'\x3b':
                identity = int.from_bytes(packet[1:5], 'little')
                if identity in bot_ids:
                    actor = decode_battle_soldier(packet, human_equipment=True)
                    sequence.append(dict(observer=index, actor=identity, kind='appearance',
                                         ap=actor.fields['0x8c571d']))
        cursors[index] = len(packets)
    return dict(attacks=attacks, movements=movements, ap_updates=ap, sequence=sequence)


def move(net, fixture, source, battle, index, path, report):
    actor = actor_for(battle, fixture.names[index])
    modes.require(actor is not None and actor['hp'], 'Living owned actor required for movement')
    count = min(len(path), actor['ap'] // battle['move_cost'], 255)
    if not count:
        return battle
    prefix = path[:count]
    replies = net.command(index, encode_move_request(BattleMove(actor['id'], prefix)))
    modes.require(any(decode_battle_move(p).actor_id == actor['id'] and
                      decode_battle_move(p).path == prefix
                      for p in replies if p[:1] == b'\x3d'), 'Accepted native movement reply missing')
    state = fixture.status(source)
    after = owned_battle(state, fixture.names, expected=battle['match'], exact=False)
    moved = actor_for(after, fixture.names[index])
    modes.require(moved is not None and (moved['x'], moved['y']) == prefix[-1],
                  'Native movement differs from authoritative position')
    modes.require(moved['ap'] == actor['ap'] - count * battle['move_cost'],
                  'Movement did not charge the authoritative AP cost')
    report.append(dict(actor=actor['id'], steps=count, origin=[actor['x'], actor['y']],
                       endpoint=list(prefix[-1]), ap_before=actor['ap'], ap_after=moved['ap']))
    return after


def wait_human(fixture, source, names, match, *, seconds=15):
    deadline = time.monotonic() + seconds
    while True:
        state = fixture.status(source)
        battle = owned_battle(state, names, expected=match, exact=False)
        if current_client(battle, names) is not None or battle['finished']:
            return state, battle
        modes.require(time.monotonic() < deadline, 'Mutant turn did not return to a human in time')
        time.sleep(.15)


def verify_npc_ap(before, after, events):
    """Validate consecutive visible action costs before the turn-final AP reset.

    Snapshots after EndTurn legitimately contain zero even with spare AP. Fog
    can omit a turn prefix or suffix, so this evidence never claims full turns.
    """
    prior = {a['id']: a for a in before['actors']}
    proofs = []
    for actor in after['actors']:
        if actor['id'] not in after['bot_actor_ids']:
            continue
        modes.require(0 <= actor['ap'] <= actor['turn_ap'], 'Mutant AP exceeds its configured budget')
        old = prior.get(actor['id'])
        if not old or actor['generation'] != old['generation'] + 1:
            continue
        observer_proofs = []
        for observer in (0, 1):
            last_ap = None
            pending = 0
            intervals = []
            terminal = []
            for event in events['sequence']:
                if event['observer'] != observer or event['actor'] != actor['id']:
                    continue
                kind = event['kind']
                if kind == 'move':
                    pending += event['steps'] * after['move_cost']
                elif kind == 'attack':
                    pending += actor['attack_ap']
                else:
                    points = event['ap']
                    modes.require(0 <= points <= actor['turn_ap'], 'Native mutant AP exceeds its configured budget')
                    if kind == 'appearance':
                        # The appearance snapshot establishes a fresh AP value
                        # after any hidden route prefix; preceding costs are unknown.
                        last_ap, pending = points, 0
                        continue
                    if last_ap is not None and pending and last_ap - points == pending:
                        intervals.append(dict(ap_before=last_ap, ap_after=points, charged=pending))
                    elif last_ap is not None and points == 0 and pending == 0 and last_ap:
                        terminal.append(dict(ap_before_terminal_zero=last_ap,
                            turn_end_discards_unused_ap=True,
                            exact_unused_ap_unproven_if_fog_suffix_missing=True))
                    last_ap, pending = points, 0
            if intervals:
                observer_proofs.append(dict(observer=observer,
                    consecutive_action_intervals=intervals, terminal_zero_updates=terminal,
                    coverage='visible consecutive actions; hidden prefix/suffix unproven',
                    full_turn_coverage=False))
        if observer_proofs:
            proofs.append(dict(actor=actor['id'], generation=actor['generation'],
                budget=actor['turn_ap'], turn_final_snapshot_ap=actor['ap'],
                turn_end_clears_unused_ap=True, full_turn_coverage=False, evidence=observer_proofs))
    return proofs


def reconnect(net, fixture, source, battle, grounds, report):
    index = 1 if current_client(battle, fixture.names) == 0 else 0
    modes.require(battle['turn_remaining'] > 12, 'Insufficient live turn time for stable reconnect evidence')
    before_memory = battle['hunter_state']
    before_actors = battle['actors']
    before_patrol = battle['patrol_progress']
    net.peers.pop(index).sock.close()
    time.sleep(.4)
    net.attach(index)
    net.command(index, b'\x36')
    net.sync((0, 1))
    state = fixture.status(source)
    after = owned_battle(state, fixture.names, expected=battle['match'])
    replay = [p for p in net.received[index] if p[:1] == b'\x35']
    modes.require(replay and replay[-1] == grounds[index], 'Reconnect changed the native scene')
    modes.require(after['hunter_state'] == before_memory and after['actors'] == before_actors
                  and after['patrol_progress'] == before_patrol and after['round'] == battle['round'],
                  'Reconnect reset or changed hunter state')
    active = {i: s for i, s in before_memory.items() if s.get('last_seen') is not None}
    report.update(account=index, same_match=True, same_native_ground=True,
                  same_hunter_state=True, same_patrol_progress=True,
                  same_actor_position_hp_ap=True, round=after['round'],
                  active_target_memory_observed=bool(active), hunter_state=before_memory,
                  active_target_memory=active,
                  limitation='Reconnect verifies recorded AI state; active pursuit memory is asserted only if present')
    return after


def cleanup(net, fixture, source, match, report):
    """Try ordinary exits; if unreachable, observe real disconnect expiry."""
    started = time.monotonic()
    try:
        for _ in range(24):
            state = fixture.status(source)
            if not state['checkpoints']:
                break
            battle = owned_battle(state, fixture.names, expected=match, exact=False)
            for index in tuple(net.peers):
                actor = actor_for(battle, fixture.names[index])
                if actor is None or not actor['hp']:
                    net.command(index, b'\x36')
                    continue
                exits = battle['lift'] if index == 0 else battle['raider_exits']
                deadline = battle['exit_deadlines'].get(str(actor['owner']), 0)
                if [actor['x'], actor['y']] in exits and battle['round'] >= deadline:
                    net.command(index, b'\x2a\1')
                    net.command(index, b'\x36')
            state = fixture.status(source)
            if not state['checkpoints']:
                break
            battle = owned_battle(state, fixture.names, expected=match, exact=False)
            index = current_client(battle, fixture.names)
            if index is None:
                if battle['finished']:
                    for i in tuple(net.peers):
                        net.command(i, b'\x2a\1'); net.command(i, b'\x36')
                    break
                _, battle = wait_human(fixture, source, fixture.names, match)
                index = current_client(battle, fixture.names)
            if index is None:
                break
            actor = actor_for(battle, fixture.names[index])
            if actor and actor['hp']:
                exits = battle['lift'] if index == 0 else battle['raider_exits']
                path = route(battle, actor, exits)
                if path:
                    battle = move(net, fixture, source, battle, index, path, report.setdefault('exit_movements', []))
                actor = actor_for(battle, fixture.names[index])
                deadline = battle['exit_deadlines'].get(str(actor['owner']), 0) if actor else 0
                if actor and [actor['x'], actor['y']] in exits and battle['round'] >= deadline:
                    net.command(index, b'\x2a\1')
                    net.command(index, b'\x36')
                    continue
            if current_client(battle, fixture.names) == index:
                net.command(index, encode_end_turn())
            net.sync(tuple(net.peers))
    except Exception as error:
        report['ordinary_exit_error'] = type(error).__name__
    finally:
        for index in tuple(net.peers):
            try:
                net.command(index, b'\xb0\x19')
            except Exception:
                pass
        net.close()
    report['sockets_closed_utc'] = datetime.now(timezone.utc).isoformat()
    disconnected = time.monotonic()
    expiry = disconnected + 210
    next_notice = disconnected
    while True:
        state = fixture.status(source)
        if state['game_connections'] == 0 and not any(state['idle'].values()):
            report.update(passed=True, game_connections=0, retained=state['idle'],
                          disconnect_wait_seconds=round(time.monotonic() - disconnected, 3),
                          total_seconds=round(time.monotonic() - started, 3))
            return state
        modes.require(time.monotonic() < expiry, 'Owned reconnect expiry cleanup deadline exceeded')
        if time.monotonic() >= next_notice:
            progress('cleanup_wait', seconds=round(time.monotonic() - disconnected), retained=state['idle'])
            next_notice = time.monotonic() + 20
        time.sleep(3)


def run(fixture, source, report, *, max_rounds=12):
    before = fixture.status(source)
    modes.require(before['game_connections'] == 0 and not any(before['idle'].values()),
                  'Server must be idle before owned hunter verification')
    net = retained.Network(fixture, '185.184.42.88', 'ti-reborn.com', 29512, 29513,
                           modes.tls_context(), local_session_port=28513)
    report.update(accounts=fixture.names[:2], source_sha256=source, service_before=before['service'],
                  ownership_checked=True, movements=[], rounds=[], npc_ap_proofs=[], reconnect={})
    match = None
    cursors = {0: 0, 1: 0}
    try:
        progress('login')
        for index in (0, 1):
            net.attach(index)
        modes.require(fixture.status(source)['game_connections'] == 2,
                      'Unexpected public game connection; stop owned admission')
        net.command(1, b'\xb0\x14\2')
        net.command(0, b'\xb0\x14\1')
        battle = owned_battle(fixture.status(source), fixture.names)
        match = battle['match']
        grounds = {}
        for index in (0, 1):
            net.command(index, b'\x36')
            packets = [p for p in net.received[index] if p[:1] == b'\x35']
            modes.require(packets, 'Shared native mine ground missing')
            grounds[index] = packets[-1]
        modes.require(grounds[0] == grounds[1], 'Authenticated clients received different mine maps')
        _, battle = wait_human(fixture, source, fixture.names, match)
        modes.require(len(battle['bot_actor_ids']) == 10 and len(battle['actors']) == 12,
                      'Expected two owned human actors and ten mutants')
        modes.require(all(a['sight'] == 6 for a in battle['actors'] if a['id'] in battle['bot_actor_ids']),
                      'Hosted mutant sight does not equal six')
        report['shared_mine'] = dict(match=match, humans=2, mutants=10,
            ground_sha256=hashlib.sha256(grounds[0]).hexdigest(), mutant_sight=6,
            human_actor_ids=[actor_for(battle, n)['id'] for n in fixture.names[:2]])
        human_ids = set(report['shared_mine']['human_actor_ids'])
        bot_ids = set(battle['bot_actor_ids'])
        progress('reconnect')
        battle = reconnect(net, fixture, source, battle, grounds, report['reconnect'])
        # Reattach replaced one observer's packet history. Combat evidence starts
        # after reconnect so packet coverage maps to the following real turns.
        cursors = {i: len(net.received[i]) for i in (0, 1)}
        first_round = battle['round']
        deadline = time.monotonic() + 480
        positive = False
        for action in range(max_rounds * 2 + 2):
            modes.require(time.monotonic() < deadline, 'Bounded hunter observation wall-clock limit reached')
            _, battle = wait_human(fixture, source, fixture.names, match)
            modes.require(battle['round'] - first_round < max_rounds,
                          'No verified mutant contact within twelve real global rounds')
            living = [i for i in (0, 1) if (a := actor_for(battle, fixture.names[i])) and a['hp']]
            modes.require(living, 'No living owned actor remains for bounded hunter observation')
            index = current_client(battle, fixture.names)
            modes.require(index is not None, 'Human turn required for owned approach')
            if index == (0 if 0 in living else 1):
                path = hunter_route(battle, actor_for(battle, fixture.names[index]))
                modes.require(path is not None, 'No ordinary connected route to a live mutant')
                battle = move(net, fixture, source, battle, index, path, report['movements'])
            pre_turn = battle
            net.command(index, encode_end_turn())
            _, battle = wait_human(fixture, source, fixture.names, match)
            net.sync((0, 1))
            events = read_events(net, cursors, bot_ids, human_ids)
            proofs = verify_npc_ap(pre_turn, battle, events)
            report['npc_ap_proofs'].extend(proofs)
            seen_memory = {i: s for i, s in battle['hunter_state'].items()
                           if s.get('target_id') in human_ids and s.get('last_seen') is not None}
            hp_before = {a['id']: a['hp'] for a in pre_turn['actors'] if a['id'] in human_ids}
            after_hp = {a['id']: a['hp'] for a in (*battle['actors'], *battle['retired_actors'])
                        if a['id'] in human_ids}
            damage = [dict(actor=i, hp_before=hp, hp_after=after_hp[i])
                      for i, hp in hp_before.items() if i in after_hp and after_hp[i] < hp]
            native_hits = [a for a in events['attacks'] if any(h['damage'] > 0 for h in a['hits'])]
            correlated = [d for d in damage if any(
                h['actor'] == d['actor'] and h['damage'] > 0 and h['hp'] == d['hp_after']
                for attack in native_hits for h in attack['hits'])]
            report['rounds'].append(dict(round=battle['round'], action=action,
                human_hp={str(a['id']): a['hp'] for a in battle['actors'] if a['id'] in human_ids},
                npc_positions=[dict(id=a['id'], x=a['x'], y=a['y'], ap=a['ap'], generation=a['generation'])
                               for a in battle['actors'] if a['id'] in bot_ids],
                memory=seen_memory, damage=damage, native_mutant_attacks=events['attacks']))
            progress('hunter_round', round=battle['round'], memories=len(seen_memory),
                     damage_events=len(damage), native_hits=len(native_hits), ap_proofs=len(proofs))
            if correlated and native_hits and report['npc_ap_proofs']:
                report['combat'] = dict(positive_mutant_damage=True, hp_changes=correlated,
                    native_attack_results=native_hits, persisted_hunter_memory=seen_memory,
                    active_target_memory_observed=bool(seen_memory),
                    active_memory_limit='A killed target clears pursuit memory; hosted active-memory observation is optional',
                    consecutive_visible_action_ap_costs_confirmed=True,
                    full_npc_turn_ap_coverage=False,
                    ap_limit='Turn-end zeros discard spare AP; fog-hidden actions have separate direct regression evidence')
                positive = True
                break
        modes.require(positive, 'No complete damage and AP proof in the bounded ordinary mine')
        report['verification_passed'] = True
    finally:
        progress('cleanup')
        if match is not None:
            final = cleanup(net, fixture, source, match, report.setdefault('cleanup', {}))
        else:
            net.close()
            final = modes.wait_state(fixture, source,
                lambda s: s['game_connections'] == 0 and not any(s['idle'].values()), seconds=8)
        report['tls_channels'] = [c.metadata() for c in net.connections]
        report['foreign_preservation'] = modes.preserve(before, final)
        modes.require(final['service'] == before['service'], 'Hosted game service changed during QA')
        report['service_unchanged'] = True
        modes.require(all(not d['plaintext_secret_found'] and d['valid_tls_record_stream']
                          for c in report['tls_channels'] for d in c['wire'].values()),
                      'Strict external TLS wire audit failed')
    report['passed'] = True


def self_test():
    battle = dict(width=5, height=5, blocked=[[2, 0], [2, 1], [2, 2], [2, 3]],
        actors=[dict(id=1, x=0, y=0, hp=115), dict(id=2, x=4, y=0, hp=115)],
        bot_actor_ids=[2])
    path = hunter_route(battle, battle['actors'][0])
    modes.require(path is not None and len(path) == 11 and path[-1] == (3, 0),
                  'Route did not traverse the only wall opening to an adjacent free cell')
    battle['blocked'].append([2, 4])
    modes.require(hunter_route(battle, battle['actors'][0]) is None,
                  'Disconnected geometry produced a route')
    before = dict(actors=[dict(id=2, generation=0)])
    after = dict(actors=[dict(id=2, generation=1, ap=0, turn_ap=20, attack_ap=5)], bot_actor_ids=[2], move_cost=1)
    events = dict(sequence=[dict(observer=0, actor=2, kind=k, **extra) for k, extra in (
        ('ap', {'ap': 20}), ('move', {'steps': 1}), ('ap', {'ap': 19}),
        ('attack', {}), ('ap', {'ap': 14}), ('ap', {'ap': 0}))])
    proof = verify_npc_ap(before, after, events)
    modes.require(len(proof) == 1 and len(proof[0]['evidence'][0]['consecutive_action_intervals']) == 2
                  and proof[0]['evidence'][0]['terminal_zero_updates'][0]['ap_before_terminal_zero'] == 14,
                  'Turn-end zero incorrectly rejected valid action costs with spare AP')
    return dict(passed=True, remote_actions=0, checks=['connected wall detour', 'unreachable mutant refusal',
                'ordered movement/attack AP and spare-AP turn reset'],
                snapshot_compiles=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, action='append')
    parser.add_argument('--deployment', type=Path, action='append')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--max-rounds', type=int, default=12, choices=range(1, 13))
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test())); return 0
    if not args.fixture or len(args.fixture) != 2 or not args.deployment or not args.output:
        parser.error('Two retained private fixtures, deployed source proof and fresh output required')
    modes.require(not args.output.exists(), 'Preserve previous hosted QA evidence')
    report = dict(passed=False, verification_passed=False,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        kind='two authenticated owned protocol clients in one authoritative hosted mine',
        graphical_clients_started=0, accounts_created=0, remote_sql_writes_by_tool=0,
        access_level='Previously audited synthetic Lv4/XP7355; not earned progression',
        local_player_data_uploaded=False, database_restored=False,
        max_real_global_rounds=args.max_rounds, source_tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limitations=['automated protocol validation; no graphical clients',
                     'damage/rank effects on retained owned QA accounts remain saved',
                     'patrol/search alternatives and diverse AP values have separate automated regression tests'])
    try:
        source = deployment_hashes(args.deployment)
        fixture = Fixture(args.fixture)
        modes.require(fixture.host == '185.184.42.88', 'Retained fixtures belong to another host')
        run(fixture, source, report, max_rounds=args.max_rounds)
    except Exception as error:
        report.update(error_type=type(error).__name__, error_locations=[dict(file=Path(f.filename).name, line=f.lineno)
            for f in traceback.extract_tb(error.__traceback__)])
        if isinstance(error, AssertionError):
            report['reason'] = str(error)[:250]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(report, out, indent=2)
    progress('complete', passed=report['passed'], report=str(args.output), credentials_printed=False)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
