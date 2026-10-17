"""Read-only original05/06 TLS observer using the existing owned QA account B.

It remains before server selection: no07, GAME Auth2, gameplay commands, account
creation or save writes. Reports contain counters and TLS metadata, not secrets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from tools.verify_game_tls_hosted import AuditedTlsSocket, tls_context, login_preface, require
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA
from test_server_deployment import Peer
from tio.protocol.transport import (decode_initial_challenge, expected_reply_fields,
    InitialReply, encode_initial_reply, decode_initial_completion)
from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, transform_auth_value
from tio.protocol.server_list import ServerListRequest, encode_server_list_request, decode_server_list

FOLDER = ROOT/'reports/gameplay-completion/legacy-status-20261011'
FIXTURE = ROOT/'reports/arena-surroundings/private/qs3110ad96.json'
ACCOUNT_INDEX = 1


def regular_path(path):
    return not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [path,*path.parents])


def observe_lists(peer, expected_online, *, samples=3, interval=5, session_port=28513, sleep=time.sleep):
    require(type(expected_online) is int and 0<=expected_online<=65535, 'Expected online must fit the original u16 field')
    require(type(samples) is int and 2<=samples<=6 and 0<=interval<=10, 'Observation samples exceed bounded scope')
    request=encode_server_list_request(ServerListRequest(0,0,b''))
    trailing=None
    observations=[]
    for index in range(samples):
        if index:
            sleep(interval)
        peer.send(request)
        # Strict06 decoding refuses a new challenge/completion/token or an08
        # handoff. All requests share this one authenticated cipher/connection.
        listing=decode_server_list(peer.receive())
        require(listing.unknown_u8_01==0 and len(listing.entries)==1,'Expected one hosted server record')
        require(listing.trailing_bytes==b'','Original empty Auth2 trailing echo changed')
        if trailing is None:
            trailing=listing.trailing_bytes
        require(listing.trailing_bytes==trailing,'Repeated06 trailing echo changed')
        entry=listing.entries[0]
        require(entry.unknown_u8_01==1,'Expected hosted server-id1')
        require(entry.address_octets==socket.inet_aton('127.0.0.1') and entry.unknown_u16_01==session_port,
                'Original TLS loopback route changed')
        require(entry.unknown_u16_02==expected_online,'Actual unique game online differs from expected count')
        require(entry.unknown_u16_03==15,'Original server capacity changed')
        require(entry.unknown_u8_02==1,'Hosted game server is unavailable')
        observations.append(dict(sample=index+1,online=entry.unknown_u16_02,
                                 available=bool(entry.unknown_u8_02),server_id=entry.unknown_u8_01,
                                 capacity=entry.unknown_u16_03+1,trailing_echo_empty=True))
    return observations


def execute(args, report):
    require(regular_path(FIXTURE),'QA credential fixture must be regular')
    fixture=FreshSurroundingsQA.load_private(FIXTURE)
    require(fixture.host==args.host and fixture.prefix=='qs3110ad96' and len(fixture.names)==4,
            'Proven owned QA fixture target differs')
    # Login-only reservations deliberately remain excluded from game online.
    patterns=[value.encode(encoding) for value in [fixture.names[ACCOUNT_INDEX],fixture.passwords[ACCOUNT_INDEX]]
              for encoding in ('utf-8','utf-16-le')]
    connection=AuditedTlsSocket((args.host,args.login_port),args.server_name,tls_context(),patterns=patterns)
    try:
        connection.sendall(login_preface(args.local_session_port))
        peer=Peer(connection)
        fields=expected_reply_fields(decode_initial_challenge(peer.receive()))
        peer.send(encode_initial_reply(InitialReply(*fields,0,bytes(3))))
        token=decode_initial_completion(peer.receive()).unknown_u32_01
        connection.capture_next_write=True
        peer.send(encode_basic_login_request(BasicLoginRequest(fixture.names[ACCOUNT_INDEX].encode(),
                    fixture.passwords[ACCOUNT_INDEX].encode(),transform_auth_value(token))))
        require(peer.receive()==b'\x04\0','Owned QA TLS login failed')
        report['observations']=observe_lists(peer,args.expected_online,samples=args.samples,
                                            interval=args.interval,session_port=args.local_session_port)
        report.update(passed=True,same_authenticated_connection=True,initial_token_preserved=True,
                      repeated_authentication=False,refresh_requests=args.samples-1,
                      original_empty_trailing_echo_preserved=True,refresh_token_reissued=False,
                      game_handoff_token_validation_performed=False,
                      token_validation_scope='The original login context is retained; each refresh returns only06 without a new token. GAME Auth2 validity is outside this login-only observer.')
    finally:
        connection.close()
        report['tls']=connection.metadata()
    require(report['tls']['verified_chain_and_name'],'TLS chain and hostname verification missing')
    require(all(not value['plaintext_secret_found'] for value in report['tls']['wire'].values()),
            'Plaintext credential pattern found on external TLS wire')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    def online_count(value):
        count=int(value)
        if not 0<=count<=65535:
            raise argparse.ArgumentTypeError('Expected online must be0..65535')
        return count
    parser.add_argument('--expected-online',required=True,type=online_count,metavar='0..65535')
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--host',default='185.184.42.88')
    parser.add_argument('--server-name',default='ti-reborn.com')
    parser.add_argument('--login-port',type=int,default=29512)
    parser.add_argument('--local-session-port',type=int,default=28513)
    parser.add_argument('--samples',type=int,default=3)
    parser.add_argument('--interval',type=float,default=5)
    args=parser.parse_args()
    path=args.report.resolve()
    require(not path.exists() and path.is_relative_to(FOLDER) and regular_path(args.report),
            'Use a new regular scoped observation report')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),
                expected_online=args.expected_online,observer_account_index=ACCOUNT_INDEX,
                observations=[],game_auth2_sent=False,server_selection07_sent=False,
                gameplay_commands_sent=False,accounts_created=0,save_writes=0,
                login_only_reservation=True,graphical_clients_started=0,
                raw_frames_retained=False,credentials_or_tokens_reported=False)
    status=0
    try:
        execute(args,report)
    except Exception as error:
        # Protocol exceptions may contain a secret frame: retain type only.
        report['passed']=False
        report['error_type']=type(error).__name__
        status=1
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as output:
        json.dump(report,output,indent=2)
        output.write('\n')
    print(json.dumps({key:report[key] for key in ('passed','expected_online','observations','game_auth2_sent')},indent=2))
    return status


if __name__=='__main__':
    sys.exit(main())
