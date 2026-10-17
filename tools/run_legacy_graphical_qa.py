"""Own real 0.1.6 graphical client and genuine hosted TLS authentication.

Only preparation/authentication uses this API; gameplay input is through sky.
Loads existing private QA credentials without printing them or typing into a
user authentication dialog. No server packet or authentication result is forged.
"""
from pathlib import Path
import argparse
import json
import queue
import sys
import threading
import time

from tools.hosted_graphical_qa_bridge import HostedGraphicalQaBridge
from tools.verify_legacy_lobbies_hosted import FreshSurroundingsQA, OWNERSHIP

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-completion/legacy-status-20261011/gui'
LAUNCHER = ROOT / 'reports/launcher-self-update/revision2/release/TIO Launcher.exe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client', type=Path)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--account-index', type=int, choices=range(4), required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=3600)
    args = parser.parse_args()
    report = args.report.resolve()
    client = args.client.resolve()
    if not report.is_relative_to(FOLDER) or report.exists() or not client.is_relative_to(FOLDER) or not 1 <= args.seconds <= 3600:
        raise ValueError('Use a new report and dedicated client in the GUI evidence folder')
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    if fixture.host != '185.184.42.88' or len(fixture.names) != 4:
        raise ValueError('Unexpected owned QA fixture')
    fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload())
    events = []

    def output(event):
        events.append(event)
        print(json.dumps(event, ensure_ascii=True), flush=True)

    credentials = dict(login=fixture.names[args.account_index], password=fixture.passwords[args.account_index], fresh_qa=True)
    bridge = HostedGraphicalQaBridge(client, credentials, launcher=LAUNCHER, on_event=output)
    credentials.clear()
    commands = queue.Queue()
    control = report.with_suffix('.control.jsonl')
    if control.exists():
        raise ValueError('Use a fresh owned QA control file')
    control.touch(exist_ok=False)

    def receive():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line).get('action'))
            except Exception:
                commands.put('invalid')

    threading.Thread(target=receive, daemon=True).start()
    bridge.start_connect()
    deadline = time.monotonic() + args.seconds
    cleanup = False
    control_offset = 0
    try:
        while time.monotonic() < deadline:
            with control.open('r', encoding='utf-8') as inp:
                inp.seek(control_offset)
                for line in inp:
                    try:
                        commands.put(json.loads(line).get('action'))
                    except Exception:
                        commands.put('invalid')
                control_offset = inp.tell()
            try:
                action = commands.get(timeout=0.25)
            except queue.Empty:
                continue
            if action == 'status':
                output(dict(event='bridge_status', state=bridge.status()))
            elif action == 'selectserver':
                output(dict(event='selection_rpc_returned', result=bridge.select_server()))
            elif action in ('release', 'cleanup'):
                cleanup = action == 'cleanup'
                break
            else:
                output(dict(event='invalid_control_command'))
    finally:
        state = bridge.status()
        bridge.release(cleanup=cleanup)
        receipt = dict(kind='Actual graphical native client through public launcher 0.1.6 and verified TLS',
                       account=fixture.names[args.account_index], pid=bridge.pid, client=str(client),
                       tls_start_receipt=str(bridge.tls_receipt), state=state, events=events,
                       client_terminated=cleanup, password_logged=False,
                       gameplay_automated_by_this_helper=False)
        with report.open('x', encoding='utf-8') as out:
            json.dump(receipt, out, indent=2)
            out.write('\n')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps(dict(event='owned_graphical_qa_failed', error_type=type(error).__name__)), file=sys.stderr)
        raise SystemExit(1)
