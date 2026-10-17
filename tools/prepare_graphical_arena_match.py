"""Prepare or explicitly retire one owned hosted graphical QA match.

Start uses genuine encrypted public TCP peers and normal mode0/1 loaded packets,
then closes only those sockets without leave so native clients can reconnect.
No account creation, server configuration changes, UI automation or client
launch occurs here. Import and --self-test perform no network operations.
"""
from contextlib import contextmanager
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import (
    FreshSurroundingsQA, NetworkQA, OWNERSHIP, PROFILES, fetch_json,
    published_scene, require, scene_names, sha, validate_shared_ground,
)
from tio.protocol.battle_ground import decode_battle_ground
from tools.heal_owned_surroundings_fixture import heal_owned_fixture

HOST = '185.184.42.88'
VERSION = '2026.10.07.1'
OUTPUT = ROOT/'reports/arena-surroundings-implementation/client-qa/matches'

# Read-only checkpoint inspection refuses every unrelated account/checkpoint.
# Salted credential proof is used internally by OWNERSHIP and never printed.
MATCH_STATE = OWNERSHIP + r'''
import hashlib,subprocess
from tio.battle_snapshot import loads
mode=data['mode'];assert mode in (0,1)
count={0:2,1:4}[mode];size={0:38,1:57}[mode]
participants=data['participants'];assert participants==names[:count] and len(participants)==count
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
online=subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).splitlines()
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 members=list(db.execute('SELECT account,match_id FROM battle_checkpoint_members'))
 assert all(account in participants for account,match in members),'An unrelated checkpoint/player exists'
 checkpoints=list(db.execute('SELECT match_id,payload,checksum,status FROM battle_checkpoints'))
 assert len(checkpoints)<=1 and {r[0] for r in checkpoints}=={m[1] for m in members},'Unexpected checkpoint set'
 pending=db.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0]
 checkpoint=None
 if checkpoints:
  match,payload,checksum,status=checkpoints[0]
  assert status in ('active','finished') and hashlib.sha256(payload.encode()).hexdigest()==checksum
  state=loads(payload)[0];assert state['kind']=='shared'
  battle=state['battle'];field=battle['field']
  roster=sorted(r[0] for r in battle['reward_roster'].values())
  assert roster==sorted(participants) and len(battle['reward_roster'])==count and len(battle['bots'])==0
  assert battle['match_id']==match and battle['room'].request.mode==mode
  assert (field.width,field.height)==(size,size)
  checkpoint=dict(match=match,status=status,participants=roster,bots=0,town=battle['city_id'],mode=mode,
   ground_sha256=hashlib.sha256(battle['ground']).hexdigest(),width=field.width,height=field.height,
   members=sorted(account for account,x in members),metadata=field.scene_metadata)
 print(json.dumps(dict(service='active',integrity='ok',established_connections=len(online),
  pending_settlements=pending,checkpoint=checkpoint)))
'''


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def mode_spec(mode):
    require(type(mode) is int and mode in (0, 1), 'Only normal owned mode0/1 graphical QA is supported')
    return {0:(2,38),1:(4,57)}[mode]


def match_report_path(fixture, city, mode=0):
    mode_spec(mode)
    return OUTPUT/(fixture.prefix+'-'+city+('-mode1' if mode == 1 else '')+'.json')


def own_state(fixture, mode=0):
    count, _ = mode_spec(mode)
    return fixture.remote(MATCH_STATE, {**fixture.ownership_payload(), 'participants': fixture.names[:count], 'mode': mode})


