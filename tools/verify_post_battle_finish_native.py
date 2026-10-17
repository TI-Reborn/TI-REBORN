"""Original Finish callback719F60 and treatment sender8C3D84.
GUI/settings glue and transport writes are isolated. The actual exit branch,
checkbox branch, actor ownership/HP selection and packet-building calls run.
Not a graphical-client validation.
"""
from verify_auth_native import *
from tio.battle_recovery import decode_treatment


def run(checked,healthy=False):
    u=emulator();table=DATA;window=DATA+0x1000;wrapper=DATA+0x2000
    obj=wrapper+0x100;vtable=wrapper+0x200;send=wrapper+0x300
    put32(u,0xac618c,table);put32(u,0xac46c8,window)
    u.mem_write(window+0x49,b'\x01');u.mem_write(window+0x280,bytes((checked,)))
    for index,address in enumerate((0xac59e0,0xac6100,0xac63b4,0xac5834,0xac600c)):
        put32(u,address,DATA+0x4000+index*0x100)
    put32(u,DATA+0x4400,obj)
    put32(u,wrapper,obj);put32(u,obj,vtable);put32(u,vtable,send)
    u.mem_write(send,b'\xc3');u.mem_write(0xac4b25,b'\0')
    u.mem_map(0x30000000,0x20000)
    for index,(hp,maximum,own,identity) in enumerate(((100 if healthy else 30,100,1,0x40000001),
            (100 if healthy else 0,100,1,0x40000002),(0,100,0,0x40000003))):
        actor=0x30000000+index*0x7000;put32(u,table+index*4,actor)
        u.mem_write(actor+0x41,bytes((own,)));put32(u,actor+0x28,identity)
        u.mem_write(actor+0x6006,struct.pack('<HH',hp,maximum))
    packets=[];buffer=bytearray()
    def hook(uc,address,size,user):
        if address in (0xa6a114,0x40b09c):return_from_stub(uc)
        elif address==0x4244b4:
            put32(uc,uc.reg_read(UC_X86_REG_EDX),DATA+0x6000);return_from_stub(uc)
        elif address==0x40bf68:
            uc.reg_write(UC_X86_REG_EAX,DATA+0x6000);return_from_stub(uc)
        elif address==0x688420:
            sp=uc.reg_read(UC_X86_REG_ESP);return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+16)
        elif address==0x688328:
            uc.reg_write(UC_X86_REG_EAX,checked);return_from_stub(uc)
        elif address==0x6748b0:
            buffer.clear();uc.reg_write(UC_X86_REG_EAX,wrapper);return_from_stub(uc)
        elif address in (0x675bf8,0x7f1b5c,0x6ac248):
            value=uc.reg_read(UC_X86_REG_EDX)
            buffer.extend(struct.pack('<I',value) if address==0x6ac248 else bytes((value&255,)))
            uc.reg_write(UC_X86_REG_EAX,wrapper);return_from_stub(uc)
        elif address==send:
            packets.append(bytes(buffer));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x719f60,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP,(hex(u.reg_read(UC_X86_REG_EIP)),hex(u.reg_read(UC_X86_REG_ESP)),[p.hex() for p in packets])
    expected=[b'\x2a\x01']
    if checked and not healthy:
        expected.append(b'\x7c\x02'+struct.pack('<II',0x40000001,0x40000002))
        assert decode_treatment(packets[-1])==(0x40000001,0x40000002)
    assert packets==expected,[p.hex() for p in packets]
    return dict(checked=bool(checked),healthy=healthy,packets=[p.hex() for p in packets])


if __name__=='__main__':
    cases=[run(0),run(1),run(1,True)]
    output=ROOT/'reports/post-battle-treatment/native-finish.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(method=__doc__,sha256=EXPECTED_SHA,cases=cases),indent=2)+'\n')
    print('Native Finish: exit before treatment; wounded/dead own IDs; unchecked/healthy no charge request: PASS')
