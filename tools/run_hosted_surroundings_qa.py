"""Bounded public multiplayer diagnostics using an existing owned QA fixture.

The release verifier is imported unchanged. This wrapper creates no accounts,
starts no graphical clients, changes no server configuration and uploads no
data. An explicit run adjusts only ownership-checked fixture characters, then
uses the normal encrypted public matchmaking protocol. Incremental evidence
contains opcodes/counts and sanitized F0/394 messages, never packet payloads or
credentials. Import and --self-test contact no server.
"""
from collections import Counter
from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import (
    FreshSurroundingsQA, NetworkQA, OWNERSHIP, PARTICIPANTS, PROFILES,
    fetch_json, published_scene, require, sha, validate_shared_ground,
)
from tools.heal_owned_surroundings_fixture import heal_owned_fixture

HOST = '185.184.42.88'
VERSION = '2026.10.07.1'
OUTPUT = ROOT/'reports/arena-surroundings-implementation/hosted-diagnostics'
PREFLIGHT = OWNERSHIP + r'''
import subprocess
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
online=subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).splitlines()
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not online,'Other graphical/protocol clients are connected'
 assert db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0]==0,'A retained match exists'
 assert db.execute('SELECT COUNT(*) FROM battle_checkpoint_members').fetchone()[0]==0,'Retained participants exist'
 assert db.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0]==0,'A settlement is pending'
print(json.dumps(dict(service='active',integrity='ok',established_connections=0,checkpoints=0,pending_settlements=0)))
'''


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(temporary, path)


def scrub(value, fixture):
    text = str(value)
    for password in fixture.passwords:
        if password:
            text = text.replace(password, '[redacted]')
    return ''.join(c if c >= ' ' or c == '\n' else '?' for c in text)[:500]


def f0_summary(packet, fixture):
    if len(packet) < 9 or packet[0] != 0xf0:
        return None
    command = int.from_bytes(packet[1:5], 'little')
    result = dict(command=command, arguments=int.from_bytes(packet[5:9], 'little'))
    if command == 394:
        result['rejected'] = True
        if len(packet) >= 15 and packet[5:13] == b'\x01\0\0\0\x05\0\0\0' and packet[-2:] == b'\0\0':
            result['message'] = scrub(packet[13:-2].decode('utf-16-le', errors='replace'), fixture)
        else:
            result['message'] = 'Malformed native error argument; payload withheld'
    return result


class NativeRejection(RuntimeError):
    pass


class Evidence:
    def __init__(self, fixture, path, modes, cities):
        self.fixture, self.path = fixture, path
        self.started = time.monotonic()
        self.stage = 'not_started'
        self.last_flush = 0
        self.expected_native_rejection = None
        self.lock = threading.RLock()
        self.report = dict(schema='arena-surroundings-hosted-diagnostic/v1',
            kind='Real accounts over genuine public encrypted TCP; no graphical clients',
            passed=False, completed=False, accounts_created=0, graphical_clients_started=0,
            server_config_changed=False, host=fixture.host, fixture_private_path=fixture.credential_path,
            accounts=fixture.names, modes=list(modes), cities=list(cities), matches=[],
            packet_counts={}, native_messages=[], events=[], current_stage=self.stage,
            original_verifier_sha256=sha((ROOT/'tools/verify_hosted_arena_surroundings.py').read_bytes()),
            command_ping_is_processing_barrier=False)
        self.flush()

    def flush(self):
        with self.lock:
            self.report['elapsed_seconds'] = round(time.monotonic()-self.started, 3)
            save(self.path, self.report)
            self.last_flush = time.monotonic()

    def event(self, kind, **fields):
        with self.lock:
            item = dict(kind=kind, elapsed_seconds=round(time.monotonic()-self.started, 3), **fields)
            self.report['events'].append(item)
            self.report['events'] = self.report['events'][-2048:]
            self.report['current_stage'] = self.stage
            self.flush()
        print(json.dumps(item), flush=True)

    @contextmanager
    def operation(self, stage, **fields):
        previous, self.stage = self.stage, stage
        self.event('stage_begin', stage=stage, **fields)
        try:
            yield
        except BaseException:
            self.report.setdefault('last_failure_stage', stage)
            self.event('stage_failed', stage=stage, **fields)
            raise
        else:
            self.event('stage_complete', stage=stage, **fields)
        finally:
            self.stage = previous

    def observe(self, index, packet):
        with self.lock:
            counters = self.report['packet_counts'].setdefault(str(index), {})
            opcode = packet[:1].hex()
            counters[opcode] = counters.get(opcode, 0)+1
            message = f0_summary(packet, self.fixture)
            if message:
                expected = self.expected_native_rejection
                message['expected_negative_check'] = bool(expected and index == expected[0] and
                    message.get('message') == expected[1])
                self.report['native_messages'].append(dict(peer=index, stage=self.stage, **message))
                self.report['native_messages'] = self.report['native_messages'][-256:]
                self.event('native_message', peer=index, stage=self.stage, **message)
                if message.get('rejected') and not message['expected_negative_check']:
                    raise NativeRejection('F0/394: '+message['message'])
            elif time.monotonic()-self.last_flush >= 1:
                self.flush()