def validate_start_snapshot(snapshot, fixture, city, ground_sha, mode=0):
    count, size = mode_spec(mode)
    require(snapshot['town'] == PROFILES[city]['town'] and snapshot['metadata']['profile'] == city,
            'Another city was selected')
    require(snapshot['bots'] == 0 and len(snapshot['actors']) == count and
            {actor['account'] for actor in snapshot['actors']} == set(fixture.names[:count]),
            'Graphical match requires exactly the normal owned real roster and zero bots')
    require((snapshot['width'], snapshot['height']) == (size, size) and snapshot['ground_sha256'] == ground_sha,
            'Authoritative checkpoint differs from the shared public ground')
    require(all(0 <= x < size and 0 <= y < size for x, y in snapshot['blocked']), 'Decorative cells became blocked gameplay cells')
    require(not any(obj['file'].startswith('as_') for obj in snapshot['metadata']['objects']),
            'Decorative models became authoritative objects')


def validate_retained(state, fixture, city, match=None, ground_sha=None, *, complete=False, mode=0):
    count, size = mode_spec(mode)
    require(state['service'] == 'active' and state['integrity'] == 'ok', 'Hosted state is unhealthy')
    checkpoint = state['checkpoint']
    require(checkpoint is not None and checkpoint['participants'] == sorted(fixture.names[:count]) and
            checkpoint['bots'] == 0, 'Expected owned checkpoint is absent or has a foreign roster')
    require(checkpoint['town'] == PROFILES[city]['town'] and checkpoint['metadata']['profile'] == city and
            checkpoint['mode'] == mode and (checkpoint['width'], checkpoint['height']) == (size, size),
            'Retained checkpoint city/mode/dimensions changed')
    require(match is None or checkpoint['match'] == match, 'A different match replaced the graphical checkpoint')
    require(ground_sha is None or checkpoint['ground_sha256'] == ground_sha, 'Retained ground bytes changed')
    require(set(checkpoint['members']) <= set(fixture.names[:count]), 'Unrelated retained member')
    if complete:
        require(checkpoint['status'] == 'active' and checkpoint['members'] == sorted(fixture.names[:count]),
                'Every normal owned participant must retain the active checkpoint')
    return checkpoint


def wait_disconnected(fixture, seconds=10, mode=0):
    deadline = time.monotonic()+seconds
    while True:
        state = own_state(fixture, mode)
        if state['established_connections'] == 0:
            return state
        require(time.monotonic() < deadline, 'QA sockets did not disconnect promptly')
        time.sleep(.2)


@contextmanager
def public_peers(fixture, seconds=90):
    network = NetworkQA(fixture)
    # A deadline closes only this helper's own sockets, never native processes.
    timer = threading.Timer(seconds, network.close)
    timer.daemon = True
    timer.start()
    try:
        yield network
    finally:
        timer.cancel()
        network.close()


def validate_fixture(fixture, mode=0):
    count, _ = mode_spec(mode)
    require(fixture.host == HOST and len(fixture.names) in (2, 4, 8), 'Unexpected hosted QA fixture')
    require(len(fixture.names) >= count and fixture.names == [fixture.prefix+chr(97+i) for i in range(len(fixture.names))] and
            re.fullmatch(r'qs[0-9a-f]{8}', fixture.prefix), 'Only the contiguous normal fixture-owned roster is permitted')


