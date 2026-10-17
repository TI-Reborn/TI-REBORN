"""Own two graphical clients against a private SQLite copy and loopback only.

Uses genuine native transport/authentication with local disposable test accounts.
Does not type authentication dialogs, fabricate responses or connect to hosting.
Window inspection/input is performed separately through the computer-use skill.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import socket
import sqlite3
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hosted_graphical_qa_bridge import SPANS, HostedGraphicalQaBridge
from tools.prepare_contracts_local import safe_config
from tools.prepare_contracts_local import atomic
from tools.prepare_contracts_city_local import verify_client


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def guards(root):
    import pefile
    result = []
    with pefile.PE(str(root / 'silver.dll')) as pe:
        for name, va, size, expected in SPANS:
            data = pe.get_data(va - 0x400000, size)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Authentication entry changed: ' + name)
            offsets = [entry.rva - (va - 0x400000)
                       for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
                       if entry.type == 3 and 0 <= entry.rva - (va - 0x400000) <= 8]
            result.append(dict(name=name, va=va, entry12=data[:12].hex(), entry_relocations=offsets))
    return result


def local_script():
    source = (ROOT / 'tools/hosted_graphical_qa_bridge.js').read_text(encoding='utf-8')
    assert source.count("const EXPECTED_HOST = '185.184.42.88';") == 1
    source = source.replace("const EXPECTED_HOST = '185.184.42.88';", "const EXPECTED_HOST = '127.0.0.1';")
    source = source.replace("!/^q[a-z][a-f0-9]{8}[ab]$/.test(configuration.login)",
                            "!/^contract_[ab]$/.test(configuration.login)")
    source = source.replace('ownedLogin = configuration.login;', 'ownedLogin = configuration.character_name;')
    # Only the known two local fixtures may enter a character; never infer identity.
    needle = '    const kernel = Process.getModuleByName(\'kernel32.dll\');'
    assert needle in source
    source = source.replace(needle,
        "    if (configuration.character_name !== (configuration.login === 'contract_a' ? 'ContractA' : 'ContractB')) throw new Error('Unexpected local fixture');\n" + needle)
    assert '185.184.42.88' not in source
    return source


class LocalBridge(HostedGraphicalQaBridge):
    def __init__(self, root, secret, on_event):
        import frida
        self.root = root.resolve()
        verify_client(ROOT, self.root.relative_to(ROOT).as_posix())
        entries = guards(self.root)
        self.events, self._runtime_errors = [], []
        self._on_event, self.window_script, self.closed = on_event, None, False
        helper = ROOT / 'reports/contracts-local/clients/bin/TioContractsQaClient.exe'
        result = subprocess.run([str(helper), 'start', str(self.root), '--native-multi'],
                                capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError('Owned loopback loader failed')
        self.pid = int(json.loads(result.stdout.strip())['pid'])
        self.device = frida.get_local_device()
        try:
            self.session = self.device.attach(self.pid)
            self.script = self.session.create_script(local_script())
            def receive(message, _data):
                if message.get('type') != 'send':
                    self._runtime_errors.append(message.get('type', 'unknown'))
                    self._record(dict(event='bridge_runtime_error', type=message.get('type', 'unknown')))
                elif isinstance(message.get('payload'), dict):
                    self._record(message['payload'])
            self.script.on('message', receive)
            self.script.load()
            self.script.exports_sync.initialize(dict(
                executable=str(self.root / 'ti.exe'), silver_path=str(self.root / 'silver.dll'),
                entry_guards=entries, login=secret[0], password=secret[1],
                character_name=secret[2], auto_select=True))
            from tools.window_compat import install
            self.window_script = install(self.session, receive)
        except BaseException:
            self.device.kill(self.pid)
            raise
        self._record(dict(event='owned_loopback_graphical_client_started', pid=self.pid, game_root=str(self.root)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('Seconds must be 1..3600')
    config = safe_config(ROOT, ROOT / 'config/contracts-local.toml')
    roots = {suffix: ROOT / ('reports/contracts-local/clients/game-' + suffix) for suffix in ('a', 'b')}
    for root in roots.values():
        verify_client(ROOT, root.relative_to(ROOT).as_posix())
        guards(root)
    local_script()
    if args.check_only:
        emit(dict(passed=True, check_only=True, clients=2, loopback_only=True))
        return 0
    # Refuse to share a listener with an unknown running server.
    for port in (28512, 28513):
        with closing(socket.socket()) as listener:
            listener.bind(('127.0.0.1', port))
    secrets = [line.split('\t') for line in (config.data_directory / 'LOCAL_TEST_ACCOUNTS.txt')
               .read_text(encoding='utf-8').splitlines() if line and not line.startswith('#')]
    assert [(row[0], row[2]) for row in secrets] == [('contract_a', 'ContractA'), ('contract_b', 'ContractB')]
    directory = ROOT / 'reports/contracts-local/city-ui/graphical' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')
    directory.mkdir(parents=True)
    data = directory / 'data'
    data.mkdir()
    with closing(sqlite3.connect(config.database)) as source, closing(sqlite3.connect(data / 'reservation.sqlite3')) as dest:
        source.backup(dest)
    profile = directory / 'server.toml'
    profile.write_text('bind_address="127.0.0.1"\nadvertised_address="127.0.0.1"\ngame_port=28512\nsession_port=28513\ndata_directory="data"\nlog_level="INFO"\nmulti_account=true\ncontracts_enabled=true\n', encoding='utf-8')
    events = (directory / 'events.jsonl').open('a', encoding='utf-8')
    server_log = (directory / 'server.log').open('w', encoding='utf-8')
    server = subprocess.Popen([sys.executable, '-m', 'server', '--config', str(profile)], cwd=ROOT,
                              stdout=server_log, stderr=subprocess.STDOUT)
    bridges = {}
    configurations = {root / 'base' / name: (root / 'base' / name).read_bytes()
                      for root in roots.values() for name in ('config.cfg', 'autoexec.cfg')}
    commands = queue.Queue()
    control = directory / 'controls.jsonl'
    control.touch()
    def read_commands():
        with control.open(encoding='utf-8') as stream:
            while server.poll() is None:
                line = stream.readline()
                if not line:
                    time.sleep(.1)
                    continue
                try:
                    commands.put(json.loads(line))
                except ValueError:
                    pass
    threading.Thread(target=read_commands, daemon=True).start()
    def record(copy, event):
        events.write(json.dumps(dict(copy=copy, **event), ensure_ascii=False) + '\n')
        events.flush()
        emit(dict(copy=copy, **event))
    try:
        until = time.monotonic() + 10
        while True:
            if server.poll() is not None:
                raise RuntimeError('Owned loopback server stopped')
            with closing(socket.socket()) as probe:
                if probe.connect_ex(('127.0.0.1', 28512)) == 0:
                    break
            if time.monotonic() > until:
                raise RuntimeError('Owned loopback server startup timed out')
            time.sleep(.1)
        for suffix, secret in zip(('a', 'b'), secrets):
            bridges[suffix] = LocalBridge(roots[suffix], secret, lambda event, suffix=suffix: record(suffix, event))
        secrets.clear()
        emit(dict(event='ready', directory=str(directory), controls=str(control), pids={key: value.pid for key, value in bridges.items()}))
        until = time.monotonic() + args.seconds
        while time.monotonic() < until:
            try:
                command = commands.get(timeout=.2)
            except queue.Empty:
                continue
            action, copy = command.get('action'), command.get('copy', 'a')
            if action == 'cleanup':
                break
            if copy not in bridges:
                continue
            if action == 'connect':
                bridges[copy].start_connect()
            elif action == 'status':
                record(copy, dict(event='status', state=bridges[copy].status()))
        states = {key: bridge.status() for key, bridge in bridges.items()}
        (directory / 'result.json').write_text(json.dumps(dict(
            scope='Owned native clients on a private loopback database; states show the observed progress.',
            graphical_client_processes_started=len(bridges),
            native_login_completed=sum(bool(state.get('authenticated')) for state in states.values()),
            native_world_entry_sent=sum(bool(state.get('worldStartSent')) for state in states.values()),
            native_states=states, hosted_connections=0, personal_or_primary_data_changed=False),
            ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    finally:
        for bridge in bridges.values():
            bridge.release(cleanup=True)
        # Native shutdown may persist display preferences; restore the exact
        # owned pre-run bytes so the prepared-client provenance remains valid.
        for path, original in configurations.items():
            atomic(path, data=original)
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        events.close()
        server_log.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        emit(dict(event='local_graphical_check_failed', error_type=type(error).__name__))
        raise SystemExit(1)
