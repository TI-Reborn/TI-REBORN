"""Attach observation/owned credentials to production-launcher TLS QA clients.

The launcher starts each real native client via --tls-qa-start and verifies both
TLS endpoints before publishing its readiness file. This adapter never starts
an alternate transport, modifies auth results, fabricates packets, or changes
configuration. It checks the live loopback listeners and production ORANGE
route before placing only proven-owned QA credentials in the native heap.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.hosted_graphical_qa_bridge import HostedGraphicalQaBridge, static_guards
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP

REPORTS = ROOT / 'reports/game-tls'
QA_BASE = ROOT / 'reports/arena-surroundings-implementation/client-qa'


def require(value, message):
    if not value:
        raise ValueError(message)


def readiness(status_path, root, launcher):
    status_path = Path(status_path).resolve()
    require(status_path.is_relative_to(REPORTS.resolve()), 'Readiness file must belong to this TLS QA report folder')
    value = json.loads(status_path.read_text(encoding='utf-8'))
    require(set(value) <= {'Pid', 'BridgePid', 'LoginPort', 'SessionPort', 'EndpointCertificatesValidated', 'Error'} and
            value.get('Error') is None and value.get('EndpointCertificatesValidated') is True,
            'Launcher readiness must confirm certificate preflight without unsupported fields')
    require(all(type(value.get(key)) is int for key in ('Pid', 'BridgePid', 'LoginPort', 'SessionPort')),
            'Invalid launcher readiness types')
    require(value['Pid'] > 0 and value['BridgePid'] > 0 and value['Pid'] != value['BridgePid'],
            'Distinct game and bridge PIDs are required')
    require(all(1024 <= value[key] <= 65535 for key in ('LoginPort', 'SessionPort')) and
            value['LoginPort'] != value['SessionPort'], 'Invalid loopback listener ports')
    # Public integers only. No credentials, shell substitutions or private data.
    code = (f"$gameInfo=Get-Process -Id {value['Pid']} -ErrorAction Stop; "
            f"$bridgeInfo=Get-Process -Id {value['BridgePid']} -ErrorAction Stop; "
            f"$listeners=Get-NetTCPConnection -State Listen -LocalPort {value['LoginPort']},{value['SessionPort']} -ErrorAction Stop; "
            "[pscustomobject]@{Game=$gameInfo.Path; Bridge=$bridgeInfo.Path; "
            "Listeners=@($listeners | Select-Object LocalAddress,LocalPort,OwningProcess)} | ConvertTo-Json -Depth 5 -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                            text=True, capture_output=True, timeout=20)
    require(result.returncode == 0, 'Cannot verify the live owned TLS bridge')
    actual = json.loads(result.stdout)
    require(Path(actual['Game']).resolve() == (root / 'ti.exe').resolve(), 'Readiness PID belongs to a different game')
    require(Path(actual['Bridge']).resolve() == launcher.resolve(), 'Listener bridge is not the expected launcher executable')
    listeners = actual['Listeners']
    require(len(listeners) == 2 and {r['LocalPort'] for r in listeners} == {value['LoginPort'], value['SessionPort']},
            'Unexpected local listener set')
    require(all(r['LocalAddress'] == '127.0.0.1' and r['OwningProcess'] == value['BridgePid'] for r in listeners),
            'Loopback listeners do not belong to this verified bridge')
    return value


ROUTE_GUARD = r'''
    // Observe the exact production route thunk before credential allocation.
    const routeOrange = Process.getModuleByName('orange.dll');
    const exportConnect = routeOrange.getExportByName('AaaAa');
    if(exportConnect.sub(routeOrange.base).toUInt32()!==0x118f || exportConnect.readU8()!==0xe9)
      throw new Error('Unexpected production ORANGE route export');
    const route = exportConnect.add(5).add(exportConnect.add(1).readS32());
    const original = route.add(40).add(route.add(36).readS32());
    const routeHost = route.add(6).readPointer();
    if(!routeHost.equals(route.add(128))&&!routeHost.equals(route.add(256)))
      throw new Error('Unexpected production loopback string location');
    const u32bytes = value => [value&255,(value>>>8)&255,(value>>>16)&255,(value>>>24)&255];
    const expectedRoute = [0x9c,0x50,0xc7,0x44,0x24,0x0c,
      ...u32bytes(routeHost.toUInt32()),0x8b,0x44,0x24,0x18,0x83,0xf8,0,0xb8,
      ...u32bytes(configuration.loopback_login_port),0x74,0x05,0xb8,
      ...u32bytes(configuration.loopback_session_port),0x89,0x44,0x24,0x10,0x58,0x9d,0xe9,
      ...u32bytes((original.toUInt32()-route.add(40).toUInt32())>>>0)];
    if(hex(route,40)!==expectedRoute.map(v=>v.toString(16).padStart(2,'0')).join('') ||
       routeHost.readUtf8String()!=='127.0.0.1')
      throw new Error('Production native TLS route bytes differ');
    const signature = 'a0f5509b0c84c074238b0df0509b0c85c974198b4424108b54240c508b44240c528b54240c5052e8'
      .match(/../g).map(v=>parseInt(v,16));
    const actualOriginal = new Uint8Array(original.readByteArray(signature.length));
    for(let i=0;i<signature.length;i++)
      if(!(i>=1&&i<=4)&&!(i>=11&&i<=14)&&signature[i]!==actualOriginal[i])
        throw new Error('Production route original target differs');
    emit('production_native_tls_route_verified',{loopback_host:'127.0.0.1',
      login_port:configuration.loopback_login_port,session_port:configuration.loopback_session_port,
      export_rva:0x118f,route_bytes_verified:40});
'''


def native_source(login_port, session_port):
    source = (ROOT / 'tools/hosted_graphical_qa_bridge.js').read_text(encoding='utf-8')
    replacements = (
        ("const EXPECTED_HOST = '185.184.42.88';", "const EXPECTED_HOST = '127.0.0.1';"),
        ('const EXPECTED_SESSION_PORT = 28513;', f'const EXPECTED_SESSION_PORT = {session_port};'),
        ('nativeConnect(Memory.allocUtf8String(EXPECTED_HOST), 28512, ptr(0), 0);',
         f'nativeConnect(Memory.allocUtf8String(EXPECTED_HOST), {login_port}, ptr(0), 0);'),
        ("const kernel = Process.getModuleByName('kernel32.dll');", ROUTE_GUARD + "\n    const kernel = Process.getModuleByName('kernel32.dll');"),
    )
    for before, after in replacements:
        require(source.count(before) == 1, 'Established native QA source changed unexpectedly')
        source = source.replace(before, after)
    require(source.count('port: 28512') == 2, 'Established native initial endpoint metadata changed')
    return source.replace('port: 28512', f'port: {login_port}')


class AttachedTlsGraphicalQa(HostedGraphicalQaBridge):
    """Reuse existing guarded native RPCs, attached only to a launcher-owned PID."""
    def __init__(self, root, credentials, ready, *, on_event=None, auto_select=True):
        import frida
        self.root = Path(root).resolve()
        guards = static_guards(self.root)
        require(credentials.get('fresh_qa') is True and
                re.fullmatch(r'qs[a-f0-9]{8}[ab]', credentials.get('login', '')), 'Only owned fixture QA credentials are accepted')
        require(re.fullmatch(r'[!-~]{12,64}', credentials.get('password', '')), 'Unsupported private QA password')
        self.pid, self.bridge_pid = ready['Pid'], ready['BridgePid']
        self.events, self._runtime_errors = [], []
        self._on_event, self.window_script, self.closed = on_event, None, False
        self.device = frida.get_local_device()
        self.session = self.device.attach(self.pid)
        self.script = self.session.create_script(native_source(ready['LoginPort'], ready['SessionPort']))
        def receive(message, data):
            if message.get('type') != 'send':
                self._runtime_errors.append(message.get('type', 'unknown'))
                self._record(dict(event='bridge_runtime_error', type=message.get('type', 'unknown')))
                return
            payload = message.get('payload')
            if isinstance(payload, dict):
                self._record(payload)
        self.script.on('message', receive)
        self.script.load()
        self.script.exports_sync.initialize(dict(executable=str(self.root / 'ti.exe'),
            silver_path=str(self.root / 'silver.dll'), entry_guards=guards,
            login=credentials['login'], password=credentials['password'], auto_select=auto_select,
            loopback_login_port=ready['LoginPort'], loopback_session_port=ready['SessionPort']))
        from tools.window_compat import install
        self.window_script = install(self.session, receive)
        self._record(dict(event='production_launcher_client_attached', pid=self.pid,
                          bridge_pid=self.bridge_pid, login_port=ready['LoginPort'], session_port=ready['SessionPort']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    parser.add_argument('--status-a', type=Path, required=True)
    parser.add_argument('--status-b', type=Path)
    parser.add_argument('--seconds', type=int, default=3600)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--menu-only', action='store_true', help='Keep native server/character selection manual')
    args = parser.parse_args()
    require(1 <= args.seconds <= 7200, 'Observation limit must be 1..7200 seconds')
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host == '185.184.42.88', 'Unexpected hosted QA fixture target')
    copies = {'a': args.status_a}
    if args.status_b:
        copies['b'] = args.status_b
    ready = {}
    for copy, status in copies.items():
        root = (QA_BASE / ('game-' + copy)).resolve()
        static_guards(root)
        ready[copy] = readiness(status, root, args.launcher)
    require(len({r['Pid'] for r in ready.values()}) == len(ready) and
            len({r['BridgePid'] for r in ready.values()}) == len(ready), 'QA clients must be independent processes/bridges')
    if args.check_only:
        print(json.dumps(dict(check_only=True, own_clients_verified=len(ready), credentials_printed=False)))
        return 0
    fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload())
    run_dir = REPORTS / 'native-runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    run_dir.mkdir(parents=True)
    controls = run_dir / 'controls.jsonl'
    controls.write_text('', encoding='utf-8')
    events = run_dir / 'events.jsonl'
    attached = {}
    def record(value):
        value = dict(observed_utc=datetime.now(timezone.utc).isoformat(), **value)
        with events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        print(json.dumps(value, ensure_ascii=False), flush=True)
    commands = queue.Queue()
    def reader():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line))
            except Exception:
                commands.put(dict(action='invalid'))
    threading.Thread(target=reader, daemon=True).start()
    offset = 0
    try:
        for copy, status in ready.items():
            index = ord(copy) - ord('a')
            attached[copy] = AttachedTlsGraphicalQa(QA_BASE / ('game-' + copy),
                dict(login=fixture.names[index], password=fixture.passwords[index], fresh_qa=True), status,
                auto_select=not args.menu_only, on_event=lambda value, copy=copy: record(dict(copy=copy, **value)))
        record(dict(event='ready_for_tls_native_validation', control_file=str(controls), run_dir=str(run_dir),
            native_clients=len(attached), transport='production launcher TLS bridge',
            credentials_printed=False, config_mutations=0))
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            with controls.open('r', encoding='utf-8') as stream:
                stream.seek(offset)
                while True:
                    line = stream.readline()
                    if not line or not line.endswith('\n'):
                        break
                    try:
                        commands.put(json.loads(line))
                    except Exception:
                        commands.put(dict(action='invalid'))
                    offset = stream.tell()
            try:
                command = commands.get(timeout=.25)
            except queue.Empty:
                continue
            action, copy = command.get('action'), command.get('copy', 'a')
            if action == 'cleanup':
                break
            if action == 'attach-client':
                if copy not in ready or copy in attached:
                    record(dict(event='invalid_attach_copy', copy=copy))
                    continue
                root = (QA_BASE / ('game-' + copy)).resolve()
                fresh = readiness(Path(command.get('status_file', '')), root, args.launcher)
                require(fresh['Pid'] != ready[copy]['Pid'] and fresh['BridgePid'] != ready[copy]['BridgePid'],
                        'Reconnect requires fresh production game and bridge PIDs')
                require(all(fresh['Pid'] != client.pid and fresh['BridgePid'] != client.bridge_pid
                            for client in attached.values()), 'Reconnect would adopt another active QA process')
                fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload())
                index = ord(copy) - ord('a')
                attached[copy] = AttachedTlsGraphicalQa(root,
                    dict(login=fixture.names[index], password=fixture.passwords[index], fresh_qa=True), fresh,
                    auto_select=not args.menu_only,
                    on_event=lambda value, copy=copy: record(dict(copy=copy, **value)))
                ready[copy] = fresh
                record(dict(event='fresh_native_client_attached', copy=copy, pid=fresh['Pid'],
                            bridge_pid=fresh['BridgePid'], auth_connect_started=False))
                continue
            if copy not in attached:
                record(dict(event='invalid_copy'))
                continue
            client = attached[copy]
            if action == 'close-client':
                client.release(cleanup=True)
                del attached[copy]
                record(dict(event='owned_native_client_closed', copy=copy, pid=client.pid,
                            bridge_pid=client.bridge_pid, native_leave_requested=False,
                            server_checkpoint_cleanup_requested=False))
            elif action in ('connect', 'connect-progress'):
                result = client.start_connect_with_progress() if action == 'connect-progress' else client.start_connect()
                record(dict(event='connect_returned', copy=copy, result=result))
            elif action == 'selectserver':
                record(dict(event='selectserver_returned', copy=copy, result=client.select_server()))
            elif action == 'status':
                state = client.status()
                value = dict(event='status', copy=copy, state=state)
                (run_dir / (copy + '-status.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                record(value)
            elif action == 'mark':
                label = command.get('label', '')
                require(re.fullmatch(r'[a-z0-9-]{1,64}', label), 'Use a short public stage label')
                record(dict(event='visual_stage', copy=copy, label=label))
            else:
                record(dict(event='invalid_control'))
    finally:
        for client in attached.values():
            client.release(cleanup=True)
        record(dict(event='owned_clients_closed', count=len(attached), config_mutations=0,
                    native_bridge_lifetime_cleanup='production helper observes own game exit'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Frida errors/arguments can contain credentials. Never emit their text.
        print(json.dumps(dict(event='tls_native_validation_failed', error_type=type(error).__name__)), file=sys.stderr)
        raise SystemExit(1)
