"""Execute original C6/21 builder and C6/04 numeric roster reader.

Unmodified pinned Silver x86 code runs in Unicorn. Managed string allocation,
record cleanup, collection append and asynchronous UI calls are explicit stubs.
Actual count loops, packet numeric readers/writers, average and counter stores
execute. This proves ABI compatibility, not rendering or real GUI acceptance.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT))
from verify_auth_native import emulator,put32,get32,return_from_stub,DATA,STACK,STOP,EXPECTED_SHA,BINARY
from tio.protocol.ranked import decode_join,encode_accepted
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_EIP
import capstone
import pefile

FOLDER=ROOT/'reports/gameplay-followup/stage4-ratings'


def builder(count):
    u=emulator();u.mem_map(DATA+0x10000,0x40000)
    obj=DATA+0x9000;handle=DATA+0x8000;vtable=DATA+0x8100;flush=DATA+0x8200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    slots=DATA+0x100;put32(u,0xac618c,slots)
    for index in range(count):
        pet=DATA+0x10000+index*0x8000;put32(u,slots+4*index,pet)
        put32(u,pet+0x28,index+1);u.mem_write(pet+0x5ff1,b'\1')
    for pointer in (0xac5974,0xac643c):
        put32(u,pointer,DATA+0x7400);put32(u,DATA+0x7400,DATA+0x7500)
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address in (0xa83d3c,0xa86fe8):uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x952bfc,STOP,count=100000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    raw=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert decode_join(raw)==((0,0),tuple((i,(),0) for i in range(1,count+1)))
    return dict(kind='original C6/21 builder',fighters=count,packet=raw.hex())


def accepted(players,actors):
    teams=tuple(tuple((side*10+i+1,tuple((1,2) for _ in range(actors))) for i in range(players)) for side in range(2))
    names={owner:('Actor'+str(owner)).encode() for team in teams for owner,pets in team}
    ratings={owner:60+owner for owner in names}
    packet=encode_accepted(51,teams,names,ratings)
    u=emulator();u.mem_map(DATA+0x10000,0x10000);u.mem_write(DATA,packet[2:])
    first=DATA+0x1000;second=DATA+0x1100
    put32(u,0xac4ab8,first);put32(u,0xac4abc,second);calls=[];seen_names=[]
    def hook(uc,address,size,user):
        if address==0x605f1c:
            pointer=uc.reg_read(UC_X86_REG_EAX);out=uc.reg_read(UC_X86_REG_EDX)
            cursor=get32(uc,pointer);text=bytearray()
            while (value:=bytes(uc.mem_read(cursor,1)))!=b'\0':text.extend(value);cursor+=1
            put32(uc,pointer,cursor+1)
            allocated=DATA+0x10000+len(seen_names)*0x100;uc.mem_write(allocated,bytes(text)+b'\0')
            put32(uc,out,allocated);seen_names.append(bytes(text).decode('ascii'));return_from_stub(uc)
        elif address==0x40b4c4:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX));return_from_stub(uc)
        elif address==0x9560a0:
            put32(uc,uc.reg_read(UC_X86_REG_EAX)+8,0);return_from_stub(uc)
        elif address==0x955678:
            collection=uc.reg_read(UC_X86_REG_EAX)
            put32(uc,collection+8,get32(uc,collection+8)+1);return_from_stub(uc)
        elif address==0xa8e4b0:uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address in (0x40c8cc,0x40c9a4,0x40b0fc,0xa6a114,0xa69ab0,0x6a1090):
            calls.append(hex(address));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x953108,STOP,count=100000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    counts=[get32(u,first+8),get32(u,second+8)]
    owners=[bytes(u.mem_read(address,1))[0] for address in (0xad05d4,0xad05d5)]
    averages=[get32(u,address) for address in (0xad05d8,0xad05dc)]
    assert counts==[players*actors]*2,(counts,players,actors)
    assert owners==[players]*2
    expected=[sum(ratings[owner] for owner,pets in team)//players for team in teams]
    assert averages==expected,(averages,expected)
    assert seen_names==[names[owner].decode() for team in teams for owner,pets in team]
    return dict(kind='original C6/04 accepted roster reader',players_per_side=players,
                actors_per_player=actors,stored_actor_counts=counts,stored_owner_counts=owners,
                stored_average_ratings=averages,managed_names_stubbed=seen_names,packet=packet.hex(),ui_calls_stubbed=calls)


def main():
    target=FOLDER/'native-abi.json'
    if target.exists():raise ValueError('Preserve prior native ABI proof')
    checks=[builder(count) for count in (1,2,3,4)]
    checks.extend(accepted(players,actors) for players,actors in ((1,4),(2,3),(4,1)))
    raw=BINARY.read_bytes();assert hashlib.sha256(raw).hexdigest()==EXPECTED_SHA
    pe=pefile.PE(data=raw);mapped=pe.get_memory_mapped_image();decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
    ranges=((0x952bfc,0x952f38),(0x953038,0x9530d2),(0x953108,0x95331c))
    asm=[]
    for first,last in ranges:
        asm.extend(f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in decoder.disasm(mapped[first-0x400000:last-0x400000],first))
    asm_path=FOLDER/'original-c6-writer-readers.asm';asm_path.write_text('\n'.join(asm)+'\n',encoding='utf-8')
    target.write_text(json.dumps(dict(passed=True,silver_sha256=EXPECTED_SHA,method=__doc__,checks=checks,
        assembler_sha256=hashlib.sha256(asm_path.read_bytes()).hexdigest(),graphical_client_acceptance=False),indent=2)+'\n',encoding='utf-8')
    print('Original C6 builder/accepted numeric roster loops: 7 PASS; no GUI claim')


if __name__=='__main__':main()