def start(fixture, city, report_path, mode=0):
    validate_fixture(fixture, mode)
    count, size = mode_spec(mode)
    report = dict(action='start', passed=False, city=city, mode=mode, host=HOST,
                  fixture_private_path=fixture.credential_path, accounts=fixture.names[:count],
                  graphical_accounts=fixture.names[:2], disconnected_additional_accounts=fixture.names[2:count],
                  report=str(report_path), accounts_created=0, clients_started=0,
                  kind='Genuine public encrypted TCP setup; retained checkpoint for later native graphical reconnect')
    try:
        preflight = own_state(fixture, mode)
        require(preflight['established_connections'] == 0 and preflight['checkpoint'] is None and
                preflight['pending_settlements'] == 0, 'Other players or a previous battle are present')
        report['preservation_before'] = fixture.preservation()
        policy = json.loads((ROOT/'config/arena_surroundings.json').read_text(encoding='utf-8'))
        manifest = fetch_json('https://'+HOST+'/updates/manifest.json')
        require(manifest['version'] == VERSION, 'Expected published surroundings client version is absent')
        report['client_version'] = manifest['version']
        fixture.set_city(city)  # Ownership-checked own QA locations/HP only.
        report['canonical_owned_fixture_heal'] = heal_owned_fixture(fixture, city)
        with public_peers(fixture) as network:
            packets = network.start(mode)  # Normal queue/team Ready and b'36' loaded for the complete roster.
            ground, scene = validate_shared_ground(packets, city, mode, policy)
            snapshot = fixture.snapshot(fixture.names[:count])
            ground_sha = sha(packets[0])
            validate_start_snapshot(snapshot, fixture, city, ground_sha, mode)
            connected_state = own_state(fixture, mode)
            require(connected_state['established_connections'] == count, 'Another player connected during match setup')
            validate_retained(connected_state, fixture, city, snapshot['match'], ground_sha, complete=True, mode=mode)
            report.update(match=snapshot['match'], ground_sha256=ground_sha, scene=scene,
                          variant=scene.split('_')[2], brushes=sorted(set(ground.first_layer)),
                          participants=count, bots=0, width=size, height=size, owned_roster_verified=True)
            resource = published_scene(HOST, manifest, scene, size)
            report['published_resource'] = dict(path=resource['path'], sha256=resource['sha256'],
                models=resource['native']['model_count'], sides=sorted(resource['alpha_proof']['four_sides']),
                corners=sorted(resource['alpha_proof']['four_corners']),
                model_dependencies=len(resource['model_dependencies']))
            require(resource['native']['width'] == resource['native']['height'] == 1,
                    'Published decoration must have an empty 1x1 scene footprint')
            # Context exit closes sockets without b'2a01', b'ba05' or leave().
        disconnected = wait_disconnected(fixture, mode=mode)
        checkpoint = validate_retained(disconnected, fixture, city, report['match'], report['ground_sha256'], complete=True, mode=mode)
        require(disconnected['pending_settlements'] == 0, 'Unexpected pending settlement after pure disconnect')
        report.update(passed=True, checkpoint_preserved=True, socket_close_without_leave=True,
                      native_reconnect_seconds=180, native_scene_load_seconds=30,
                      disconnected_at_unix=time.time(), final_checkpoint_status=checkpoint['status'])
        return report
    except BaseException as error:
        report['error_type'] = type(error).__name__
        # Deliberately do not auto-forfeit a retained match on an inspection failure.
        raise
    finally:
        if report_path.exists():
            stamp = str(time.time_ns())
            if report.get('passed'):
                previous_path = report_path.with_name(report_path.stem+'-previous-'+stamp+'.json')
                previous_path.write_bytes(report_path.read_bytes())
            else:
                # A rejected duplicate start must preserve the existing cleanup record.
                report_path = report_path.with_name(report_path.stem+'-start-failed-'+stamp+'.json')
                report['report'] = str(report_path)
        write_report(report_path, report)


