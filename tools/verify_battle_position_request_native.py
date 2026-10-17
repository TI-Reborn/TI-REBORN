"""Original95e114 actor/coordinate46 writer; disabled gate, transport/UI isolated."""
from verify_auth_native import *

def run(actor,x,y,disabled=False):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    put32(u,0xac5834,DATA+0x3300);u.mem_write(DATA+0x3300,bytes((int(disabled),)))
    def hook(uc,a,size,user):
        if a==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif a in (flush,0x9dc760):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,actor);u.reg_write(UC_X86_REG_EDX,x);u.reg_write(UC_X86_REG_ECX,y)
    u.emu_start(0x95e114,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==(b'' if disabled else b'\x46'+struct.pack('<IBB',actor,x,y))
    return {'actor_id':actor,'x':x,'y':y,'disabled':disabled,'packet_hex':packet.hex()}

if __name__=='__main__':
    cases=[run(17,2,3),run(0x12345678,0,255),run(17,2,3,True)]
    (ROOT/'evidence/battle_position_request_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases,
         'caller':'9b7ff4..9b8008 passes actor+28, x+603c, y+6040'},indent=2)+'\n',encoding='utf-8')
    print('Original coordinate request46:3 cases PASS')
