"""Start two dedicated clients with ownership-checked private QA credentials.

Uses the genuine hosted native authentication bridge. No user interface input
is performed here; camera/arena interaction belongs to the supported sky API.
"""
import argparse
import json
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.hosted_graphical_qa_bridge import HostedGraphicalQaBridge
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, OWNERSHIP
from tools.observe_arena_camera import ArenaCameraObserver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    fixture.remote(OWNERSHIP + "\nprint(json.dumps(dict(owned=True)))", fixture.ownership_payload())
    bridges = []
    observers = []
    def output(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)
    try:
        for index, suffix in enumerate(('a', 'b')):
            game_root = ROOT/'reports/arena-surroundings-implementation/client-qa'/('game-'+suffix)
            def event(value, index=index):
                output(dict(client=index, **value))
            bridge = HostedGraphicalQaBridge(game_root, dict(
                login=fixture.names[index], password=fixture.passwords[index], fresh_qa=True),
                auto_select=True, on_event=event)
            bridges.append(bridge)
            bridge.start_connect()
            observers.append(ArenaCameraObserver(bridge))
        output(dict(event='two_owned_clients_started', pids=[b.pid for b in bridges],
                    accounts=fixture.names[:2], host=fixture.host))
        for line in sys.stdin:
            action = json.loads(line).get('action')
            if action == 'status':
                snapshot = dict(event='graphical_status', observed_at_unix=time.time(),
                    clients=[dict(**b.status(), camera=o.snapshot()) for b,o in zip(bridges,observers)])
                (ROOT/'reports/arena-surroundings-implementation/client-qa/current-clients.json').write_text(
                    json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                output(snapshot)
            elif action in ('release', 'cleanup'):
                for observer in observers:
                    observer.release()
                for bridge in bridges:
                    bridge.release(cleanup=action == 'cleanup')
                output(dict(event=action, pids=[b.pid for b in bridges]))
                return 0
            else:
                output(dict(event='unknown_control'))
    except BaseException:
        for observer in observers:
            try:
                observer.release()
            except Exception:
                pass
        for bridge in bridges:
            bridge.release(cleanup=True)
        raise
    finally:
        for observer in observers:
            try:
                observer.release()
            except Exception:
                pass
        for bridge in bridges:
            bridge.release()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps(dict(event='graphical_start_failed', error_type=type(error).__name__)),
              file=sys.stderr)
        raise SystemExit(1)
