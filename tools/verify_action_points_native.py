"""Original4E serializer and status10 branch writing actor+6004.

Status handler actor lookup isolated; execute to AP write, before UI notification.
"""
from verify_auth_native import *
from tio.protocol.action_points import encode_action_points


def run(points):
    u=emulator();obj=DATA;attr=DATA+0x100;flags=DATA+0x200;out=DATA+0x400
    put32(u,obj,17);u.mem_write(obj+4,b'\x01')
    put32(u,obj+8,attr);put32(u,obj+12,1);put32(u,obj+16,flags)
    u.mem_write(flags,b'\x01');u.mem_write(attr,b'\x0a\x01');put32(u,attr+4,points);u.mem_write(attr+8,b'\x01')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x654f38,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==encode_action_points(17,points)
    u=emulator();actor=DATA+0x2000;parent=DATA+0x1000
    put32(u,0xac618c,DATA+0x100);put32(u,DATA+0x100,actor)
    u.mem_write(actor+0x41,b'\x01');u.mem_write(actor+0x6004,b'\xff')
    put32(u,parent-4,obj);put32(u,STACK+0x8004,parent)
    reached=[]
    def hook(uc,a,size,user):
        if a in (0xa93f70,0x6552c0):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif a==0x8c7a08:
            reached.append(True);uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,10);u.reg_write(UC_X86_REG_ECX,points)
    u.emu_start(0x8c7320,STOP,count=1000)
    assert reached and bytes(u.mem_read(actor+0x6004,1))==bytes((points,))
    return dict(points=points,packet_hex=packet.hex())


if __name__=='__main__':
    cases=[run(p) for p in (0,38,255)]
    (ROOT/'evidence/action_points_native.json').write_text(json.dumps(
        dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Action points serializer and model write:3 cases PASS')