class BoundedNetworkQA(NetworkQA):
    def __init__(self, fixture, evidence, seconds):
        super().__init__(fixture)
        require(0 < seconds <= 90, 'Per-case TCP deadline must be at most90 seconds')
        self.evidence = evidence
        self.deadline = time.monotonic()+seconds
        self.expired = threading.Event()
        self._entering = None
        self._tracked = {}
        self.field_dimensions = None
        original_connect, original_handoff = self.case.connect, self.case.handoff

        def connect(port):
            self.check()
            connection = original_connect(port)
            try:
                self.check()
                connection.settimeout(min(15, max(.1, self.deadline-time.monotonic())))
            except BaseException:
                connection.close()
                raise
            return connection

        def handoff(key, denied=False):
            peer = original_handoff(key, denied=denied)
            index = self._entering
            self._tracked[index] = peer
            original_receive, original_until = peer.receive, peer.until
            def receive():
                self.check()
                packet = original_receive()
                self.check()
                evidence.observe(index, packet)
                return packet
            def until(prefix, *, max_packets=100):
                with evidence.operation('await_'+prefix.hex(), peer=index, max_packets=max_packets):
                    return original_until(prefix, max_packets=max_packets)
            peer.receive, peer.until = receive, until
            return peer

        self.case.connect, self.case.handoff = connect, handoff
        self.timer = threading.Timer(seconds, self.expire)
        self.timer.daemon = True
        self.timer.start()

    def check(self):
        if self.expired.is_set() or time.monotonic() >= self.deadline:
            raise TimeoutError('Owned QA TCP case deadline exceeded; awaiting '+self.evidence.stage)

    def expire(self):
        self.expired.set()
        self.evidence.event('tcp_case_deadline', stage=self.evidence.stage)
        # shutdown interrupts an already blocked recv on Windows. Every socket
        # here was created by this NetworkQA instance, never a native client.
        for connection in tuple(self.case.clients):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        super().close()

    def close(self):
        self.timer.cancel()
        super().close()

    def enter(self, index, *, reconnect=False):
        self.check()
        self._entering = index
        with self.evidence.operation('reconnect' if reconnect else 'enter_city', peer=index):
            return super().enter(index, reconnect=reconnect)

    def command(self, index, packet):
        self.check()
        labels = {b'\xba\x03':'create_or_search', b'\xba\x04':'join_team',
                  b'\xba\x01':'list_teams', b'\x2c':'ready', b'\x2e':'captain_start',
                  b'\x36':'scene_loaded', b'\x2a':'leave', b'\x3a':'end_turn', b'\x3c':'move'}
        label = next((label for prefix, label in labels.items() if packet.startswith(prefix)), 'command')
        previous = self.evidence.expected_native_rejection
        if packet[:1] == b'\x3c' and self.field_dimensions:
            from tio.protocol.battle_move import decode_move_request
            move = decode_move_request(packet)
            width, height = self.field_dimensions
            if len(move.path) == 1 and any(x >= width or y >= height for x, y in move.path):
                self.evidence.expected_native_rejection = (index, 'Destination is blocked or outside grid')
        try:
            with self.evidence.operation(label, peer=index, opcode=packet[:1].hex()):
                return super().command(index, packet)
        finally:
            self.evidence.expected_native_rejection = previous

    def cleanup(self):
        if self.expired.is_set():
            self.evidence.report['cleanup'] = 'TCP deadline closed own sockets; retained battle may need normal owned reconnect/forfeit'
            return
        # This uses only authenticated fixture-owned peers already connected.
        # A separate5-second deadline prevents cleanup keepalives from hanging.
        self.timer.cancel()
        self.deadline = time.monotonic()+5
        self.timer = threading.Timer(5, self.expire)
        self.timer.daemon = True
        self.timer.start()
        errors = []
        for index in tuple(self.peers):
            try:
                self.command(index, b'\x2a\x01')
            except (OSError, EOFError, AssertionError, RuntimeError, TimeoutError, KeyError) as error:
                errors.append(dict(peer=index, error=scrub(type(error).__name__+': '+str(error), self.fixture)))
        self.evidence.report['cleanup'] = dict(explicit_owned_leave_attempted=True, errors=errors,
            retained_battle_may_remain=bool(errors) or self.expired.is_set())


