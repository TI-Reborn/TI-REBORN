"""Own graphical clients, genuine hosted native authentication, secrets on stdin.

No startup occurs on import. This is a narrow, not-yet-runtime-validated QA
bridge, not the loopback diagnostic client. It never injects server packets or
modifies authentication results. Credentials live only in the own process's
native heap; the OS reclaims their buffers when that QA client closes.
"""
from __future__ import annotations

import argparse
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
HOST = '185.184.42.88'
HASHES = {
    'ti.exe': 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c',
    'orange.dll': '5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589',
    'silver.dll': '7137403658a66f8c9ee571960f29203bf6049d2722fa9719526049aec01670c1',
}
MENU_LAYOUT_SHA = '2d9e0f83b3ff94ef2c7ac5df2d396cd7b7a55a7ac03168c0ef252e977b75b359'


def accepted_native_hashes(name: str) -> set[str]:
    """Only the original release and its exact authored presentation variant."""
    values = {HASHES[name]}
    if name == 'silver.dll':
        values.add(MENU_LAYOUT_SHA)
        values.add('4897eb6d6af6beb587fc9b303dc6911519d90b3414ae8cca8fd1ffb698c1f082')
        values.add('efc655e70cdc1e414270f6e5a4651d4c2927e866c7ae878edb6d54cb118049bf')
        values.add('853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1')
        values.add('afaa457c06ba6223476bc6e53eeff9947e9291acbce19700bb10ed5c3b29bdad')
        values.add('9d24b8f13a2c2a07c0673f8f9165b9df9f76a45eaa8561415606b3854ca86302')
        values.add('8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b')
        values.add('e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80')
    return values


