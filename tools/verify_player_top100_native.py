"""Execute original player-rating combo/builder/reader and refresh lookup.

Scalar and NUL-name read loops run in the DLL. Delphi string/allocation,
crest fetch, transport and GUI lookup are explicit stubs. This is ABI evidence,
not proof of a rendered live game window or a hosted exchange.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from functools import lru_cache

import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_EBP,UC_X86_REG_EIP,UC_X86_REG_ESP
from verify_auth_native import emulator,put32,get32,return_from_stub,DATA,STACK,STOP,ROOT,BINARY,EXPECTED_SHA
from tio.protocol.player_top100 import PlayerRating,encode_request,encode_ratings,decode_ratings


@lru_cache(maxsize=3)
def images(binary,expected_sha):
    raw=Path(binary).read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected_sha:raise ValueError('Unrecognized pinned client candidate')
    original_raw=BINARY.read_bytes()
    if hashlib.sha256(original_raw).hexdigest()!=EXPECTED_SHA:raise ValueError('Unrecognized original source')
    return pefile.PE(data=original_raw).get_memory_mapped_image(),pefile.PE(data=raw).get_memory_mapped_image()


def machine(binary=BINARY,expected_sha=EXPECTED_SHA):
    original,candidate=images(binary,expected_sha)
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0,0x1000)
    u.mem_map(0x400000,(len(candidate)+4095)&~4095);u.mem_write(0x400000,candidate)
    u.mem_map(DATA,0x10000);u.mem_map(STACK,0x10000)
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000);visited=set()
    def parity(uc,address,size,user):
        if 0x400000<=address<0x400000+len(original):
            assert bytes(uc.mem_read(address,size))==original[address-0x400000:address-0x400000+size],hex(address)
            visited.add(address)
    u.hook_add(UC_HOOK_CODE,parity)
    return u,visited


def builder(index,**options):
    u,visited=machine(**options);writer=DATA+0x2000;transport=DATA+0xff00
    u.mem_write(transport,b'\xc3')
    put32(u,0xac600c,DATA+0x100);put32(u,DATA+0x100,writer)
    put32(u,writer,DATA+0x300);put32(u,DATA+0x300,transport)
    put32(u,0xacde74,DATA+0x500);put32(u,DATA+0x780,DATA+0x900)
    put32(u,DATA+0xc5c,DATA+0x1400);put32(u,DATA+0xc64,index)
    for i in range(9):put32(u,DATA+0x1404+i*8,i)
    sent=[]
    def hook(uc,address,size,user):
        if address==0x6748b0:
            put32(uc,writer+0x1004,0);put32(uc,DATA+0x200,writer)
            uc.reg_write(UC_X86_REG_EAX,DATA+0x200);return_from_stub(uc)
        elif address==transport:
            sent.append(bytes(uc.mem_read(writer+4,get32(uc,writer+0x1004))));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x7801b0,STOP,count=2000)
    selector={0:5,5:0}.get(index,index)
    assert sent==[encode_request(selector)],sent
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return dict(combo_index=index,request=sent[0].hex(),visited_original_instructions=len(visited))


def consume(packet,**options):
    u,visited=machine(**options);u.mem_write(DATA,packet);array=DATA+0x4000
    strings={0:b''};next_string=0x50000000;result=dict(crests=[],refresh=False,rows=[])
    def save(destination,value):
        nonlocal next_string
        next_string+=4;strings[next_string]=value;put32(u,destination,next_string)
    def hook(uc,address,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if address==0x40d5a4:
            sp=uc.reg_read(UC_X86_REG_ESP);count=get32(uc,sp+4)
            assert count<=100;put32(uc,array-4,count);put32(uc,eax,array if count else 0)
            return_from_stub(uc)
        elif address==0x40c0d8:
            length=bytes(uc.mem_read(edx,1))[0];save(eax,bytes(uc.mem_read(edx+1,length)));return_from_stub(uc)
        elif address==0x40bf90:save(eax,bytes([edx&255]));return_from_stub(uc)
        elif address==0x40c164:
            save(eax,strings[get32(uc,eax)]+strings[edx]);return_from_stub(uc)
        elif address==0x40c06c:
            raw=strings[edx][:uc.reg_read(UC_X86_REG_ECX)]
            uc.mem_write(eax,bytes([len(raw)])+raw);return_from_stub(uc)
        elif address==0x40b47c:save(eax,strings[edx]);return_from_stub(uc)
        elif address==0x68a094:
            result['crests'].append([eax,edx&255]);return_from_stub(uc)
        elif address==0x77f8ea:
            result['consumed']=get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA
            count=get32(uc,array-4)
            result['rows']=[dict(name=strings[get32(uc,array+i*64)].decode('latin1'),
                clan_name=strings[get32(uc,array+i*64+4)].decode('latin1'),
                fields=[get32(uc,array+i*64+j) for j in range(8,64,4)]) for i in range(count)]
        elif address==0xa3fca8:
            result['refresh']=True;uc.reg_write(UC_X86_REG_EAX,0xffffffff);return_from_stub(uc)
        elif address in (0x40b0fc,0x9cfa38):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,packet[0]);u.reg_write(UC_X86_REG_EDX,DATA+1)
    u.reg_write(UC_X86_REG_ECX,len(packet));put32(u,0xac622c,DATA+0x3000)
    u.emu_start(0x77f918,STOP,count=1_000_000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    result['handled']=bool(u.reg_read(UC_X86_REG_EAX)&255)
    if result['handled']:
        _,rows=decode_ratings(packet);assert result['consumed']==len(packet) and result['refresh']
        assert len(result['rows'])==len(rows)
        for native,row in zip(result['rows'],rows):
            assert native['name'].encode('latin1')==row.name and native['clan_name'].encode('latin1')==row.clan_name
            expected=(row.clan_crest_id,row.alliance_crest_id,row.level,row.damage_dealt,row.damage_received,
                row.wins,row.losses,row.experience,row.kills,row.deaths,row.rating,row.military_rank,row.rank_points,row.trueskill)
            assert native['fields']==[n&0xffffffff for n in expected],(native,expected)
    else:assert not result['refresh'] and not result['rows']
    result['packet_size']=len(packet);result['visited_original_instructions']=len(visited)
    return result


def record_rtti(**options):
    original,candidate=images(options.get('binary',BINARY),options.get('expected_sha',EXPECTED_SHA))
    expected=dict(nick=0,clanname=4,clan_crest_id=8,ally_crest_id=12,level=16,
        dmg_give=20,dmg_recv=24,wins=28,loses=32,expire=36,kills=40,deathes=44,
        raiting=48,militaryRank=52,militaryRankPoints=56,trueskill=60)
    result={}
    for name,offset in expected.items():
        needle=bytes([len(name)])+name.encode('ascii')
        position=original.find(needle,0x77f9ad-0x400000,0x77faf4-0x400000)
        assert position>=0
        actual=struct.unpack_from('<I',original,position-5)[0]
        assert actual==offset,(name,actual,offset)
        assert original[position-5:position+len(needle)]==candidate[position-5:position+len(needle)]
        result[name]=dict(offset=actual,address=hex(position+1+0x400000))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',type=Path,default=BINARY)
    parser.add_argument('--sha',default=EXPECTED_SHA);parser.add_argument('--output',type=Path,default=ROOT/'evidence/player_top100_native.json')
    args=parser.parse_args();options=dict(binary=args.binary,expected_sha=args.sha)
    requests=[builder(i,**options) for i in range(9)]
    rows=(PlayerRating(b'Alice',b'Clan',11,0xdecafbad,22,7,101,102,103,104,-105,6,-106,107,108,109,110),
          PlayerRating(b'Bob',level=20,rating=0x7fffffff,rank_points=0x7fffffff,experience=0xffffffff))
    cases=[consume(encode_ratings(i,rows),**options) for i in range(9)]
    cases.append(consume(encode_ratings(5,()),**options))
    cases.append(consume(encode_ratings(0,[PlayerRating(f'Player{i:03}'.encode(),rating=i) for i in range(100)]),**options))
    cases.append(consume(b'\xf9',**options));cases.append(consume(b'\xa4',**options))
    report=dict(original_sha256=EXPECTED_SHA,candidate_sha256=args.sha,
        method=__doc__,native=dict(builder='0x77f74c',combo_callback='0x7801b0',combo_value='0xa3e490',
            dispatcher='0x77f918',reader='0x77f788',record_RTTI='0x77f97c',window='window_players_rating',
            native_refresh='0x7800dc',global_dispatch_callsite='0x9f5725'),
        parity='Every executed instruction at original image addresses equals pinned original bytes.',
        record_RTTI=record_rtti(**options),requests=requests,cases=cases)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'{len(requests)} native requests and {len(cases)} native dispatch/reader cases: PASS ({args.sha})')


if __name__=='__main__':main()
