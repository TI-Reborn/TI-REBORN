"""Original silver.dll mode selectors and BA03 serializer, with UI isolated.

Executes 875630/8755BC until their refresh call (category write is original),
then the original 875118 search callback + 85F954 packet builder. The owned
squad-count helper returns the fixture count; no GUI click is claimed.
"""
from verify_auth_native import *
from verify_arena_mode_ranges_native import run as ranges


def run(entry,mode,count):
    u=emulator()
    u.hook_add(UC_HOOK_CODE,lambda uc,a,s,d: uc.emu_stop() if a==entry+13 else None)
    u.emu_start(entry,STOP,count=20)
    assert get32(u,0xac48a0)==mode
    u=emulator()
    obj,handle,vtable,flush=DATA+0x1000,DATA+0x3000,DATA+0x3100,DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush)
    put32(u,0xac600c,handle);put32(u,0xac5fa0,DATA+0x3300)
    put32(u,0xac48a0,mode)
    u.reg_write(UC_X86_REG_EAX,DATA+0x4000)
    def hook(uc,address,size,user):
        if address==0x87969c:
            uc.reg_write(UC_X86_REG_EAX,count);return_from_stub(uc)
        elif address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x875118,STOP,count=4000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==bytes((0xba,3,mode,count)),packet.hex()
    return dict(mode=mode,count=count,packet_hex=packet.hex())


if __name__=='__main__':
    cases=[run(entry,mode,count) for entry,mode in ((0x875630,1),(0x8755bc,4)) for count in (1,2,3)]
    caps=[ranges(4,players,size) for players,size in ((2,2),(4,3),(8,3))]
    (ROOT/'evidence/team_modes_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases,wall_ranges=caps),indent=2)+'\n')
    print('Original team selectors/search writer/wall limits: 9 cases PASS')
