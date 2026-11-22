"""Public TLS mine movement and explicit menu exit on two excluded owners."""
import json
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import tio
import server
saved_path = list(sys.path)
from tools.verify_game_operations_hosted import CREATE, CLEANUP, remote
sys.path[:] = saved_path
from tools.verify_training_base_20261018_hosted import PREPARE
sys.path[:] = saved_path
from tools.verify_launcher_required_hosted_20261020 import Network
sys.path[:] = saved_path
from tools.verify_chat_paste_hosted_20261117 import disconnect
sys.path[:] = saved_path
from tio.protocol.battle_move import BattleMove, encode_move_request

OUT = ROOT / 'reports/mine-menu-exit-20261117'
PRIVATE = ROOT / '.secrets/mine-menu-exit-20261117.json'

STATE = r'''
import json,sqlite3
from collections import deque
from tio.rating_visibility import QA_LOGIN
from tio.battle_snapshot import loads
assert QA_LOGIN.fullmatch(request)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.payload,m.owner_id FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(request,)).fetchone()
 if not row:
  print(json.dumps(None))
 else:
  b=loads(row[0])[0]['battle'];f=b['field'];owner=row[1]
  assert b['kind']=='mine' and b['reward_roster'][owner][0]==request
  ids=f.living_actor_ids(owner)
  if not ids:
   print(json.dumps(dict(finished=True)))
  else:
   actor,=ids;a=f.actor(actor);start=(a.x,a.y);exits=f.mining.layout.lift
   occupied={(v.x,v.y) for v in f._actors.values() if v.health and v.actor_id!=actor}
   def neighbours(p):
    return [q for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))
            if f.inside(*(q:=(p[0]+dx,p[1]+dy))) and q not in f.blocked|occupied]
   queue=deque([(start,())]);seen={start};route=None
   while queue:
    p,path=queue.popleft()
    if (p in exits)!=(start in exits):route=path;break
    for q in neighbours(p):
     if q not in seen:seen.add(q);queue.append((q,(*path,q)))
   turn=b['arena']._turns.get(b['room'].room_id)
   print(json.dumps(dict(finished=b['finished'],match=b['match_id'],actor=actor,
    position=start,hp=a.health,ap=a.action_points,inside=start in exits,
    turn=bool(turn and turn[0]==owner),inside_steps=[p for p in neighbours(start) if p in exits],route=route,
    mob_stats=[[f.combat.defense(i),f.actor(i).max_health] for i in f.combat.npc_defense])))
'''


def main(*, cases=((15, 15), (16, 16)), mob_stats=None,
         quit_away_from_exit=False, drill_crystals=(0, 0)) -> None:
    assert len(cases) == 2
    assert len(drill_crystals) == 2
    assert not PRIVATE.exists(), 'Previous owned fixtures need cleanup'
    prefix = 'qt' + secrets.token_hex(4)
    data = dict(names=[prefix + 'a', prefix + 'b'],
                passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision'] = remote(CREATE, list(zip(data['names'], data['passwords'])))
    PRIVATE.write_text(json.dumps(data), encoding='utf-8')
    net = Network(data)
    report = dict(passed=False, public_tls=True, graphical_clients=False, cases=[])

    def state(index):
        return remote(STATE, data['names'][index])

    def move(index, actor, path):
        return net.command(index, encode_move_request(BattleMove(actor, tuple(map(tuple, path)))), expected=b'\x3d')

    def leave(index):
        current = state(index)
        if current and not current['finished']:
            assert current['turn'] and current['route']
            route = current['route']
            if not quit_away_from_exit or current['inside']:
                replies = move(index, current['actor'], route)
                assert not any(p[0] == 0x4c for p in replies)
            if current['inside'] and not quit_away_from_exit:
                back = route[-2] if len(route) > 1 else current['position']
                replies = move(index, current['actor'], (back,))
                assert not any(p[0] == 0x4c for p in replies)
            assert not state(index)['finished']
            if quit_away_from_exit:
                assert not state(index)['inside'], 'Quit test still stands at the exit'
            replies = net.command(index, b'\x2a\x01', expected=b'\x4c')
            threshold = 200 if cases[index][0] >= 11 else 100
            assert next(p for p in replies if p[0] == 0x4c)[3] == int(
                drill_crystals[index] >= threshold)
        net.command(index, b'\x2a\x01')
        net.command(index)

    try:
        for index, (level, town) in enumerate(cases):
            prepare = PREPARE.replace("'0x8c4aef':4", "'0x8c4aef':" + str(level))
            prepare = prepare.replace('FLOORS[3]', 'FLOORS[' + str(level - 1) + ']')
            prepare = prepare.replace('19,*center(19)', str(town) + ',*center(' + str(town) + ')')
            prepare = prepare.replace('from tio.protocol.item_list import encode_item_list',
                                      'from tio.protocol.item_list import encode_item_list,ItemRecord')
            prepare = prepare.replace('encode_item_list(1,())',
                'encode_item_list(1,(ItemRecord(9001,52,bytes(2),'
                + str(drill_crystals[index]) + ',0,0,(1,1,1),bytes(4),None,bytes(3)),))')
            remote(prepare, [data['names'][index]])
            net.connect(index)
        for index in (0, 1):
            net.command(index, b'\xb0\x14\x01', expected=b'\x41')
            net.command(index, b'\x36')
            deadline = time.monotonic() + 20
            while True:
                before = state(index)
                if before and before.get('turn'):
                    break
                assert time.monotonic() < deadline, 'Mine turn did not start'
                time.sleep(.2)
            assert before['inside'] and before['inside_steps']
            if mob_stats is not None:
                assert before['mob_stats'] == [list(mob_stats[index])] * 10
            assert b'\xb2\x16\x01' in net.received[index], 'Quit menu not enabled with an empty drill'
            destination = before['inside_steps'][0]
            replies = move(index, before['actor'], (destination,))
            after = state(index)
            assert not any(p[0] == 0x4c for p in replies), 'First step returned battle result'
            assert after and not after['finished'] and after['match'] == before['match']
            assert after['position'] == destination and after['hp'] == before['hp']
            assert after['ap'] < before['ap']
            report['cases'].append(dict(level=cases[index][0], first_step_kept_battle=True,
                                         hp_preserved=True, movement_ap_spent=True,
                                         mob_stats=before['mob_stats']))
            leave(index)
            report['cases'][-1].update(
                movement_did_not_finish_battle=True,
                quit_away_from_exit=quit_away_from_exit,
                drill_crystals=drill_crystals[index],
                explicit_menu_result_verified=True)
        report['passed'] = True
    finally:
        try:
            for index in tuple(net.peers):
                if state(index):
                    leave(index)
            disconnect(net, lambda i: net.tls.begin(data['names'][i], 37001 + i,
                                                    password=data['passwords'][i]))
            assert all(state(i) is None for i in (0, 1)), 'QA battle still retained'
            cleanup = remote(CLEANUP, dict(names=data['names'],
                protected_before=data['provision']['protected_before'], require_unchanged_players=False))
            (OUT / 'fixture-cleanup.json').write_text(json.dumps(cleanup, indent=2), encoding='utf-8')
            PRIVATE.unlink()
        finally:
            net.close()
            (OUT / 'public-tls.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
