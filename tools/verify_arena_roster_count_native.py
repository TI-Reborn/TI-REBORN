"""Verify BA03 caller uses arena category and count of pets with nonzero state.
Executes original 875118 callback, 87969c count and native packet writers.
Only allocator/transport are stubbed; input is a synthetic roster.
"""
from verify_auth_native import *


def run(states,category):
    u=emulator();slots=DATA+0x4000;obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    put32(u,0xac618c,slots);put32(u,0xac48a0,category)
    # Each actor needs its full native state offset5ff1, beyond the default DATA map.
    pool=0x5000000;u.mem_map(pool,0x100000)
    for i,state in enumerate(states):
        if state is None:continue
        actor=pool+i*0x7000;put32(u,slots+i*4,actor);u.mem_write(actor+0x5ff1,bytes([state]))
    def hook(uc,addr,size,user):
        if addr==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif addr==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+0x5000)
    u.emu_start(0x875118,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    count=sum(s is not None and s!=0 for s in states)
    assert packet==bytes([0xba,3,category,count]),packet.hex()
    return {'states':states,'category':category,'count':count,'packet_hex':packet.hex()}

if __name__=='__main__':
    cases=[run([],0),run([None,0,1,2,3,4,0],4),run([1]*31,1)]
    (ROOT/'evidence/arena_roster_count_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Arena original UI callback and roster count:3 cases PASS')
