"""Reproduce the verified Reservation bootstrap against the original TI client.

The launcher uses a synthetic local account and instrumented authentication /
character-selection callbacks. City selection and opening use server packets;
the diagnostic direct town-view callback is deliberately absent.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLAGS = (
    '--loopback --completion --login-result --server-list --server-list-entry '
    '--server-login --mode1-challenge --mode1-complete --auth2-result '
    '--shared-config --empty-characters --create-success-probe --select-probe '
    '--mychar-probe --town-probe --enter-town-probe --open-town-probe '
    '--visible-launch --inspect-window'
).split()

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=0,help='Session duration: 0 = until client closes (default), 1..3600 = timed diagnostic run')
    parser.add_argument('--database',type=Path,default=ROOT/'data/reservation.sqlite3',help='Persistent character database')
    parser.add_argument('--probe-catalogs',action='store_true',help='Diagnostic: request city catalogs through original native builders')
    roster = parser.add_mutually_exclusive_group()
    roster.add_argument('--probe-owned-pet',action='store_true',help='Compatibility alias: saved roster is now loaded by default')
    roster.add_argument('--empty-roster',action='store_true',help='Diagnostic: omit owned roster and disable inventory, hiring and shop mutations')
    parser.add_argument('--probe-purchase',action='store_true',help='Diagnostic: buy one knife using native builder; use a separate test database')
    parser.add_argument('--probe-sale',action='store_true',help='Diagnostic: sell the last owned item using native builder in a separate test database')
    parser.add_argument('--probe-hire',action='store_true',help='Diagnostic: hire candidate2 using a separate test database')
    parser.add_argument('--probe-dismiss',action='store_true',help='Diagnostic: dismiss hired pet2 in a separate test database')
    parser.add_argument('--probe-battle-settings',action='store_true',help='Diagnostic: send BattleSettings after inventory in a separate database')
    parser.add_argument('--probe-battle-members',action='store_true',help='Diagnostic: send own member25 and settings6C in a separate database')
    parser.add_argument('--probe-arena-create',action='store_true',help='Diagnostic: native create request through server handler in a separate database')
    parser.add_argument('--probe-arena-ready',action='store_true',help='Diagnostic: create and toggle ready twice through native callbacks')
    parser.add_argument('--probe-arena-leave',action='store_true',help='Diagnostic: create, toggle ready, then leave through native callbacks')
    parser.add_argument('--probe-battle-scene',action='store_true',help='Diagnostic: empty8x8 scene after room creation; separate database required')
    parser.add_argument('--probe-battle-actor',action='store_true',help='Diagnostic: add first saved human to scene without equipment')
    parser.add_argument('--probe-battle-heal',action='store_true',help='Diagnostic: cast dog healing twice using saved dog1 in a separate database')
    parser.add_argument('--probe-equip',action='store_true',help='Diagnostic: original equip/unequip requests in a separate database')
    parser.add_argument('--probe-equip-replace',action='store_true',help='Diagnostic: equip first, replace with second, remove second; requires two saved items')
    parser.add_argument('--probe-turn-timeout',action='store_true',help='Diagnostic: two-second actor turn with no client EndTurn')
    parser.add_argument('--probe-battle-move',action='store_true',help='Diagnostic: server sends actor path after scene loading; separate database')
    parser.add_argument('--probe-two-turns',action='store_true',help='Diagnostic: two turns with original movement requests; separate database')
    parser.add_argument('--probe-battle-remove',action='store_true',help='Diagnostic: remove scene actor after EndTurn; separate database')
    parser.add_argument('--probe-warehouse-transfer',action='store_true',help='Diagnostic: withdraw then deposit item1001 in separate database')
    parser.add_argument('--probe-warehouse-partial',action='store_true',help='Diagnostic: withdraw3 then deposit2 from prepared ammunition stack')
    args=parser.parse_args()
    if args.probe_battle_heal:
        if args.probe_battle_move or args.probe_two_turns or args.probe_turn_timeout or args.probe_battle_remove:
            parser.error('Healing probe requires its own turn sequence')
        args.probe_battle_actor=True
        FLAGS.append('--battle-heal-probe')
    if args.probe_warehouse_partial:
        args.probe_warehouse_transfer=True
        FLAGS.append('--warehouse-partial-probe')
    if args.probe_warehouse_transfer:
        if args.empty_roster or any(value for key,value in vars(args).items() if key.startswith('probe_') and key not in ('probe_warehouse_transfer','probe_warehouse_partial','probe_owned_pet')):parser.error('Warehouse probe requires saved roster and no other probes')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve():parser.error('Warehouse probe requires a separate database')
        FLAGS.append('--warehouse-transfer-probe')
    if args.probe_battle_remove:
        if args.probe_two_turns or args.probe_turn_timeout:parser.error('Removal probe requires a single normally ended turn')
        args.probe_battle_actor=True
        FLAGS.append('--battle-remove-probe')
    if args.probe_two_turns:
        if args.probe_turn_timeout:parser.error('Two-turn movement probe cannot combine timeout probe')
        args.probe_battle_move=True
        FLAGS.append('--two-turns-probe')
    if args.probe_battle_move:
        args.probe_battle_actor=True
        FLAGS.append('--battle-move-probe')
    if args.probe_turn_timeout:
        args.probe_battle_actor=True
        FLAGS.append('--turn-timeout-probe')
    if args.probe_equip_replace:
        args.probe_equip=True
        FLAGS.append('--equip-replace-probe')
    if args.probe_equip:
        if args.empty_roster or any((args.probe_purchase,args.probe_sale,args.probe_hire,args.probe_dismiss,args.probe_arena_create,args.probe_arena_ready,args.probe_arena_leave,args.probe_battle_settings,args.probe_battle_members,args.probe_battle_scene,args.probe_battle_actor)):
            parser.error('Equip probe requires a roster and no other mutation probes')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve():
            parser.error('Equip probe requires a separate test database')
        FLAGS.append('--equip-probe')
    if args.probe_battle_actor:
        args.probe_battle_scene=True
        FLAGS.append('--battle-actor-probe')
    if args.probe_battle_scene:
        if args.probe_arena_ready or args.probe_arena_leave: parser.error('Scene probe cannot combine ready/leave probes')
        args.probe_arena_create=True
        FLAGS.append('--battle-scene-probe')
    if args.probe_arena_create or args.probe_arena_ready or args.probe_arena_leave:
        if args.empty_roster or args.probe_hire or args.probe_dismiss or args.probe_purchase or args.probe_sale or args.probe_battle_settings or args.probe_battle_members:
            parser.error('Arena create probe requires roster and no other mutation or battle probes')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve(): parser.error('Arena create probe requires a separate database')
        FLAGS.append('--arena-create-probe')
        if args.probe_arena_ready or args.probe_arena_leave: FLAGS.append('--arena-ready-probe')
        if args.probe_arena_leave: FLAGS.append('--arena-leave-probe')
    if args.probe_battle_settings or args.probe_battle_members:
        if args.empty_roster or args.probe_hire or args.probe_dismiss or args.probe_purchase or args.probe_sale: parser.error('Battle settings probe requires roster and no mutation probes')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve(): parser.error('Battle settings probe requires a separate database')
        FLAGS.append('--battle-settings-probe')
        if args.probe_battle_members: FLAGS.append('--battle-members-probe')
    if args.probe_dismiss:
        if args.empty_roster or args.probe_hire or args.probe_purchase or args.probe_sale: parser.error('Dismiss probe requires a roster and no other mutation probes')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve(): parser.error('Dismiss probe requires a separate test database')
        FLAGS.append('--dismiss-probe')
    if args.probe_hire:
        if args.empty_roster: parser.error('--probe-hire requires a roster')
        if args.probe_purchase or args.probe_sale: parser.error('Run hiring separately from shop probes')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve(): parser.error('--probe-hire requires a separate test database')
        FLAGS.append('--hire-probe')
    if args.probe_sale:
        if args.probe_purchase: parser.error('Use separate purchase and sale runs')
        if args.empty_roster: parser.error('--probe-sale requires a roster')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve(): parser.error('--probe-sale requires a separate test database')
        FLAGS.append('--shop-sale-probe')
    if args.probe_purchase:
        if args.empty_roster: parser.error('--probe-purchase requires a roster')
        if args.database.resolve()==(ROOT/'data/reservation.sqlite3').resolve(): parser.error('--probe-purchase requires a separate test database')
        FLAGS.append('--shop-purchase-probe')
    # Local starter data is experimental; existing saved actors/items are preserved.
    if not args.empty_roster: FLAGS.append('--owned-pet-probe')
    if args.probe_catalogs: FLAGS.append('--catalog-request-probe')
    if not 0 <= args.seconds <= 3600:parser.error('--seconds must be 0..3600')
    FLAGS.append(f'--observation-seconds={args.seconds}')
    FLAGS.append(f'--database={args.database.resolve()}')
    raise SystemExit(subprocess.call(
        [sys.executable, str(ROOT / 'tools/probe_item_fixture.py'), *FLAGS], cwd=ROOT
    ))
