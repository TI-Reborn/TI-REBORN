"""Observe genuinely clean launcher installs using only proven-owned QA logins.

The ordinary launcher must install and start the client first. This helper
adopts only the two dedicated new-player roots; it does not install, start,
configure, provision, create/select characters, or enter the world. Explicit
connect controls use the established native authentication adapter. Character
creation, appearance, city and battle actions remain in the visible game UI.
Import and --help perform no network or process operations. Runtime ownership
verification reads the prior hosted backup and current salted account digests.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.hosted_graphical_qa_bridge import HostedGraphicalQaBridge, HASHES, SPANS, validate_native_binary
from tools.hosted_tls_graphical_qa import native_source, require
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP

REPORTS = ROOT / 'reports/new-player'
LAUNCHER_SHA256 = '8a34ea68124eebfb6ded5f2c9d8c96dee85befb9eb99b5efb57d5dea708b4d52'
LAUNCHER_BYTES = 118679712
PRIVATE_CONTROL_KEYS = {'password', 'login', 'credentials', 'token', 'email'}


def own_root(copy):
    require(copy in ('a', 'b'), 'Only the two owned new-player copies are accepted')
    root = (REPORTS / ('client-' + copy)).resolve()
    require(root.parent == REPORTS.resolve(), 'New-player client root escaped its report folder')
    return root


def published_launcher(path):
    path = Path(path).resolve()
    require(path.is_file() and path.stat().st_size == LAUNCHER_BYTES,
            'Expected the exact published self-contained 0.1.3 launcher')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    require(digest == LAUNCHER_SHA256, 'Published launcher SHA256 differs')
    return path


def new_player_static_guards(root):
    """Keep the established binary/function guards, accepting pristine seeds.

    The published config.cfg seed has no orange_addr; autoexec.cfg supplies it.
    Reading the effective pair preserves the normal first-install defaults.
    """
    import pefile
    root = Path(root).resolve()
    require(root in {own_root('a'), own_root('b')} and (root / '.tio-owned-qa').is_file(),
            'Only explicitly owned clean installs can be observed')
    require(not any(path.exists() for path in (root / 'login.ini', root / 'base/login.ini')),
            'Clean QA roots must not contain stored native credentials')
    for name in HASHES:
        validate_native_binary(name, (root / name).read_bytes())
    addresses, ports = [], []
    for name in ('autoexec.cfg', 'config.cfg'):
        text = (root / 'base' / name).read_text(encoding='cp1251')
        addresses.extend(re.findall(r'^\s*orange_addr\s+(\S+)', text, re.M))
        ports.extend(re.findall(r'^\s*orange_port\s+(\S+)', text, re.M))
    require(addresses and set(addresses) == {'185.184.42.88'} and ports and set(ports) == {'28512'},
            'Clean install effective initial endpoint differs from the published seeds')
    pe = pefile.PE(str(root / 'silver.dll'))
    guards = []
    try:
        for name, va, size, expected in SPANS:
            data = pe.get_data(va - 0x400000, size)
            require(hashlib.sha256(data).hexdigest() == expected, 'Native function changed: ' + name)
            relocations = []
            for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', ()):
                for entry in block.entries:
                    offset = entry.rva - (va - 0x400000)
                    if 0 <= offset < 12:
                        require(entry.type == 3 and offset + 4 <= 12, 'Unsupported native entry relocation')
                        relocations.append(offset)
            guards.append(dict(name=name, va=va, entry12=data[:12].hex(), entry_relocations=relocations))
    finally:
        pe.close()
    return guards


def game_in_bridge_job(game_pid, bridge_pid):
    """Prove membership in a job handle owned by this specific TLS helper."""
    require(os.name == 'nt' and ctypes.sizeof(ctypes.c_void_p) == 8,
            'Live launcher ownership requires 64-bit Windows Python')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    native = ctypes.WinDLL('ntdll')
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                      ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                      wintypes.BOOL, wintypes.DWORD)
    kernel.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    native.NtQuerySystemInformation.argtypes = (wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
                                               ctypes.POINTER(wintypes.ULONG))
    native.NtQuerySystemInformation.restype = ctypes.c_long

    class HandleEntry(ctypes.Structure):
        _fields_ = [('object', ctypes.c_void_p), ('pid', ctypes.c_size_t),
                    ('handle', ctypes.c_size_t), ('access', wintypes.ULONG),
                    ('backtrace', wintypes.USHORT), ('type_index', wintypes.USHORT),
                    ('attributes', wintypes.ULONG), ('reserved', wintypes.ULONG)]

    game = kernel.OpenProcess(0x1000, False, game_pid)
    bridge = kernel.OpenProcess(0x0040, False, bridge_pid)
    try:
        require(game and bridge, 'Cannot inspect the owned game/helper job')
        length = 65536
        for _ in range(12):
            require(length <= 32 * 1024 * 1024, 'System handle table exceeds the inspection bound')
            buffer = ctypes.create_string_buffer(length)
            needed = wintypes.ULONG()
            status = native.NtQuerySystemInformation(64, buffer, length, ctypes.byref(needed))
            if status == 0:
                break
            require(status == -1073741820, 'Cannot inspect live helper job handles')
            length = max(length * 2, needed.value + 65536)
        else:
            raise ValueError('System handle table changed beyond the inspection bound')
        count = ctypes.c_size_t.from_buffer(buffer).value
        offset, size = 2 * ctypes.sizeof(ctypes.c_size_t), ctypes.sizeof(HandleEntry)
        require(count <= (length - offset) // size, 'Unexpected system handle table size')
        own = [HandleEntry.from_buffer_copy(buffer, offset + i * size)
               for i in range(count)
               if HandleEntry.from_buffer(buffer, offset + i * size).pid == bridge_pid]
        require(len(own) <= 4096, 'TLS helper handle count exceeds the inspection bound')
        for entry in own:
            duplicate = wintypes.HANDLE()
            if not kernel.DuplicateHandle(bridge, entry.handle, kernel.GetCurrentProcess(),
                                          ctypes.byref(duplicate), 0, False, 2):
                continue
            try:
                inside = wintypes.BOOL()
                if kernel.IsProcessInJob(game, duplicate, ctypes.byref(inside)) and inside.value:
                    return True
            finally:
                kernel.CloseHandle(duplicate)
        return False
    finally:
        if game:
            kernel.CloseHandle(game)
        if bridge:
            kernel.CloseHandle(bridge)


def live_readiness(root, launcher):
    """Read a GUI-started game/helper pair, without inventing a CLI ready record."""
    # Fixed, credential-free PowerShell. Paths/command lines are parsed as data.
    code = ("$gameRows=@(Get-CimInstance Win32_Process -Filter \"Name='ti.exe'\" | "
            "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine); "
            "$helperRows=@(Get-CimInstance Win32_Process -Filter \"Name='TIO Launcher.exe'\" | "
            "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine); "
            "$listeners=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object LocalAddress,LocalPort,OwningProcess); "
            "[pscustomobject]@{Games=$gameRows;Helpers=$helperRows;Listeners=$listeners} | "
            "ConvertTo-Json -Depth 5 -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                            capture_output=True, text=True, timeout=25)
    require(result.returncode == 0, 'Cannot inspect the GUI-started native client')
    actual = json.loads(result.stdout)
    games = [row for row in actual['Games'] if row.get('ExecutablePath') and
             Path(row['ExecutablePath']).resolve() == (root / 'ti.exe').resolve()]
    require(len(games) == 1, 'Expected exactly one live game in this clean owned root')
    game = games[0]
    helpers = [row for row in actual['Helpers'] if row['ProcessId'] == game['ParentProcessId'] and
               row.get('ExecutablePath') and Path(row['ExecutablePath']).resolve() == launcher]
    require(len(helpers) == 1, 'Owned game parent is not the exact published launcher helper')
    helper = helpers[0]
    # ProcessStartInfo.ArgumentList uses ordinary Windows quoting for these
    # fixed, quote-free paths. Accept only the authored hidden child invocation.
    quoted_exe = '(?:"' + re.escape(str(launcher)) + '"|' + re.escape(str(launcher)) + ')'
    quoted_root = '(?:"' + re.escape(str(root)) + '"|' + re.escape(str(root)) + ')'
    require(re.fullmatch(quoted_exe + r'\s+--tls-game\s+' + quoted_root +
                         r'\s+TIO\.TLS\.[0-9a-f]{32}\s+(?:player|qa)',
                         helper.get('CommandLine') or '', re.I),
            'Unexpected TLS helper command line/root/pipe profile')
    listeners = [row for row in actual['Listeners'] if row['OwningProcess'] == helper['ProcessId']]
    require(len(listeners) == 2 and all(row['LocalAddress'] == '127.0.0.1' and
            type(row['LocalPort']) is int and 1024 <= row['LocalPort'] <= 65535 for row in listeners),
            'Expected exactly two loopback listeners owned by the production helper')
    require(game_in_bridge_job(game['ProcessId'], helper['ProcessId']),
            'Game is not in a job owned by its actual TLS helper')
    # Discover each route's purpose from the exact live 40-byte thunk. The
    # shared adapter verifies the entire route again before credential allocation.
    import frida
    session = frida.get_local_device().attach(game['ProcessId'])
    script = None
    try:
        script = session.create_script(r"""
          rpc.exports = { ports() {
            const orange = Process.getModuleByName('orange.dll');
            const exported = orange.getExportByName('AaaAa');
            if(exported.sub(orange.base).toUInt32()!==0x118f || exported.readU8()!==0xe9)
              throw new Error('Unexpected production TLS export');
            const route=exported.add(5).add(exported.add(1).readS32());
            return {login:route.add(18).readU32(),session:route.add(25).readU32()};
          }};
        """)
        script.load()
        ports = script.exports_sync.ports()
    finally:
        if script:
            script.unload()
        session.detach()
    require(type(ports.get('login')) is int and type(ports.get('session')) is int and
            ports['login'] != ports['session'] and
            {ports['login'], ports['session']} == {row['LocalPort'] for row in listeners},
            'Live route ports do not match the production helper listeners')
    return dict(Pid=game['ProcessId'], BridgePid=helper['ProcessId'],
                LoginPort=ports['login'], SessionPort=ports['session'],
                Source='live ordinary launcher child, parent PID, helper job and loopback listeners',
                CertificatePreflightEvidence='exact published helper startup invariant; not a saved CLI result',
                HelperProfile='player' if helper['CommandLine'].endswith(' player') else 'qa')


def observational_source(login_port, session_port):
    source = native_source(login_port, session_port)
    before = '        if (!autoSelect) return;\n        try { selectOwnedCharacter(this.characterCount); }'
    after = ("        state.charactersLoaded = true;\n"
             "        state.characterCount = this.characterCount;\n"
             "        emit('native_character_list_observed', {count:this.characterCount, automatic_selection:false});\n"
             '        if (!autoSelect) return;\n        try { selectOwnedCharacter(this.characterCount); }')
    require(source.count(before) == 1, 'Established manual character-list observer changed unexpectedly')
    return source.replace(before, after)


class NewPlayerGraphicalQa(HostedGraphicalQaBridge):
    """Reuse guarded authentication RPCs with character/world automation disabled."""
    def __init__(self, root, credentials, ready, *, on_event=None):
        import frida
        self.root = Path(root).resolve()
        require(self.root in {own_root('a'), own_root('b')}, 'Only clean new-player roots can be adopted')
        guards = new_player_static_guards(self.root)
        require(credentials.get('fresh_qa') is True and
                re.fullmatch(r'qs[a-f0-9]{8}[ab]', credentials.get('login', '')),
                'Only proven-owned portal QA credentials are accepted')
        require(re.fullmatch(r'[!-~]{12,64}', credentials.get('password', '')), 'Unsupported QA password')
        self.pid, self.bridge_pid = ready['Pid'], ready['BridgePid']
        self.events, self._runtime_errors = [], []
        self._on_event, self.window_script, self.closed = on_event, None, False
        self.device = frida.get_local_device()
        self.session = self.device.attach(self.pid)
        self.script = self.session.create_script(observational_source(ready['LoginPort'], ready['SessionPort']))

        def receive(message, data):
            if message.get('type') != 'send':
                self._runtime_errors.append(message.get('type', 'unknown'))
                self._record(dict(event='bridge_runtime_error', type=message.get('type', 'unknown')))
            elif isinstance(message.get('payload'), dict):
                self._record(message['payload'])

        try:
            self.script.on('message', receive)
            self.script.load()
            self.script.exports_sync.initialize(dict(executable=str(self.root / 'ti.exe'),
                silver_path=str(self.root / 'silver.dll'), entry_guards=guards,
                login=credentials['login'], password=credentials['password'], auto_select=False,
                loopback_login_port=ready['LoginPort'], loopback_session_port=ready['SessionPort']))
            from tools.window_compat import install
            self.window_script = install(self.session, receive)
            from tools.new_player_action_observer import source as action_source
            self.action_script = self.session.create_script(action_source(self.root))
            self.action_script.on('message', receive)
            self.action_script.load()
        except BaseException:
            self.session.detach()
            raise
        self._record(dict(event='clean_launcher_client_attached', pid=self.pid, bridge_pid=self.bridge_pid,
                          login_port=ready['LoginPort'], session_port=ready['SessionPort'],
                          character_automation=False, world_automation=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    parser.add_argument('--copies', nargs='+', choices=('a', 'b'), default=['a'])
    parser.add_argument('--seconds', type=int, default=3600)
    parser.add_argument('--check-only', action='store_true', help='Verify live ownership; do not allocate credentials or connect')
    args = parser.parse_args(argv)
    require(1 <= args.seconds <= 7200 and len(args.copies) == len(set(args.copies)), 'Invalid bounded observation/copies')
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host == '185.184.42.88' and len(fixture.names) == 2,
            'Exactly two new owned portal accounts on the known hosting server are required')
    launcher = published_launcher(args.launcher)
    ready = {}
    for copy in args.copies:
        root = own_root(copy)
        new_player_static_guards(root)
        ready[copy] = live_readiness(root, launcher)
    require(len({r['Pid'] for r in ready.values()}) == len(ready) and
            len({r['BridgePid'] for r in ready.values()}) == len(ready), 'Owned native clients/helpers must be independent')
    if args.check_only:
        print(json.dumps(dict(check_only=True, live_clients_verified=len(ready),
                              credentials_allocated=False, authentication_started=False, hosted_server_contacted=False)))
        return 0
    fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload())
    run_dir = REPORTS / 'native-runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    run_dir.mkdir(parents=True)
    controls, events = run_dir / 'controls.jsonl', run_dir / 'events.jsonl'
    controls.write_text('', encoding='utf-8')
    attached, commands = {}, queue.Queue()

    def record(value):
        value = dict(observed_utc=datetime.now(timezone.utc).isoformat(), **value)
        with events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        print(json.dumps(value, ensure_ascii=False), flush=True)

    def adopt(copy):
        require(copy not in attached, 'Copy is already attached')
        root = own_root(copy)
        new_player_static_guards(root)
        fresh = live_readiness(root, launcher)
        require(all(fresh['Pid'] != client.pid and fresh['BridgePid'] != client.bridge_pid
                    for client in attached.values()), 'Cannot adopt another active owned copy')
        fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload())
        index = ord(copy) - ord('a')
        attached[copy] = NewPlayerGraphicalQa(root,
            dict(login=fixture.names[index], password=fixture.passwords[index], fresh_qa=True), fresh,
            on_event=lambda value: record(dict(copy=copy, **value)))
        ready[copy] = fresh
        (run_dir / (copy + '-readiness.json')).write_text(json.dumps(fresh, indent=2) + '\n', encoding='utf-8')
        record(dict(event='fresh_clean_native_client_attached', copy=copy, pid=fresh['Pid'],
                    bridge_pid=fresh['BridgePid'], auth_connect_started=False, helper_profile=fresh['HelperProfile']))

    def reader():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line))
            except Exception:
                commands.put(dict(action='invalid'))
    threading.Thread(target=reader, daemon=True).start()
    offset = 0
    try:
        for copy in args.copies:
            adopt(copy)
        record(dict(event='ready_for_new_player_gui_validation', control_file=str(controls), run_dir=str(run_dir),
                    native_clients=len(attached), credentials_printed=False, config_mutations=0,
                    characters_created_by_helper=0, character_selection_automatic=False))
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
            if not isinstance(command, dict) or PRIVATE_CONTROL_KEYS & set(command):
                record(dict(event='invalid_control'))
                continue
            action, copy = command.get('action'), command.get('copy', 'a')
            if action == 'cleanup':
                break
            if copy not in ('a', 'b'):
                record(dict(event='invalid_copy'))
                continue
            if action in ('attach-client', 'reconnect'):
                if copy in attached:
                    record(dict(event='close_owned_client_before_reattach', copy=copy))
                else:
                    adopt(copy)
                continue
            if copy not in attached:
                record(dict(event='copy_not_attached', copy=copy))
                continue
            client = attached[copy]
            if action == 'close-client':
                client.release(cleanup=True)
                del attached[copy]
                record(dict(event='owned_clean_native_client_closed', copy=copy, pid=client.pid,
                            native_leave_requested=False, server_checkpoint_cleanup_requested=False))
            elif action in ('connect', 'connect-progress'):
                result = client.start_connect_with_progress() if action == 'connect-progress' else client.start_connect()
                record(dict(event='assisted_native_auth_connect_returned', copy=copy, result=result))
            elif action == 'selectserver':
                record(dict(event='assisted_native_server_selection_returned', copy=copy, result=client.select_server()))
            elif action == 'status':
                value = dict(event='status', copy=copy, state=client.status())
                (run_dir / (copy + '-status.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                record(value)
            elif action == 'mark':
                label = command.get('label', '')
                require(isinstance(label, str) and re.fullmatch(r'[a-z0-9-]{1,64}', label), 'Use a short public stage label')
                record(dict(event='visual_stage', copy=copy, label=label))
            else:
                record(dict(event='invalid_control'))
    finally:
        for client in attached.values():
            client.release(cleanup=True)
        record(dict(event='owned_clean_clients_closed', count=len(attached), config_mutations=0,
                    helper_lifetime_cleanup='production helper observes own game exit'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Frida errors may contain private arguments. Never emit their text.
        print(json.dumps(dict(event='new_player_validation_failed', error_type=type(error).__name__)), file=sys.stderr)
        raise SystemExit(1)
