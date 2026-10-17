"""Native71 dispatcher, order reader, sorting and name-row numeric argument.
Managed record copies are isolated; parser, sorter and numeric renderer run.
This is not graphical game-client validation.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EDI
from tio.protocol.battle_turn import encode_members_arranged


def run(count):
    u=emulator();slots=DATA+0x2000;frame=STACK+0xe000;index=DATA+0x6000
    owners=tuple(101+n for n in range(count));packet=encode_members_arranged(owners)
    put32(u,0xac62a4,slots)
    for slot,owner in enumerate(reversed(owners)):
        u.mem_write(slots+slot*0x1c0,b'\x01');put32(u,slots+slot*0x1c0+4,owner)
    u.mem_write(DATA,packet[1:]);seen=[]
    def hook(uc,address,size,user):
        if address==0x9cfa38:return_from_stub(uc)
        elif address==0x68a850:
            sp=uc.reg_read(UC_X86_REG_ESP)
            assert get32(uc,sp+4)==0xa0abf8
            seen.append('native71 dispatched')
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8)
        elif address in (0x40c8cc,0x40c9a4):return_from_stub(uc)
        elif address==0x40cc38:
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),0x1c0)))
            return_from_stub(uc)
        elif address==0x4244b4:
            seen.append(uc.reg_read(UC_X86_REG_EAX));uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,0x71);u.reg_write(UC_X86_REG_EDX,DATA);u.reg_write(UC_X86_REG_ECX,len(packet)-1)
    u.emu_start(0xa0b234,STOP,count=100000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert u.reg_read(UC_X86_REG_EAX)==1
    assert seen==['native71 dispatched']
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
    u.reg_write(UC_X86_REG_EAX,DATA);u.emu_start(0xa0abf8,STOP,count=100000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert [(get32(u,slots+n*0x1c0+4),u.mem_read(slots+n*0x1c0+0x11c,1)[0]) for n in range(count)]==list(zip(owners,range(count)))
    numbers=[]
    for n in range(count):
        put32(u,index,n);u.reg_write(UC_X86_REG_ESI,slots);u.reg_write(UC_X86_REG_EDI,index);u.reg_write(UC_X86_REG_EBP,frame)
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.emu_start(0x9577aa,STOP,count=20);numbers.append(seen[-1])
    assert numbers==list(range(1,count+1))
    return dict(packet=packet.hex(),displayed=numbers)


if __name__=='__main__':
    results=[run(n) for n in (2,4,8)]
    output=ROOT/'reports/turn-order/native.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=results),indent=2)+'\n')
    print('Native71 dispatch, reader, sort and displayed numbers: PASS')
