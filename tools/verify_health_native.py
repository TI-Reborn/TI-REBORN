"""Original4E serializer and status4 store; UI/effect callbacks not executed."""
from verify_auth_native import *
from tio.protocol.health import encode_health


def run(old,health):
    u=emulator();obj=DATA;attr=DATA+0x100;flags=DATA+0x200;out=DATA+0x400
    put32(u,obj,17);u.mem_write(obj+4,b'\x01')
    put32(u,obj+8,attr);put32(u,obj+12,1);put32(u,obj+16,flags)
    u.mem_write(flags,b'\x01');u.mem_write(attr,b'\x04\x01');put32(u,attr+4,health);u.mem_write(attr+8,b'\x01')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x654f38,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==encode_health(17,health)
    u=emulator();actor=DATA+0x2000
    put32(u,0xac618c,DATA+0x100);put32(u,DATA+0x100,actor)
    u.mem_write(actor+0x6006,old.to_bytes(2,'little'));reached=[]
    def hook(uc,address,size,user):
        if address==0xa93f70:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0x8c75b9:
            reached.append(True);uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,4);u.reg_write(UC_X86_REG_ECX,health)
    u.emu_start(0x8c7320,STOP,count=1000)
    assert reached and int.from_bytes(u.mem_read(actor+0x6006,2),'little')==health
    return {'old':old,'health':health,'packet_hex':packet.hex()}

if __name__=='__main__':
    cases=[run(a,b) for a,b in ((73,85),(100,0),(0,65535))]
    (ROOT/'evidence/health_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Original health serializer and model write:3 cases PASS')
