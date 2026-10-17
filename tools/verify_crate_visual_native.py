"""Execute original ti.exe44 scene consumer and crate frame selection.

Object lookup, visibility queries and sound are isolated; the packet reader,
grid writes, original state transition72DC90 and frame setter72D64C execute.
Also execute visible state4->2 transition from the original scene update.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator,EXE_SHA
from tio.protocol.battle_loot import encode_open_container_state


def run(visible,base_frame):
    u=exe_emulator();record=DATA+0x100;obj=DATA+0x5000
    packet=encode_open_container_state(18,11)
    u.mem_write(DATA,packet[1:]);put32(u,record,0x44);put32(u,record+12,DATA)
    put32(u,0x76e000,DATA+0x1000);put32(u,DATA+0x1000,DATA+0x1100)
    put32(u,DATA+0x1100+0xd0,DATA+0x2000);put32(u,DATA+0x1100+0x21c,DATA+0x2000)
    put32(u,DATA+0x2008,1)
    put32(u,obj+4,18);put32(u,obj+8,11)
    u.mem_write(obj+0x346,b'\x01');u.mem_write(obj+0x411,bytes((base_frame,)))
    u.mem_write(obj+0x28,bytes((base_frame,)))
    put32(u,0x76e5f4,DATA+0x3000);put32(u,DATA+0x3000,DATA+0x3100)
    put32(u,DATA+0x310c,DATA+0x3200);put32(u,DATA+0x3200+18*4,DATA+0x4000)
    put32(u,0x76dbe0,DATA+0x6000)
    consumed=[]
    def hook(uc,a,size,user):
        if a==0x6f607c:
            consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-0x10)-DATA)
            uc.emu_stop();return
        if a==0x4b1dec:uc.reg_write(UC_X86_REG_EAX,obj)
        elif a in (0x6e45a0,0x6e460c):
            uc.reg_write(UC_X86_REG_EAX,int(visible))
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+8);return
        elif a==0x40bf18:put32(uc,uc.reg_read(UC_X86_REG_EAX),0)
        elif a==0x6b4958:
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+4);return
        elif a==0x40afb4:pass
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,record)
    u.emu_start(0x6f57d0,STOP,count=20000)
    assert consumed==[4],consumed
    assert u.mem_read(DATA+0x4000+11*14+9,1)==b'\x01'
    state=u.mem_read(obj+0x346,1)[0]
    assert state==(4 if visible else 2),state
    if visible:
        # Run the original render/update fragment which settles animation4.
        frame=STACK+0x7000
        u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
        put32(u,frame-0x50,obj);put32(u,frame-0x10,0)
        u.mem_write(frame-0x55,b'\0')
        u.emu_start(0x72ff35,0x72ff5b,count=3000)
    assert u.mem_read(obj+0x346,1)==b'\x02'
    assert u.mem_read(obj+0x28,1)[0]==base_frame+1
    return dict(packet=packet.hex(),visible=visible,initial_frame=base_frame,
                queued_state=state,final_state=2,open_frame=base_frame+1)


if __name__=='__main__':
    cases=[run(v,f) for v in (False,True) for f in (0,2)]
    (ROOT/'evidence/crate_visual_native.json').write_text(json.dumps(
        dict(method=__doc__,exe_sha256=EXE_SHA,cases=cases),indent=2)+'\n')
    print('Original crate44 scene state and open frame:4 cases PASS')
