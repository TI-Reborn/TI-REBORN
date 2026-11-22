"""Private chat regression on two excluded accounts over current public TLS."""
import json
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import tio
import server
saved = list(sys.path)
from tools.verify_game_operations_hosted import CREATE, CLEANUP, remote
sys.path[:] = saved
from tools.verify_training_base_20261018_hosted import PREPARE
sys.path[:] = saved
from tools.verify_launcher_required_hosted_20261020 import Network
sys.path[:] = saved
from tio.protocol.chat import encode_message
from test_chat_paste import PASTED_TEXT

OUT = ROOT/'reports/chat-paste-20261117'
PRIVATE = ROOT/'.secrets/chat-paste-20261117.json'


def disconnect(net, reauthorize):
    net.close()
    # A new login is admitted only after the old worker detaches from the hub.
    # Do not enter a character again: the proof creates no new gameplay session.
    deadline = time.monotonic()+20
    try:
        for i in net.peers:
            while True:
                try:
                    reauthorize(i)
                    break
                except AssertionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.2)
    finally:
        net.close()


def main():
    assert not PRIVATE.exists(), 'Previous owned fixtures require cleanup first'
    prefix = 'qt'+secrets.token_hex(4)
    data = dict(names=[prefix+'a', prefix+'b'], passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision'] = remote(CREATE, list(zip(data['names'], data['passwords'])))
    PRIVATE.write_text(json.dumps(data), encoding='utf-8')
    net = Network(data)
    report = dict(passed=False, public_tls=True, graphical_clients=False, checks=[])
    try:
        remote(PREPARE.replace('19,*center(19)', '2,*center(2)'), data['names'])
        for i in (0, 1):
            net.connect(i)
        a, b = net.peers[0], net.peers[1]
        def send(text):
            a.send(b'\x21\x01'+text.encode('utf-16-le')+b'\0\0'+data['names'][1].encode()+b'\0')
        for text in (PASTED_TEXT, 'x'*201, 'bad\x1btext'):
            send(text)
            error = a.until(b'\xf0\x8a\x01\0\0', max_packets=512)
            if len(text)>200:
                assert '200' in error[13:-2].decode('utf-16-le')
            net.case.ping(a)
            net.case.ping(b)
        report['checks'].append('Exact pasted text, 201 characters and invalid controls are rejected without disconnect')
        for source, expected in (('Привет\r\nдругу\tиз чата', 'Привет другу из чата'),
                                 ('После вставки', 'После вставки')):
            send(source)
            assert b.until(b'\x22', max_packets=512) == encode_message(1, data['names'][0].encode(), expected)
            net.case.ping(a)
        report['checks'].append('Multiline paste becomes one line; subsequent private messages still reach the peer')
        report['passed'] = True
    finally:
        disconnect(net, lambda i: net.tls.begin(data['names'][i], 37001+i, password=data['passwords'][i]))
        report['cleanup'] = remote(CLEANUP, dict(names=data['names'],
            protected_before=data['provision']['protected_before'], require_unchanged_players=False))
        PRIVATE.unlink()
        (OUT/'hosted-two-account.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