def native_process_exited(pid):
    require(type(pid) is int and 0 < pid < 2**32, 'Invalid observed native PID')
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x1000, 0, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
            return True
        raise RuntimeError('Cannot verify native process exit')
    try:
        status = ctypes.c_uint32()
        require(kernel.GetExitCodeProcess(handle, ctypes.byref(status)), 'Cannot query native process exit')
        return status.value != 259  # STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def cleanup(fixture, city, report_path, native_pids, mode=0):
    validate_fixture(fixture, mode)
    count, size = mode_spec(mode)
    require(len(native_pids) == 2 and len(set(native_pids)) == 2 and all(native_process_exited(pid) for pid in native_pids),
            'Both observed own native clients must exit before cleanup')
    saved = json.loads(report_path.read_text(encoding='utf-8'))
    require(saved.get('action') == 'start' and saved.get('owned_roster_verified') is True and
            saved['city'] == city and saved['host'] == HOST and saved['accounts'] == fixture.names[:count] and
            saved['mode'] == mode and saved['participants'] == count and
            saved['fixture_private_path'] == fixture.credential_path and re.fullmatch('[0-9a-f]{64}', saved['ground_sha256']),
            'Matching ownership-verified graphical match record is required')
    cleanup_path = report_path.with_name(report_path.stem+'-cleanup.json')
    report = dict(action='cleanup', passed=False, city=city, mode=mode, match=saved['match'],
                  accounts=fixture.names[:count], fixture_private_path=fixture.credential_path,
                  native_pids=list(native_pids), accounts_created=0, clients_started=0)
    try:
        state = own_state(fixture, mode)
        require(state['established_connections'] == 0, 'Other accounts are online; cleanup aborted')
        checkpoint = state['checkpoint']
        if checkpoint is not None:
            checkpoint = validate_retained(state, fixture, city, saved['match'], saved['ground_sha256'], mode=mode)
            active = [fixture.names.index(name) for name in checkpoint['members']]
            with public_peers(fixture) as network:
                replay_hashes = []
                for index in active:
                    peer = network.enter(index)
                    if b'\x41' not in network.received[index]:
                        peer.until(b'\x41', max_packets=2048)
                    packet = next(p for p in reversed(network.received[index]) if p[:1] == b'\x35')
                    require(sha(packet) == saved['ground_sha256'], 'Cleanup reconnect replaced the retained scene')
                    ground = decode_battle_ground(packet)
                    require((ground.width, ground.height) == (size, size) and set(ground.first_layer) <= PROFILES[city]['brushes'] and
                            [entry.name.decode('ascii') for entry in ground.entries if entry.name.startswith(b'as_')] == [saved['scene']],
                            'Unexpected cleanup replay scene')
                    network.command(index, b'\x36')
                    replay_hashes.append(sha(packet))
                connected_state = own_state(fixture, mode)
                require(connected_state['established_connections'] == len(active), 'Another player connected during cleanup')
                validate_retained(connected_state, fixture, city, saved['match'], saved['ground_sha256'], mode=mode)
                for index in active:
                    network.command(index, b'\x2a\x01')  # Normal explicit forfeit/result leave.
                report.update(explicit_forfeit_accounts=[fixture.names[index] for index in active],
                              replay_ground_hashes=replay_hashes)
        else:
            report['already_cleared'] = True
        final = wait_disconnected(fixture, mode=mode)
        require(final['checkpoint'] is None and final['pending_settlements'] == 0,
                'Owned checkpoint/settlement remains after explicit cleanup')
        report.update(passed=True, checkpoint_cleared=True, online=0, preservation=fixture.preservation())
        return report
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        write_report(cleanup_path, report)


