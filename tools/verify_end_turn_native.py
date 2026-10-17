"""Original95e08c EndTurn sender: gates, own actor scan, writers and cooldown.

Transport and eligibility mode predicate94ca14 isolated; actor scan executes.
"""
from verify_auth_native import *

def run(disabled=0,now=40000,deadline=0,scan=True,actors=()):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    put32(u,0xac5834,DATA+0x3300);u.mem_write(DATA+0x3300,bytes((disabled,)))
    put32(u,0xac5fe4,DATA+0x3400);put32(u,DATA+0x3400,now);put32(u,0xac4b20,deadline)
    put32(u,0xac618c,DATA+0x4000)
    for i,(actor,own,flag) in enumerate(actors):
        address=DATA+0x5000+i*0x100;put32(u,DATA+0x4000+i*4,address)
        put32(u,address+0x28,actor);u.mem_write(address+0x41,bytes((own,)));u.mem_write(address+0x1f,bytes((flag,)))
    def hook(uc,a,size,user):
        if a in (0x6748b0,0x94ca14):
            uc.reg_write(UC_X86_REG_EAX,handle if a==0x6748b0 else int(scan));return_from_stub(uc)
        elif a==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x95e08c,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    selected=next((a for a,own,flag in actors if own and not flag),0) if scan else 0
    blocked=bool(disabled) or now<deadline
    assert packet==(b'' if blocked else b'\x3a'+struct.pack('<I',selected))
    assert get32(u,0xac4b20)==(deadline if blocked else (now+30000)&0xffffffff)
    return {'disabled':disabled,'now':now,'deadline':deadline,'scan':scan,'actors':actors,'packet_hex':packet.hex(),'new_deadline':get32(u,0xac4b20)}

if __name__=='__main__':
    cases=[run(),run(disabled=1),run(now=3,deadline=4),run(now=4,deadline=4),
           run(actors=((11,0,0),(12,1,1),(17,1,0),(18,1,0))),run(scan=False,actors=((17,1,0),))]
    (ROOT/'evidence/end_turn_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('Original EndTurn sender:6 gating/selection/cooldown cases PASS')