def validate_snapshot(initial, fixture, profile, packets, ground):
    count = len(packets)
    names = fixture.names[:count]
    require(initial['town'] == PROFILES[profile]['town'] and initial['metadata']['profile'] == profile,
            'Hosted match chose another city')
    require(initial['bots'] == 0 and len(initial['actors']) == count and
            {actor['account'] for actor in initial['actors']} == set(names), 'The own real-account roster changed')
    require((initial['width'], initial['height']) == (ground.width, ground.height) and
            initial['ground_sha256'] == sha(packets[0]), 'Authoritative shared ground changed')
    require(all(0 <= x < ground.width and 0 <= y < ground.height for x, y in initial['blocked']),
            'Blocked cells lie in decoration')
    require(not any(o['file'].startswith('as_') for o in initial['metadata']['objects']),
            'Decoration became an authoritative gameplay object')


def worker(args):
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host == HOST and len(fixture.names) >= max(PARTICIPANTS[m] for m in args.modes),
            'Existing owned fixture cannot cover this hosted run')
    evidence = Evidence(fixture, args.output, args.modes, args.cities)
    network = None
    try:
        with evidence.operation('exclusive_owned_preflight'):
            evidence.report['preflight'] = fixture.remote(PREFLIGHT, fixture.ownership_payload())
            evidence.report['preservation_before'] = fixture.preservation()
        with evidence.operation('published_manifest'):
            manifest = fetch_json('https://'+HOST+'/updates/manifest.json')
            require(manifest['version'] == VERSION, 'Expected published client version is absent')
            evidence.report['client_version'] = manifest['version']
            policy = json.loads((ROOT/'config/arena_surroundings.json').read_text(encoding='utf-8'))
        resources = {}
        for profile in args.cities:
            for mode in args.modes:
                with evidence.operation('case', city=profile, mode=mode, participants=PARTICIPANTS[mode]):
                    # Refuse native clients/foreign/offline matches before each case.
                    fixture.remote(PREFLIGHT, fixture.ownership_payload())
                    with evidence.operation('owned_fixture_city', city=profile):
                        fixture.set_city(profile)
                        evidence.report.setdefault('owned_fixture_heals', []).append(heal_owned_fixture(fixture, profile))
                    network = BoundedNetworkQA(fixture, evidence, args.case_seconds)
                    packets = network.start(mode)
                    ground, scene = validate_shared_ground(packets, profile, mode, policy)
                    network.field_dimensions = (ground.width, ground.height)
                    names = fixture.names[:PARTICIPANTS[mode]]
                    with evidence.operation('authoritative_snapshot'):
                        initial = fixture.snapshot(names)
                        validate_snapshot(initial, fixture, profile, packets, ground)
                    with evidence.operation('outside_boundary_move'):
                        movement = network.verify_outside_move(names, initial)
                    with evidence.operation('reconnect_ground'):
                        replay = network.reconnect_ground(0)
                        require(replay == packets[0], 'Reconnect changed the original decorative scene')
                        restored = fixture.snapshot(names)
                        require(restored['match'] == initial['match'] and restored['ground_sha256'] == sha(replay),
                                'Reconnect replaced the authoritative checkpoint')
                    # Normal leave precedes potentially lengthy read-only HTTPS art audit.
                    network.leave()
                    network = None
                    with evidence.operation('selected_published_resource', scene=scene):
                        if scene not in resources:
                            resources[scene] = published_scene(HOST, manifest, scene, ground.width)
                    evidence.report['matches'].append(dict(profile=profile, mode=mode, match=initial['match'],
                        participants=len(names), bots=0, width=ground.width, height=ground.height,
                        brushes=sorted(set(ground.first_layer)), scene=scene, ground_sha256=sha(packets[0]),
                        resource=resources[scene], outside_move=movement, reconnect_stable=True))
                    evidence.flush()
        with evidence.operation('preservation_after'):
            evidence.report['preservation'] = fixture.preservation()
            evidence.report['postflight'] = fixture.remote(PREFLIGHT, fixture.ownership_payload())
        evidence.report.update(passed=True, completed=True)
    except BaseException as error:
        evidence.report['error'] = scrub(type(error).__name__+': '+str(error), fixture)
        evidence.report['failed_stage'] = evidence.report.get('last_failure_stage', evidence.report['current_stage'])
        if network:
            network.cleanup()
        evidence.report['completed'] = True
    finally:
        if network:
            network.close()
        evidence.flush()
        print(json.dumps(dict(passed=evidence.report['passed'], report=str(args.output),
                              matches_completed=len(evidence.report['matches']))), flush=True)
    return 0 if evidence.report['passed'] else 1


