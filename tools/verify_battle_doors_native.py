"""Original3E writer,3F consumer, door animation/frame/collision and path lookup.

Transport, model lookup, visibility and sound are isolated. Packet numeric
code, door transitions and collision grid writes execute in original ti.exe.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator,EXE_SHA
from tio.protocol.battle_door import DoorRequest,encode_door_request,encode_door_state


def writer(opened):
    u=exe_emulator();sent=[]
    for i,address in enumerate((0x76e224,0x76dec8,0x76e1b4)):put32(u,address,DATA+0x100*i)
    def hook(uc,a,size,user):
        if a in (0x41389c,0x413b18):
            sp=uc.reg_read(UC_X86_REG_ESP);return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP,sp+8);return
        if a in (0x71944c,0x718e68):
            sent.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)&65535)))
        elif a!=0x726718:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,18);u.reg_write(UC_X86_REG_ECX,11)
    put32(u,STACK+0x8004,int(opened))
    u.emu_start(0x6dc54c,STOP,count=10000)
    assert sent==[encode_door_request(DoorRequest(17,opened,18,11))]*2
    return sent[0].hex()


def consumer(opened,unseen,stable=False,initial_opened=None):
    u=exe_emulator();record=DATA+0x100;obj=DATA+0x5000
    packet=encode_door_state(DoorRequest(17,opened,18,11))
    u.mem_write(DATA,packet[1:]);put32(u,record,0x3f);put32(u,record+12,DATA)
    put32(u,STACK+0x8004,DATA+0x7008)
    put32(u,0x76e000,DATA+0x1000);put32(u,DATA+0x1000,DATA+0x1100)
    put32(u,DATA+0x1100+0xd0,DATA+0x2000);put32(u,DATA+0x2008,1)
    put32(u,obj+4,18);put32(u,obj+8,11)
    initial_opened=not opened if initial_opened is None else initial_opened
    u.mem_write(obj+0x340,bytes((2 if initial_opened else 1,)))
    u.mem_write(obj+0x411,b'\x02');u.mem_write(obj+0x28,b'\x02')
    put32(u,0x76e5f4,DATA+0x3000);put32(u,DATA+0x3000,DATA+0x3100)
    u.mem_write(DATA+0x3100+0x24,struct.pack('<HH',38,38))
    put32(u,DATA+0x310c,DATA+0x3200);put32(u,DATA+0x3200+18*4,DATA+0x4000)
    put32(u,0x76dbe0,DATA+0x6000)
    consumed=[]
    from collections import deque
    trace=deque(maxlen=12)
    def hook(uc,a,size,user):
        trace.append(hex(a))
        if a==0x72dc90 and stable:
            sp=uc.reg_read(UC_X86_REG_ESP)
            state=get32(uc,sp+8)
            if get32(uc,sp+4)==1 and state in (3,4):put32(uc,sp+8,state-2)
            return
        if a==0x6f607c:
            consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-0x10)-DATA)
            uc.emu_stop();return
        if a==0x4b1dec:uc.reg_write(UC_X86_REG_EAX,obj)
        elif a in (0x6e45a0,0x6e460c):
            uc.reg_write(UC_X86_REG_EAX,int(unseen));sp=uc.reg_read(UC_X86_REG_ESP)
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+12);return
        elif a==0x40bf18:put32(uc,uc.reg_read(UC_X86_REG_EAX),0)
        elif a==0x6b4958:
            sp=uc.reg_read(UC_X86_REG_ESP);return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP,sp+8);return
        elif a not in (0x40afb4,0x70d704,0x6e40a4):return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,record)
    try:u.emu_start(0x6f57d0,STOP,count=20000)
    except Exception as error:
        raise RuntimeError((opened,unseen,hex(u.reg_read(UC_X86_REG_EIP)),list(trace))) from error
    assert consumed==[7]
    state=u.mem_read(obj+0x340,1)[0]
    assert state==((4 if opened else 3) if unseen and not stable else (2 if opened else 1))
    if unseen and not stable:
        frame=STACK+0x7000
        u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
        put32(u,frame-0x50,obj);put32(u,frame-0x10,0);u.mem_write(frame-0x55,b'\0')
        u.emu_start(0x72fa32,0x72fa7e,count=3000)
    assert u.mem_read(obj+0x340,1)[0]==(2 if opened else 1)
    assert u.mem_read(obj+0x28,1)[0]==(3 if opened else 2)
    collision=u.mem_read(DATA+0x4000+11*14,1)[0]
    assert collision==(0 if opened else 3)
    return dict(packet=packet.hex(),unseen=unseen,stable_adapter=stable,queued_state=state,collision=collision)


def path_key(name):
    u=exe_emulator();raw=name.encode('utf-16le');p=DATA+0x100
    put32(u,p-4,len(name));u.mem_write(p,raw+b'\0\0');starts=[]
    def hook(uc,a,size,user):
        if a==0x42f7e4:
            starts.append(uc.reg_read(UC_X86_REG_EDX));uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,p);u.reg_write(UC_X86_REG_EDX,DATA+0x500)
    u.emu_start(0x424d7c,STOP,count=5000)
    assert len(starts)==1
    return name[starts[0]:]


if __name__=='__main__':
    cases=[writer(v) for v in (False,True)]
    cases += [consumer(o,v,s) for o in (False,True) for v in (False,True) for s in (False,True)]
    assert path_key('mappack1/concrete_wall.s')=='mappack1/concrete_wall.s'
    assert path_key('mappack1\\concrete_wall.s')=='concrete_wall.s'
    assert path_key('concrete_wall.s')=='concrete_wall.s'
    u=emulator();from unicorn.x86_const import UC_X86_REG_EBX
    u.reg_write(UC_X86_REG_EBX,DATA);u.emu_start(0x9dc861,0x9dc885,count=100)
    assert u.mem_read(DATA+6,1)==b'\x01'
    (ROOT/'evidence/battle_doors_native.json').write_text(json.dumps(dict(
        method=__doc__,exe_sha256=EXE_SHA,cases=cases,door_ap=1,path_separator='backslash/colon only'),indent=2)+'\n')
    print('Original door writer2, state/frame/collision8, path3, AP1:14 cases PASS')