def validate_native_binary(name: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    if digest not in accepted_native_hashes(name):
        raise ValueError('Unsupported current client resource: ' + name)
    if name == 'silver.dll' and digest == 'e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80':
        from deploy.client_arena_browsing_visible import patch, review
        source = ROOT / 'reports/gameplay-completion/legacy-status-20261011/client-freshness/silver.dll'
        original = source.read_bytes()
        review(original, data)
        if patch(original) != data:
            raise ValueError('Browse visibility differs from exact reviewed composition')
    if name == 'silver.dll' and digest == '8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b':
        from deploy.client_arena_empty_roster_navigation import patch, review
        source = ROOT / 'reports/gameplay-completion/legacy-status-20261011/client-freshness/silver.dll'
        original = source.read_bytes()
        review(original, data)
        if patch(original) != data:
            raise ValueError('Actual Arena navigation differs from exact reviewed composition')
    if name == 'silver.dll' and digest == '9d24b8f13a2c2a07c0673f8f9165b9df9f76a45eaa8561415606b3854ca86302':
        from deploy.client_arena_lobby_search_status import patch, review
        source = ROOT / 'reports/gameplay-completion/legacy-status-20261011/client-freshness/silver.dll'
        original = source.read_bytes()
        review(original, data)
        if patch(original) != data:
            raise ValueError('Search-status client differs from exact reviewed composition')
    if name == 'silver.dll' and digest == 'afaa457c06ba6223476bc6e53eeff9947e9291acbce19700bb10ed5c3b29bdad':
        from deploy.client_arena_lobby_navigation import patch, review
        source = ROOT / 'reports/gameplay-completion/legacy-status-20261011/client-freshness/silver.dll'
        review(source.read_bytes(), data)
        if patch(source.read_bytes()) != data:
            raise ValueError('Navigation client differs from exact reviewed composition')
    if name == 'silver.dll' and digest == '853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1':
        from deploy.client_server_list_status import patch as status_patch
        from deploy.client_server_list_freshness import patch as freshness_patch
        source = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011/client/silver.dll'
        if freshness_patch(status_patch(source.read_bytes())) != data:
            raise ValueError('Final client differs from the reviewed presentation composition')
    if name == 'silver.dll' and digest == 'efc655e70cdc1e414270f6e5a4651d4c2927e866c7ae878edb6d54cb118049bf':
        from deploy.client_server_list_status import review
        source = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011/client/silver.dll'
        review(source.read_bytes(), data)
    if name == 'silver.dll' and digest == MENU_LAYOUT_SHA:
        # A new SHA alone does not waive code guards. Revert only the exact
        # authored presentation sites and prove every remaining byte is the
        # immutable prior release; rebuild and compare the entire candidate.
        import pefile
        from deploy.client_menu_interface import BASE_SHA, IMAGE_BASE, edit_specifications, patch
        if BASE_SHA != HASHES['silver.dll']:
            raise ValueError('Menu layout has an unexpected underlying release')
        pe = pefile.PE(data=data)
        restored = bytearray(data)
        try:
            for va, old, new, _ in edit_specifications():
                offset = pe.get_offset_from_rva(va-IMAGE_BASE)
                if data[offset:offset+len(new)] != new:
                    raise ValueError('Unexpected authored menu presentation bytes')
                restored[offset:offset+len(old)] = old
        finally:
            pe.close()
        previous = bytes(restored)
        if hashlib.sha256(previous).hexdigest() != BASE_SHA or patch(previous) != data:
            raise ValueError('Menu presentation patch changes unrelated native bytes')
    return digest
# Full static spans match the original native functions in the current .5 DLL.
# Live entry signatures account for the PE's recorded address relocations.
SPANS = (
    ('login_builder', 0x87c604, 332, '1fbe95e84adb3f042858909e640327632fe992c44c28df64dc1add5173d53011'),
    ('auth_result', 0x87ce60, 286, 'aa6d952e7684a357e7f02f5c4187809663b98f976f76f25661b93fbdb4262232'),
    ('server_list', 0x87d1cc, 124, 'e5d407a48d96e98ed5a88e66db9baf5c60cde6317bde892b655cdf59dd9db58a'),
    ('server_record', 0x71fea0, 160, '4dd1aa15ba0907fb447c6fa3a861010cbb95b4d3d95f5128bbc79eb360e15fdb'),
    ('server_select', 0x71e998, 241, '7b94a7ef2d0624bea505c7980542c7873b61142214202d0c30c5961f0e7f2982'),
    ('login_result', 0x87d00c, 128, '721e067c693dd7709758582a7bc720ffe719df1ef5d3a71efeab330e2faa624a'),
    ('server_login_result', 0x87d400, 64, 'e849d475a90ef227bd579431d9e0d959faa165c10e050cc41bf85d19aaad07e4'),
    ('game_auth1', 0x87d608, 64, '2f8a805a8d2d79233f2bb1b11b6aa5ac74932d3f348c2a74b6e4bad9a4c93572'),
    ('game_auth2', 0x87d8a4, 64, '97271252589a83c594bd82038bb7bd0f5644051c1c62a08c65e1b756488cba28'),
    ('character_list', 0x889eac, 1568, 'eceaa2e0cb6499b5ce283cc78e64814261d56f77e4e752ec08051ba22675a194'),
    ('character_select', 0x8a3108, 168, 'b68c6e186746d55b29252766bbe46e4679f308a28b1cbf2dc99046416a534d61'),
    ('character_select_result', 0x88a4cc, 652, 'd3f981f18c599b2ea927519dec7af6a598fc7d30e349634f9c41625f46cf0f9d'),
    ('world_start', 0x889e3c, 112, 'fa9082d5884e3e93a7063c2d81bd7022c6a82ac52dd4d924231e868c22f9fd00'),
    ('authorization_wait_show', 0x87ba24, 15, 'b2dc6625d215208a94cd61eddb50b03082fdd49904f2590f6ebc7661be2809f5'),
    ('authorization_wait_create', 0x87be58, 365, '058ceba628ca13f7514a55b029524cce26e5679ad1ed833599e2ea79f9506704'),
    ('authorization_wait_draw', 0x87bc04, 397, '49cd64d4d0d4ce83b8bb5e8b59529a5c1c8d3f605da5b5a8e29f3f86c3996848'),
)


def static_guards(game_root: Path) -> list[dict]:
    """Read/pin dedicated client resources without launching any process."""
    import pefile
    game_root = game_root.resolve()
    if not (game_root / '.tio-owned-qa').is_file():
        raise ValueError('A dedicated .tio-owned-qa marker is required')
    # A fresh copy must not inherit the player's stored login credentials.
    for path in (game_root / 'login.ini', game_root / 'base/login.ini'):
        if path.exists():
            raise ValueError('Remove inherited login.ini from the dedicated QA copy before first launch')
    for name in HASHES:
        validate_native_binary(name, (game_root / name).read_bytes())
    for name in ('autoexec.cfg', 'config.cfg'):
        text = (game_root / 'base' / name).read_text(encoding='cp1251')
        addresses = re.findall(r'^\s*orange_addr\s+(\S+)', text, re.M)
        ports = re.findall(r'^\s*orange_port\s+(\S+)', text, re.M)
        if not addresses or set(addresses) != {HOST} or not ports or set(ports) != {'28512'}:
            raise ValueError('QA client configuration must use the hosted initial endpoint')
    pe = pefile.PE(str(game_root / 'silver.dll'))
    result = []
    try:
        for name, va, size, expected in SPANS:
            data = pe.get_data(va - 0x400000, size)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Native function changed: ' + name)
            relocations = []
            for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', ()):
                for entry in block.entries:
                    offset = entry.rva - (va - 0x400000)
                    if 0 <= offset < 12:
                        if entry.type != 3 or offset + 4 > 12:
                            raise ValueError('Unsupported native entry relocation: ' + name)
                        relocations.append(offset)
            result.append(dict(name=name, va=va, entry12=data[:12].hex(),
                               entry_relocations=relocations))
    finally:
        pe.close()
    return result


class HostedGraphicalQaBridge:
    """Own PID returned by the unchanged guarded loader; explicit native RPCs."""

    def __init__(self, game_root: Path, credentials: dict, *, auto_select=False, helper=None, launcher=None, launcher_sha256=None, on_event=None):
        import frida
        self.root = Path(game_root).resolve()
        guards = static_guards(self.root)
        login = credentials.get('login', '')
        password = credentials.get('password', '')
        if credentials.get('fresh_qa') is not True or not re.fullmatch(r'q[a-z][a-f0-9]{8}[abcd]', login):
            raise ValueError('Only explicitly fresh randomly named QA credentials are accepted')
        if not re.fullmatch(r'[!-~]{12,64}', password):
            raise ValueError('QA password format is unsupported')
        self.helper = Path(helper or ROOT / 'reports/arena-surroundings-implementation/client-qa/bin/TioQaClient.exe')
        self.events: list[dict] = []
        self._on_event = on_event
        self._runtime_errors = []
        self.window_script = None
        self.closed = False
        # Own QA harness bypasses only the two startup instance-limit branches.
        # Retail renderer/authentication and all on-disk binary bytes stay intact.
        if launcher is not None:
            launcher = Path(launcher).resolve()
            expected_launcher = launcher_sha256 or 'd135224ae3803dfcaaaa3602cc2a1cfabe042a03a3c30238b81ddf4a1996dda8'
            if not re.fullmatch('[0-9a-f]{64}', expected_launcher) or hashlib.sha256(launcher.read_bytes()).hexdigest() != expected_launcher:
                raise ValueError('The exact reviewed launcher SHA256 is required')
            import uuid
            receipt = self.root.parent / ('tls-start-' + uuid.uuid4().hex + '.json')
            # The long-lived TLS child can inherit standard handles. Waiting
            # on captured pipes would wait for the whole game to close.
            launch = subprocess.Popen([str(launcher), '--tls-qa-start', str(self.root), str(receipt)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            launch.wait(timeout=75)
            if launch.returncode or not receipt.is_file():
                raise RuntimeError('The public launcher did not confirm a TLS QA client')
            info = json.loads(receipt.read_text(encoding='utf-8'))
            if not info.get('EndpointCertificatesValidated') or not 1024 <= info['SessionPort'] <= 65535:
                raise RuntimeError('The launcher did not validate both hosted TLS certificates')
            route = dict(verified_tls_route=True, session_host='127.0.0.1', session_port=info['SessionPort'])
            self.pid = int(info['Pid'])
            self.tls_receipt = receipt
        else:
            launch = subprocess.run([str(self.helper), 'start', str(self.root), '--native-multi'],
                                    capture_output=True, text=True, check=False)
            info = json.loads(launch.stdout.strip()) if launch.returncode == 0 else {}
            route = {}
            self.pid = int(info['pid']) if info else 0
        if launch.returncode:
            raise RuntimeError('Guarded QA loader did not start the client')
        self._record(dict(event='owned_graphical_client_started', pid=self.pid, game_root=str(self.root)))
        self.device = frida.get_local_device()
        self.session = self.device.attach(self.pid)
        # The launcher confirms transport readiness before SILVER is mapped.
        # Inspect only our PID; no desktop input or invented client state.
        probe = self.session.create_script("rpc.exports={ready(){return {path:Process.mainModule.path,silver:Process.findModuleByName('silver.dll')!==null};}};")
        probe.load()
        deadline = time.monotonic() + 30
        while True:
            ready = probe.exports_sync.ready()
            if Path(ready['path']).resolve() != self.root / 'ti.exe':
                self.session.detach()
                raise RuntimeError('Started PID does not belong to the owned QA client')
            if ready['silver']:
                break
            if time.monotonic() >= deadline:
                self.device.kill(self.pid)
                self.session.detach()
                raise RuntimeError('Owned QA renderer did not finish loading')
            time.sleep(0.2)
        probe.unload()
        self.script = self.session.create_script(Path(__file__).with_suffix('.js').read_text(encoding='utf-8'))

        def receive(message, data):
            if message.get('type') != 'send':
                # Never print arbitrary exception details or a script/argument dump.
                self._runtime_errors.append(message.get('type', 'unknown'))
                self._record(dict(event='bridge_runtime_error', type=message.get('type', 'unknown')))
                return
            payload = message.get('payload')
            if isinstance(payload, dict):
                self._record(payload)

        self.script.on('message', receive)
        self.script.load()
        self.script.exports_sync.initialize(dict(
            executable=str(self.root / 'ti.exe'), silver_path=str(self.root / 'silver.dll'),
            entry_guards=guards, login=login, password=password, auto_select=auto_select,
            **route,
        ))
        # Exposes the original Delphi TForm1 to the supported sky window API.
        # This changes only the own client's WS_EX_APPWINDOW; no UI inputs.
        from tools.window_compat import install
        self.window_script = install(self.session, receive)

    def _record(self, payload):
        self.events.append(payload)
        if self._on_event:
            self._on_event(payload)

    def start_connect(self):
        return self.script.exports_sync.startconnect()

    def start_connect_with_progress(self):
        """Show the exact native authorization panel and start genuine transport."""
        return self.script.exports_sync.startconnectwithprogress()

    def select_server(self):
        """Select exactly one already observed actual host/port/server-id row."""
        return self.script.exports_sync.selectserver()

    def status(self):
        result = self.script.exports_sync.status()
        result.update(pid=self.pid, runtime_errors=list(self._runtime_errors))
        return result

    def release(self, *, cleanup=False):
        """Explicit cleanup only; ordinary release leaves the graphical client open.

        Native immutable credential strings survive detachment in the own
        process's heap. The operating system reclaims them at client exit.
        """
        if self.closed:
            return
        self.closed = True
        if cleanup:
            try:
                self.device.kill(self.pid)
            except Exception:
                pass
        try:
            self.session.detach()
        except Exception:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game_root', type=Path)
    parser.add_argument('--helper', type=Path)
    parser.add_argument('--auto-select', action='store_true', help='Select the unique observed hosted row inside the native list handler')
    parser.add_argument('--seconds', type=int, default=900, help='Observation limit (1..3600 seconds)')
    parser.add_argument('--cleanup', action='store_true', help='Explicitly terminate only this helper-owned game PID at the end')
    parser.add_argument('--check-only', action='store_true', help='Static guards only: no process, account or socket creation')
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be 1..3600')
    if args.check_only:
        guards = static_guards(args.game_root)
        print(json.dumps(dict(check_only=True, functions=len(guards), graphical_clients_started=0)))
        return 0
    credentials = json.loads(sys.stdin.readline())
    def output(payload):
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    bridge = HostedGraphicalQaBridge(args.game_root, credentials, auto_select=args.auto_select,
                                      helper=args.helper, on_event=output)
    credentials.clear()
    commands = queue.Queue()
    def read_commands():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line).get('action'))
            except Exception:
                commands.put('invalid')
    threading.Thread(target=read_commands, daemon=True).start()
    bridge.start_connect()
    until = time.monotonic() + args.seconds
    try:
        while time.monotonic() < until:
            try:
                action = commands.get(timeout=0.25)
            except queue.Empty:
                continue
            if action == 'status':
                output(dict(event='bridge_status', state=bridge.status()))
            elif action == 'selectserver':
                output(dict(event='selection_rpc_returned', result=bridge.select_server()))
            elif action == 'release':
                output(dict(event='release_requested', pid=bridge.pid, client_terminated=False))
                break
            else:
                output(dict(event='invalid_control_command'))
    except KeyboardInterrupt:
        output(dict(event='interrupted', pid=bridge.pid, explicit_cleanup=args.cleanup))
    finally:
        bridge.release(cleanup=args.cleanup)
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    try:
        raise SystemExit(main())
    except Exception as error:
        # Errors from external/native code may contain argument details: emit
        # only their type, keeping password/token material out of stdout/stderr.
        print(json.dumps(dict(event='bridge_failed', error_type=type(error).__name__)), file=sys.stderr)
        raise SystemExit(1)