def supervise(args):
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host == HOST, 'Only the known hosted owned QA fixture is permitted')
    output = args.output or OUTPUT/('hosted-'+fixture.prefix+'-'+time.strftime('%Y%m%d-%H%M%S')+'.json')
    output = output.resolve()
    require(output.parent == OUTPUT.resolve() and not output.exists(), 'Use a fresh public diagnostic report in the approved folder')
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', '--fixture', str(args.fixture.resolve()),
               '--output', str(output), '--case-seconds', str(args.case_seconds),
               '--overall-seconds', str(args.overall_seconds), '--modes', *map(str, args.modes), '--cities', *args.cities]
    # No passwords are included in arguments. Termination can affect only the
    # exact child created here, never a server/native client/existing process.
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL)
    try:
        return child.wait(timeout=args.overall_seconds)
    except subprocess.TimeoutExpired:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        report = json.loads(output.read_text(encoding='utf-8')) if output.exists() else dict(passed=False, matches=[])
        report.update(passed=False, completed=True, supervisor_deadline_seconds=args.overall_seconds,
                      supervisor_terminated_only_own_child=True,
                      error='Overall owned QA process deadline exceeded; retained match may require normal owned cleanup')
        save(output, report)
        print(json.dumps(dict(passed=False, report=str(output), outer_deadline=True)), flush=True)
        return 1


