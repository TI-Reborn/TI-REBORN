"""Register two temporary QA accounts over HTTPS and test public encrypted game TCP.

Creates only fresh randomly named accounts. Does not use any player's credentials.
This is a protocol integration check, not a graphical game-client test.
"""
from pathlib import Path
import http.cookiejar
import json
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_multi_account import MultiAccountTests
from tio.protocol.character_create import CharacterCreateRequest,encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.pet_info import decode_pet_info
from tio.appearance import appearance_bytes,encode_request
from tio.protocol.asset_count import decode_asset_count
from tio.wallets import STARTING_CREDITS


def run(host):
    prefix='qa'+secrets.token_hex(4)
    names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    result={'accounts':names,'kind':'HTTPS registration + encrypted TCP, not graphical client','checks':[]}
    output=ROOT/'evidence/hosted-character-onboarding.json'
    output.write_text(json.dumps(result,indent=2)+'\n')
    origin='https://'+host
    for login,password in zip(names,passwords):
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        html=opener.open(origin+'/register/',timeout=15).read()
        assert b'name="character"' not in html
        token=re.search(rb'name="csrf" value="([^"]+)"',html)[1].decode()
        data=urllib.parse.urlencode(dict(csrf=token,login=login,password=password,confirm=password)).encode()
        response=opener.open(urllib.request.Request(origin+'/register/',data=data,headers={'Origin':origin}),timeout=15)
        assert response.status==201
    result['checks'].append('two accounts registered without character')
    case=MultiAccountTests()
    case.config=SimpleNamespace(game_port=28512,session_port=28513)
    case.clients=[]
    import socket
    def connect(port):
        connection=socket.create_connection((host,port),timeout=10)
        case.clients.append(connection);return connection
    case.connect=connect
    try:
        peers=[case.handoff(case.begin(login,password)) for login,password in zip(names,passwords)]
        for peer in peers:
            assert case.character_screen(peer)==()
            case.ping(peer)
        result['checks'].append('both authenticated accounts see empty character screen and keepalive works')
        def create(peer,name,sex):
            peer.send(encode_character_create(CharacterCreateRequest(name.encode(),0,(sex,0,0,0))))
            return peer.receive()
        assert create(peers[0],'1',1)==b'\x12\x04'
        assert create(peers[0],names[0],1)==b'\x12\x05'
        assert decode_character_list(peers[0].receive())[0].resource_type==1
        assert create(peers[1],names[0],2)==b'\x12\x03'
        assert create(peers[1],names[1],2)==b'\x12\x05'
        assert decode_character_list(peers[1].receive())[0].resource_type==2
        result['checks'].append('native male/female creation, invalid and duplicate names, retry')
        for peer,sex in zip(peers,(1,2)):
            peer.send(bytes.fromhex('1701000000'))
            assert peer.receive()==b'\x12\x05'
            assert peer.receive()[0]==0x10
            initial=bytes((sex,5 if sex==1 else 12,1 if sex==1 else 0,3,0,0))
            peer.send(encode_request(1,initial))
            assert decode_asset_count(peer.until(bytes.fromhex('c839'))).credits==STARTING_CREDITS
            assert peer.until(b'\x10')[0]==0x10
            peer.send(bytes.fromhex('1701000000'));assert peer.receive()[0]==0x18
            peer.send(b'\x19')
            pet=decode_pet_info(peer.until(b'\x66'),human_equipment=True)
            assert pet.fields['0x8c446f']==sex
            assert appearance_bytes(pet)==initial
            case.ping(peer)
        look=bytes((2,12,0,4,0,0))
        # Reproduce the native submitter's uninitialized absent body/legs bytes.
        peers[1].send(encode_request(1,look[:4]+b'\xab\xab'))
        assert appearance_bytes(decode_pet_info(peers[1].until(b'\x66'),human_equipment=True))==look
        assert decode_asset_count(peers[1].until(bytes.fromhex('c839'))).credits==STARTING_CREDITS-300
        result['checks'].append('initial selected components free; later city color change debits 300 credits')
        case.ping(peers[1]);case.ping(peers[0])
        peers[1].sock.close();time.sleep(1)
        peer=case.handoff(case.begin(names[1],passwords[1]))
        assert case.character_screen(peer)[0].optional_six==look
        peer.send(bytes.fromhex('1701000000'));assert peer.receive()[0]==0x18;peer.send(b'\x19')
        assert appearance_bytes(decode_pet_info(peer.until(b'\x66'),human_equipment=True))==look
        case.ping(peer)
        result['checks'].append('city entry, customization and reconnect persistence; other account stays online')
        result['passed']=True
    finally:
        for connection in case.clients:connection.close()
        output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':run(sys.argv[1])
