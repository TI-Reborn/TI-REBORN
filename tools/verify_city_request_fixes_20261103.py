"""Two disposable excluded accounts browse both shops over production TLS."""
import argparse
import ast
import json
from pathlib import Path
import secrets
import socket
import ssl
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from tio.protocol.city_catalogs import decode_item_shop
saved_path = list(sys.path)
from tools.verify_launcher_required_hosted_20261020 import identity
sys.path[:] = saved_path

OUT = ROOT/'reports/player-errors-20261103'
PRIVATE = ROOT/'.secrets/player-errors-20261103-qa.json'
SSH = ['ssh', '-i', str(Path.home()/'.ssh/tio_server'), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=10', 'root@185.184.42.88']


def remote(code: str, data) -> dict:
    result = subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -'],
                            input='request='+repr(data)+'\n'+code,
                            capture_output=True, encoding='utf-8', timeout=60)
    if result.returncode:
        raise RuntimeError('Owned QA administration failed; private output suppressed')
    return json.loads(result.stdout)


def fixture_sql() -> dict:
    tree = ast.parse((ROOT/'tools/verify_game_operations_hosted.py').read_text(encoding='utf-8'))
    values = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ('FINGERPRINT', 'CREATE', 'CLEANUP')):
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<owned-QA-SQL>', 'exec'), values)
    return values


def network(data: dict, *, after: bool) -> dict:
    case = MultiAccountTests(); case.clients = []
    tls = GameTLSTests(); tls.case = case
    context = ssl.create_default_context()
    proof = identity()
    def connect(kind, *, preface=None, **_kwargs):
        raw = socket.create_connection(('185.184.42.88', 29512 if kind == 'login' else 29513), timeout=20)
        channel = context.wrap_socket(raw, server_hostname='ti-reborn.com')
        case.clients.append(channel)
        port = int.from_bytes(preface[6:8], 'big') if preface else 35101
        channel.sendall(struct.pack('!4sBBH', b'TIOT', 2, 0, port)+proof)
        return channel
    tls.connect = connect
    def ask(peer, packet, expected):
        start = time.perf_counter(); peer.send(packet); peer.send(b'\x70')
        replies = []; fenced = False
        deadline = time.monotonic()+15
        for _ in range(1024):
            peer.sock.settimeout(max(.001, deadline-time.monotonic()))
            reply = peer.receive(); replies.append(reply)
            if reply.startswith(b'\xf0\x8a\x01\0\0') and not expected.startswith(b'\xf0'):
                raise AssertionError(reply[13:-2].decode('utf-16-le'))
            fenced |= reply == b'\x9e'
            if fenced and any(p.startswith(expected) for p in replies):
                return replies, (time.perf_counter()-start)*1000
        raise AssertionError('Expected response/ping fence missing')
    report = dict(passed=False, tls=True, accounts=2, graphical_clients=False, samples_ms=[])
    try:
        peers = []
        for i, (name, password) in enumerate(zip(data['names'], data['passwords'])):
            peer = tls.handoff(tls.begin(name, 35101+i, password=password))
            case.enter(peer, name); peers.append(peer)
        for i in range(10):
            peer = peers[i % 2]
            replies, elapsed = ask(peer, b'\x73\0', b'\x74\0')
            category, items = decode_item_shop(next(p for p in replies if p.startswith(b'\x74\0')))
            assert category == 0 and items
            replies, premium_elapsed = ask(peer, b'\x76'+bytes(4), b'\x77')
            assert any(p.startswith(b'\x77') and len(p) > 8 for p in replies)
            assert not any(p.startswith(b'\xf0\x8a\x01\0\0') for p in replies)
            report['samples_ms'].extend((elapsed, premium_elapsed))
        for peer in peers:
            for packet, expected in ((b'\xc1\x01', b'\xc1\x02'), (b'\xc1\x05', b'\xc1\x06')):
                ask(peer, packet, expected)
            replies, _ = ask(peer, b'\xc1\x04'+bytes(40), b'\xf0\x8a\x01\0\0')
            error = next(p for p in replies if p.startswith(b'\xf0\x8a\x01\0\0'))[13:-2].decode('utf-16-le')
            if after:
                assert error == 'Настройки векселей задаются сервером', error
            report['settings_denial'] = error
        report.update(passed=True, median_ms=statistics.median(report['samples_ms']),
                      maximum_ms=max(report['samples_ms']), both_shops_replied=20)
        return report
    finally:
        for channel in case.clients:
            channel.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('provision', 'before', 'after', 'cleanup'))
    args = parser.parse_args(); sql = fixture_sql()
    if args.mode == 'provision':
        if PRIVATE.exists():
            raise ValueError('Refuse to replace existing owned fixture')
        prefix = 'qs'+secrets.token_hex(4)
        data = dict(names=[prefix+s for s in ('a', 'b')], passwords=[secrets.token_hex(16) for _ in range(2)])
        provision = remote(sql['CREATE'], list(zip(data['names'], data['passwords'])))
        data.update(provision); PRIVATE.write_text(json.dumps(data), encoding='utf-8')
        print(json.dumps(dict(created=2, ranking_excluded=provision['ranking_excluded'])))
        return
    data = json.loads(PRIVATE.read_text(encoding='utf-8'))
    if args.mode == 'cleanup':
        report = remote(sql['CLEANUP'], dict(names=data['names'], protected_before=data['protected_before'],
                                           require_unchanged_players=False))
    else:
        report = network(data, after=args.mode == 'after')
    (OUT/('hosted-'+args.mode+'.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