def self_test():
    from tio.protocol.system_message import encode_shop_error, encode_current_town
    from tio.team_lobbies import TeamLobbies
    fixture = SimpleNamespace(host=HOST, names=['qs01234567'+c for c in 'abcdefgh'],
        passwords=['private-test-value']*8, credential_path='private-fixture.json')
    checks = 0
    error = f0_summary(encode_shop_error('Все участники должны подтвердить готовность'), fixture)
    require(error['command'] == 394 and error['rejected'] and 'готовность' in error['message'], 'F0 error decoder failed')
    checks += 1
    require(f0_summary(encode_current_town(3), fixture) == dict(command=98, arguments=1), 'Legitimate F0 was rejected')
    checks += 1
    require(f0_summary(b'\x9e', fixture) is None, 'Heartbeat became an error')
    checks += 1
    require('private-test-value' not in scrub('private-test-value', fixture), 'Credential scrub failed')
    checks += 1
    compile(PREFLIGHT, '<read-only owned preflight>', 'exec')
    checks += 1
    # Reproduce the real ready contract: all joins before consent succeeds;
    # a delayed final join after consent clears ready and rejects captain Start.
    q = TeamLobbies()
    a, b = q.create(0, 4, 0, 1), q.create(1, 4, 0, 1)
    for i in range(2, 8):
        q.join(a.identity if i % 2 == 0 else b.identity, i, 0, 1)
    for i in range(2, 8):
        q.set_ready(i, True)
    for i in (0, 1):
        q.set_ready(i, True)
        q.start(i)
    require(len(q.pairs()) == 1 and a.bots == b.bots == 0, 'Actual wall ready order failed')
    checks += 1
    q = TeamLobbies()
    a = q.create(0, 4, 0, 1)
    q.join(a.identity, 2, 0, 1);q.set_ready(2, True)
    q.join(a.identity, 4, 0, 1);q.set_ready(4, True)
    q.join(a.identity, 6, 0, 1);q.set_ready(6, True);q.set_ready(0, True)
    try:
        q.start(0)
    except ValueError as rejected:
        require('готовность' in str(rejected), 'Unexpected roster readiness rejection')
    else:
        raise AssertionError('Delayed join incorrectly preserved earlier consent')
    checks += 1
    with tempfile.TemporaryDirectory() as directory:
        evidence = Evidence(fixture, Path(directory)/'report.json', (4,), ('denver',))
        evidence.stage = 'captain_start'
        try:
            evidence.observe(0, encode_shop_error('private-test-value'))
        except NativeRejection:
            pass
        else:
            raise AssertionError('Native rejection did not fail fast')
        saved = evidence.path.read_text(encoding='utf-8')
        require('private-test-value' not in saved and 'payload' not in saved,
                'Private credential/raw payload leaked into evidence')
        checks += 1
        network = BoundedNetworkQA(fixture, evidence, 1)
        network.deadline = time.monotonic()-1
        try:
            network.check()
        except TimeoutError:
            checks += 1
        else:
            raise AssertionError('Expired monotonic deadline was accepted')
        network.close()
        require(not network.case.clients and not network.peers, 'Offline network unexpectedly created sockets')
        checks += 1
        evidence.expected_native_rejection = (0, 'Destination is blocked or outside grid')
        evidence.observe(0, encode_shop_error('Destination is blocked or outside grid'))
        require(evidence.report['native_messages'][-1]['expected_negative_check'], 'Expected boundary rejection was treated as a queue failure')
        checks += 1
        try:
            evidence.observe(0, encode_shop_error('здоровье1000/1015'))
        except NativeRejection:
            checks += 1
        else:
            raise AssertionError('Expected movement-error scope hid a health rejection')
        class OwnFakeSocket:
            def __init__(self): self.shutdowns, self.closes = 0, 0
            def shutdown(self, mode):
                require(mode == socket.SHUT_RDWR, 'Wrong owned recv interruption')
                self.shutdowns += 1
            def close(self): self.closes += 1
        network = BoundedNetworkQA(fixture, evidence, 1)
        own = OwnFakeSocket()
        unrelated = OwnFakeSocket()
        network.case.clients.append(own)
        network.expire()
        network.close()
        require(own.shutdowns == own.closes == 1 and unrelated.shutdowns == unrelated.closes == 0,
                'Deadline failed to isolate its own sockets')
        checks += 1
    print(json.dumps(dict(offline_self_test='passed', checks=checks, server_contacted=False,
                          accounts_created=0, game_connections_created=0)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--modes', nargs='+', type=int, choices=(0, 1, 4), default=(0, 1, 4))
    parser.add_argument('--cities', nargs='+', choices=tuple(PROFILES), default=tuple(PROFILES))
    parser.add_argument('--case-seconds', type=int, default=90)
    parser.add_argument('--overall-seconds', type=int, default=600)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    require(args.fixture is not None, 'An existing ignored private QA fixture is required; this tool cannot create accounts')
    require(1 <= args.case_seconds <= 90 and 1 <= args.overall_seconds <= 600,
            'TCP case/own-process deadline cannot exceed90/600 seconds')
    require(len(args.modes) == len(set(args.modes)) and len(args.cities) == len(set(args.cities)), 'Duplicate QA cases')
    if args.worker:
        require(args.output is not None and args.output.resolve().parent == OUTPUT.resolve() and not args.output.exists(),
                'Invalid/existing worker report destination')
        return worker(args)
    return supervise(args)


if __name__ == '__main__':
    raise SystemExit(main())
