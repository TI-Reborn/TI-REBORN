"""Original wire classifier, TurnNow reader/callback and name-row timer gate.

UI allocation/audio/timer setup calls are isolated. The actual x86 classifier,
field reader, owner update and renderer owner comparison execute in Unicorn.
This is not visual validation with running game clients.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EDI
from tio.protocol.battle_turn import encode_turn_now


def classify(u, packet):
    u.mem_write(DATA,packet)
    put32(u,0xacd15c,0x1b)  # Original startup's internal type identifier.
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
    u.reg_write(UC_X86_REG_EDX,DATA);u.reg_write(UC_X86_REG_ECX,len(packet))
    u.emu_start(0x65d034,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return u.reg_read(UC_X86_REG_EAX),get32(u,0xacd0e8)-DATA


def timer_row(u, identity):
    # Execute the name renderer's real owner comparison up to its timer branch.
    rows=DATA+0x6000;index=DATA+0x7000
    put32(u,rows+4,identity);put32(u,index,0)
    u.reg_write(UC_X86_REG_ESI,rows);u.reg_write(UC_X86_REG_EDI,index)
    hits=[]
    def hook(uc,address,size,user):
        if address in (0x9579c1,0x957a7a):
            hits.append(address);uc.emu_stop()
    handle=u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x9579ac,STOP,count=50)
    u.hook_del(handle)
    assert len(hits)==1
    return hits[0]==0x9579c1


def run(owner,seconds):
    u=emulator();body=DATA+0x100;calls=[]
    assert bytes(u.mem_read(0xab75a0,10))==bytes.fromhex('c7055cd1ac001b000000')
    packet=encode_turn_now(owner,seconds)
    assert classify(u,packet)==(0x1b,2), 'Wire header must select TurnNow and skip two bytes'
    # Native classifier leaves its cursor at the body, as used by65d83c.
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
    u.reg_write(UC_X86_REG_EAX,body);u.emu_start(0x630bd8,STOP,count=1000)
    assert get32(u,0xacd0e8)==DATA+len(packet)
    assert get32(u,body)==owner and get32(u,body+8)==seconds
    for index,address in enumerate((0xac5a98,0xac5cd4,0xac6264,0xac6488,0xac5834)):
        put32(u,address,DATA+0x1000+index*0x100)
    put32(u,DATA+0x1000,17);put32(u,DATA+0x1100,17);put32(u,DATA+0x1200,1)
    put32(u,DATA+0x1300,DATA+0x2000);put32(u,DATA+0x2348,DATA+0x3000);put32(u,DATA+0x3004,0xffffffff)
    noops=(0x961f3c,0x43afc0,0xa88a78,0x765ed4,0xa69d68,0x435664,0x961edc,0x9dc96c)
    def hook(uc,address,size,user):
        if address in noops:
            calls.append((address,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)))
            if address==0xa69d68:uc.reg_write(UC_X86_REG_EAX,0)
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def invoke(address):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.reg_write(UC_X86_REG_EAX,body);u.emu_start(address,STOP,count=2000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert timer_row(u,17)
    invoke(0x95e270)  # Finish disables input but retains the previous timer owner.
    assert get32(u,DATA+0x1200)==0 and timer_row(u,17)
    invoke(0x95e170)
    assert get32(u,DATA+0x1200)==0
    if owner!=17:
        assert get32(u,DATA+0x1100)==owner
        assert (0x9dc96c,owner,seconds) in calls
        assert not timer_row(u,17) and timer_row(u,owner)
    else:
        assert timer_row(u,17)
        assert not any(c[0]==0x9dc96c for c in calls)
    return dict(packet=packet.hex(),owner=owner,seconds=seconds,
                local_timer_row=timer_row(u,17),owner_timer_row=timer_row(u,owner),input_disabled=True)


if __name__=='__main__':
    old=classify(emulator(),bytes.fromhex('1b0200001028000000'))
    assert old==(0,1), 'Old bare1B must not be recognized as TurnNow'
    cases=[run(0x10000002,40),run(0x70000001,60),run(17,120)]
    (ROOT/'evidence/turn_now_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,
        method=__doc__,old_packet_classifier=old,cases=cases),indent=2)+'\n')
    print('Native C8/17 classifier, reader, finish/owner update and name-row timer gate: PASS')