def self_test():
    compile(MATCH_STATE, '<read-only graphical match inspection>', 'exec')
    fixture = type('OwnedFixture', (), dict(host=HOST, prefix='qs1234abcd', names=['qs1234abcda', 'qs1234abcdb']))()
    validate_fixture(fixture)
    snapshot = dict(town=2, metadata=dict(profile='denver', objects=[]), bots=0,
                    actors=[dict(account=n) for n in fixture.names], width=38, height=38,
                    blocked=[], ground_sha256='a'*64)
    validate_start_snapshot(snapshot, fixture, 'denver', 'a'*64)
    state = dict(service='active', integrity='ok', checkpoint=dict(match='own-match', status='active',
        participants=sorted(fixture.names), bots=0, town=2, metadata=dict(profile='denver'), width=38,mode=0,
        height=38, members=sorted(fixture.names), ground_sha256='a'*64))
    validate_retained(state, fixture, 'denver', 'own-match', 'a'*64, complete=True)
    checks = 3
    for mutation in (
        lambda s: s['checkpoint'].update(participants=['foreign']),
        lambda s: s['checkpoint'].update(bots=1),
        lambda s: s['checkpoint'].update(match='other-match'),
        lambda s: s['checkpoint'].update(ground_sha256='b'*64),
        lambda s: s['checkpoint'].update(width=57),
        lambda s: s['checkpoint'].update(members=fixture.names[:1]),
    ):
        bad = json.loads(json.dumps(state))
        mutation(bad)
        try:
            validate_retained(bad, fixture, 'denver', 'own-match', 'a'*64, complete=True)
        except AssertionError:
            checks += 1
        else:
            raise AssertionError('Invalid graphical checkpoint guard was accepted')
    four = type('OwnedFixture', (), dict(host=HOST,prefix='qs1234abcd',
        names=['qs1234abcd'+chr(97+i) for i in range(4)]))()
    validate_fixture(four, 1)
    large = json.loads(json.dumps(snapshot))
    large.update(width=57,height=57,actors=[dict(account=n) for n in four.names])
    validate_start_snapshot(large,four,'denver','a'*64,1)
    large_state=json.loads(json.dumps(state))
    large_state['checkpoint'].update(mode=1,width=57,height=57,participants=sorted(four.names),members=sorted(four.names))
    validate_retained(large_state,four,'denver','own-match','a'*64,complete=True,mode=1)
    require(match_report_path(four,'denver')!=match_report_path(four,'denver',1) and
            match_report_path(four,'denver',1).name=='qs1234abcd-denver-mode1.json', 'Mode1 must preserve mode0 reports')
    checks+=4
    for label,mutate in (
        ('foreign mode1 roster',lambda s:s['checkpoint'].update(participants=four.names[:3]+['foreign'])),
        ('wrong mode1 width',lambda s:s['checkpoint'].update(width=38)),
        ('wrong normal team mode',lambda s:s['checkpoint'].update(mode=0)),
        ('partial four-account checkpoint',lambda s:s['checkpoint'].update(members=four.names[:2])),
        ('foreign retained mode1 member',lambda s:s['checkpoint'].update(members=four.names+['foreign'])),
    ):
        changed=json.loads(json.dumps(large_state));mutate(changed)
        try:validate_retained(changed,four,'denver','own-match','a'*64,complete=True,mode=1)
        except AssertionError:checks+=1
        else:raise AssertionError('Invalid '+label+' guard was accepted')
    partial=json.loads(json.dumps(large_state))
    partial['checkpoint']['members']=four.names[:2]
    validate_retained(partial,four,'denver','own-match','a'*64,mode=1)
    checks+=1 # Expired own C/D are valid cleanup members; foreign/offline checkpoints still abort.
    for fixture_case,mode in ((fixture,1),(four,4)):
        try:validate_fixture(fixture_case,mode)
        except AssertionError:checks+=1
        else:raise AssertionError('Insufficient owned roster or unsupported mode was accepted')
    print(json.dumps(dict(offline_self_test='passed', checks=checks, network_requests=0,
                          accounts_created=0, battles_started=0, clients_started=0)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('start', 'cleanup'))
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--city', choices=tuple(PROFILES))
    parser.add_argument('--mode',type=int,choices=(0,1),default=0,
                        help='0:two owned accounts/38; 1:four owned accounts/57, with only a/b later native')
    parser.add_argument('--native-pids', type=int, nargs=2, help='The two observed own native PIDs; cleanup requires both exited')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.action is None or args.fixture is None or args.city is None:
        parser.error('action, --fixture and --city are required')
    if args.action == 'cleanup' and not args.native_pids:
        parser.error('cleanup requires --native-pids from the two own native-client startup events')
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    path = match_report_path(fixture,args.city,args.mode)
    report = start(fixture,args.city,path,args.mode) if args.action == 'start' else cleanup(fixture,args.city,path,args.native_pids,args.mode)
    fields = ('action', 'passed', 'city','mode', 'match', 'fixture_private_path', 'ground_sha256', 'scene', 'variant',
              'brushes', 'participants', 'bots', 'checkpoint_preserved', 'checkpoint_cleared')
    print(json.dumps({key: report[key] for key in fields if key in report}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps(dict(event='graphical_match_helper_failed', error_type=type(error).__name__)), file=sys.stderr)
        raise SystemExit(1)
