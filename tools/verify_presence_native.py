"""Execute original C7/4F/51 readers; stub string allocation and UI only."""
from verify_auth_native import *
from tio.protocol.presence import (Player,encode_players,encode_remove,encode_clear,
                                   encode_location_players,encode_location_clear)


def run(packet):
    u=emulator();u.mem_write(DATA,packet);seen=[];heap=DATA+0x8000
    put32(u,0xac6530,DATA+0x1000);put32(u,DATA+0x1000,DATA+0x2000)
    put32(u,DATA+0x22a0,DATA+0x3000)
    def hook(uc,addr,size,user):
        nonlocal heap
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if addr==0x605f1c:
            ptr=get32(uc,eax);raw=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
            put32(uc,eax,ptr+len(raw)+1);put32(uc,edx,heap)
            uc.mem_write(heap,bytes([len(raw)])+raw);heap+=0x100;return_from_stub(uc)
        elif addr==0x40c06c:
            n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));return_from_stub(uc)
        elif addr==0x40b6f8:
            uc.reg_write(UC_X86_REG_EFLAGS,uc.reg_read(UC_X86_REG_EFLAGS)&~0x40);return_from_stub(uc)
        elif addr in (0xa4991c,0xa017c8):
            record=dict(id=get32(uc,edx+4),name=bytes(uc.mem_read(edx+9,bytes(uc.mem_read(edx+8,1))[0])).decode('cp1251'),level=bytes(uc.mem_read(edx+0x109,1))[0])
            if addr==0xa017c8:record['channel']=eax&255
            seen.append(record)
            return_from_stub(uc)
        elif addr==0xa01ef4:seen.append(('clear',eax&255));return_from_stub(uc)
        elif addr==0xa49d3c:seen.append(get32(uc,edx+4));return_from_stub(uc)
        elif addr in (0x40c8cc,0x40c9a4,0x40b0fc,0x40c0d8,0x67bf80,0x66754c,0x9cfa38,0xa4a2c8):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    from unicorn.x86_const import UC_X86_REG_EFLAGS
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,packet[0]);u.reg_write(UC_X86_REG_EDX,DATA+1)
    u.emu_start(0x7d02d8,STOP,count=20000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return seen


if __name__=='__main__':
    players=(Player(101,b'Alice',3),Player(202,b'Bob',4))
    assert run(encode_players(players))==[dict(id=101,name='Alice',level=3),dict(id=202,name='Bob',level=4)]
    assert run(encode_remove((101,202)))==[101,202]
    assert run(encode_clear())==[]
    assert run(encode_location_players(players))==[
        dict(id=p.identity,name=p.name.decode(),level=p.level,channel=channel)
        for p in players for channel in (0,6,8)]
    assert run(encode_location_clear())==[('clear',c) for c in (0,6,8)]
    assert run(encode_location_players(()))==[]
    print('Native C7 global and 4F/51 Location/Trade/Help add/clear: PASS')
