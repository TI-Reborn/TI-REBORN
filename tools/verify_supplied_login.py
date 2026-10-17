"""One explicitly authorized TLS account check, with credentials from stdin.

No credential arguments, files, payload logs, account creation or world entry.
The output records only the authentication status and server-list count.
This protocol check does not establish successful native GUI login.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_server_deployment import Peer
from tools.verify_game_tls_hosted import tls_context, login_preface
from tio.protocol.transport import (decode_initial_challenge, expected_reply_fields,
    InitialReply, encode_initial_reply, decode_initial_completion)
from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, transform_auth_value
from tio.protocol.server_list import ServerListRequest, encode_server_list_request, decode_server_list


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    report = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
        scope='one user-authorized account, verified TLS, login/server list only',
        graphical_client_used=False, credentials_saved=False,
        accounts_created=0, world_or_battle_entered=False)
    stage = 'credential-input'
    try:
        value = json.loads(sys.stdin.readline(4097))
        if not isinstance(value, dict) or set(value) != {'login', 'password'}:
            raise ValueError('Unsupported credential input')
        login, password = value['login'].encode('ascii'), value['password'].encode('ascii')
        if not (1 <= len(login) <= 64 and 1 <= len(password) <= 64):
            raise ValueError('Unsupported credential input')
        del value
        stage = 'tls-connect'
        with socket.create_connection(('185.184.42.88', 29512), timeout=10) as raw:
            with tls_context().wrap_socket(raw, server_hostname='ti-reborn.com') as connection:
                report['tls_version'] = connection.version()
                connection.sendall(login_preface(39001))
                peer = Peer(connection)
                stage = 'challenge'
                fields = expected_reply_fields(decode_initial_challenge(peer.receive()))
                peer.send(encode_initial_reply(InitialReply(*fields, 0, bytes(3))))
                token = decode_initial_completion(peer.receive()).unknown_u32_01
                stage = 'login'
                peer.send(encode_basic_login_request(BasicLoginRequest(login, password, transform_auth_value(token))))
                del password
                reply = peer.receive()
                if len(reply) != 2 or reply[0] != 4:
                    raise ValueError('Unsupported login reply')
                report['login_status'] = reply[1]
                report['authenticated'] = reply[1] == 0
                if report['authenticated']:
                    stage = 'server-list'
                    peer.send(encode_server_list_request(ServerListRequest(0, 0, b'')))
                    report['servers'] = len(decode_server_list(peer.receive()).entries)
                report['status'] = 'passed' if report['authenticated'] and report.get('servers') == 1 else 'denied'
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, failed_stage=stage)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
