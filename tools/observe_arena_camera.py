"""Read-only camera telemetry for an existing HostedGraphicalQaBridge session.

There is deliberately no attach-by-arbitrary-PID and no launch method. Only the
already-owned bridge's existing Frida session is used. Import and --check-only
do not attach, launch a process, log in, create accounts or open game sockets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNED_ROOT = ROOT/'reports/arena-surroundings-implementation/client-qa'
PINNED = {
    'ti.exe': 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c',
    'orange.dll': '5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589',
    'silver.dll': '7137403658a66f8c9ee571960f29203bf6049d2722fa9719526049aec01670c1',
}
SPANS = (('camera_update', 0x70c070, 0xd1), ('arrow_camera_input', 0x70c144, 0xa4))


def static_guards(game_root: Path):
    import pefile
    root = Path(game_root).resolve()
    if root.parent != OWNED_ROOT.resolve() or root.name not in ('game-a', 'game-b'):
        raise ValueError('Only the two dedicated marked QA copies are supported')
    marker = json.loads((root/'.tio-owned-qa').read_text(encoding='utf-8'))
    if (marker.get('schema') != 1 or marker.get('creator') != 'tools/prepare_hosted_graphical_qa.py'
            or Path(marker.get('root', '')).resolve() != root):
        raise ValueError('Dedicated QA ownership marker differs')
    for name, expected in PINNED.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned QA binary differs: '+name)
    pe = pefile.PE(str(root/'ti.exe'))
    try:
        if pe.OPTIONAL_HEADER.ImageBase != 0x400000:
            raise ValueError('Unsupported native executable image base')
        return [dict(name=name, va=va, size=size, bytes=pe.get_data(va-0x400000, size).hex())
                for name, va, size in SPANS]
    finally:
        pe.close()


class ArenaCameraObserver:
    """No lifecycle/control authority: only observe the bridge's existing own PID."""

    def __init__(self, bridge):
        from tools.hosted_graphical_qa_bridge import HostedGraphicalQaBridge
        if not isinstance(bridge, HostedGraphicalQaBridge) or bridge.closed:
            raise ValueError('An active helper-owned HostedGraphicalQaBridge is required')
        guards = static_guards(bridge.root)
        self.pid = bridge.pid
        self.closed = False
        self._errors = []
        self.script = bridge.session.create_script(Path(__file__).with_suffix('.js').read_text(encoding='utf-8'))

        def receive(message, data):
            if message.get('type') == 'error':
                # Do not expose arbitrary target-process data in exception text.
                self._errors.append('camera_observer_runtime_error')

        self.script.on('message', receive)
        self.script.load()
        try:
            self.script.exports_sync.initialize(dict(pid=self.pid, executable=str(bridge.root/'ti.exe'), guards=guards))
        except Exception:
            self.script.unload()
            raise RuntimeError('Marked QA camera observer initialization failed') from None

    def snapshot(self):
        if self.closed:
            raise RuntimeError('Camera observer was released')
        result = self.script.exports_sync.snapshot()
        result.update(pid=self.pid, read_only=True, runtime_errors=list(self._errors))
        return result

    def release(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.script.exports_sync.release()
        finally:
            self.script.unload()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true', required=True)
    args = parser.parse_args()
    guards = static_guards(args.game_root)
    print(json.dumps(dict(check_only=True, functions=len(guards),
                          graphical_clients_started=0, arbitrary_pid_attach_supported=False)))
