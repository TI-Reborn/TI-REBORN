"""Bounded TLS login checks using two existing owned QA accounts only.

Does not read user passwords, enter a world, create accounts or change saves.
The report retains results and ciphertext counters, never credential packets.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_game_tls_hosted import TlsNetworkQA,tls_context,login_preface,require
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA
from test_server_deployment import Peer
from tio.protocol.transport import (decode_initial_challenge,expected_reply_fields,
    InitialReply,encode_initial_reply,decode_initial_completion)
from tio.protocol.login import BasicLoginRequest,encode_basic_login_request,transform_auth_value
from tio.protocol.server_list import ServerListRequest,encode_server_list_request,decode_server_list

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output already exists')
    fixture=FreshSurroundingsQA.load_private(ROOT/'reports/arena-surroundings/private/qsa1496217.json')
    require(fixture.names[:2]==['qsa1496217a','qsa1496217b'] or tuple(fixture.names[:2])==('qsa1496217a','qsa1496217b'),'Unexpected QA ownership fixture')
    network=TlsNetworkQA(fixture,'185.184.42.88','ti-reborn.com',29512,29513,tls_context(),local_session_port=39001)
    held=[];results=[]
    def login(index,*,wrong=False,expected=0):
        connection=network.connect(29512,label='login-only')
        try:
            connection.sendall(login_preface(39001));peer=Peer(connection)
            fields=expected_reply_fields(decode_initial_challenge(peer.receive()))
            peer.send(encode_initial_reply(InitialReply(*fields,0,bytes(3))))
            token=decode_initial_completion(peer.receive()).unknown_u32_01
            password=fixture.passwords[index].encode('ascii')
            if wrong:password=password+b'-invalid'
            connection.capture_next_write=True
            peer.send(encode_basic_login_request(BasicLoginRequest(fixture.names[index].encode('ascii'),password,transform_auth_value(token))))
            require(peer.receive()==bytes((4,expected)),'Unexpected native login result')
            entry={'account':fixture.names[index],'case':'wrong-password' if wrong else 'duplicate' if expected else 'valid','status':expected}
            if expected==0:
                peer.send(encode_server_list_request(ServerListRequest(0,0,b'')))
                entries=decode_server_list(peer.receive()).entries
                require(len(entries)==1,'Missing hosted server list')
                entry['servers']=len(entries);held.append(connection)
            else:connection.close()
            results.append(entry)
        except BaseException:
            connection.close();raise
    try:
        login(0,wrong=True,expected=3)
        login(0)
        login(0,expected=7)
        login(1)
        for connection in held:connection.close()
        held.clear()
        time.sleep(.4)
        login(0)
        login(1)
        report={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'status':'passed',
                'scope':'owned QA accounts, verified public TLS, login/server list only',
                'cases':results,'user_accounts_used':False,'graphical_clients_used':False,
                'accounts_created':0,'world_or_battle_entered':False}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))
    finally:
        for connection in held:connection.close()

if __name__=='__main__':main()
