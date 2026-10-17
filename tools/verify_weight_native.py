"""Execute original weight sum, overload thresholds and 4E serialization/model writes.

Metadata lookups and actor lookup are stubbed. Weight arithmetic and x87
comparisons execute unchanged; model probes stop before GUI notifications.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EDI
from tio.weight import encode_weight, overload_stage


def stage(weight, capacity):
    u=emulator()
    u.reg_write(UC_X86_REG_EBP,STACK+0x7000)
    u.reg_write(UC_X86_REG_EDI,weight)
    u.reg_write(UC_X86_REG_ESI,capacity)
    u.emu_start(0x9b3060,0x9b30c6,count=100)
    assert u.reg_read(UC_X86_REG_EIP)==0x9b30c6
    result=u.reg_read(UC_X86_REG_EAX)&0x7f
    assert result==overload_stage(weight,capacity),(weight,capacity,result)
    return dict(weight=weight,capacity=capacity,stage=result)


def inventory(equipped, container=False):
    u=emulator();panel=DATA+0x1000;array=DATA+0x2000;metadata=0x4000000
    u.mem_map(metadata,0x10000)
    put32(u,0xac637c,DATA+0x9000);put32(u,DATA+0x9000,metadata)
    put32(u,panel+0x2c8,array);put32(u,array-4,2)
    # Slot0: weapon50, slot1: 40 rounds of weight3. Equipped items remain in sum.
    for index,(mass,count) in enumerate(((50,1),(3,40))):
        entry=array+index*0x290
        put32(u,entry+4,index);put32(u,entry+0x1c,count)
        put32(u,entry+0x30,int(equipped))
        u.mem_write(metadata+index*0x3a78+0x65c,struct.pack('<H',mass))
    if container:
        u.mem_write(metadata+0x122,struct.pack('<H',123))
        put32(u,array+0x1c,10)
    def hook(uc,a,size,user):
        if a==0xa7b030:
            uc.reg_write(UC_X86_REG_EAX,get32(uc,uc.reg_read(UC_X86_REG_EAX)+4));return_from_stub(uc)
        elif a==0xa78afc:
            assert uc.reg_read(UC_X86_REG_EAX)==123
            uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,panel)
    u.emu_start(0x9bc258,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    result=u.reg_read(UC_X86_REG_EAX)
    assert result==(200 if container else 170),result
    return dict(equipped=equipped,container=container,weight=result)


def status(weight,capacity):
    u=emulator();obj=DATA;attr=DATA+0x100;out=DATA+0x400
    put32(u,obj,17);u.mem_write(obj+4,b'\x01')
    put32(u,obj+8,attr);put32(u,obj+12,2)
    put32(u,obj+16,DATA+0x300);u.mem_write(DATA+0x300,b'\x01\x01')
    for index,(kind,value) in enumerate(((7,capacity),(6,weight))):
        u.mem_write(attr+index*12,bytes((kind,1)))
        put32(u,attr+index*12+4,value);u.mem_write(attr+index*12+8,b'\x01')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x654f38,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==encode_weight(17,weight,capacity),(packet.hex(),encode_weight(17,weight,capacity).hex())
    for kind,value,offset,stop in ((6,weight,0x6020,0x8c7bad),(7,capacity,0x6024,0x8c7c4e)):
        u=emulator();actor=DATA+0x2000
        put32(u,0xac618c,DATA+0x100);put32(u,DATA+0x100,actor)
        def hook(uc,a,size,user):
            if a==0xa93f70:
                uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook)
        u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,kind);u.reg_write(UC_X86_REG_ECX,value)
        u.emu_start(0x8c7320,stop,count=1000)
        assert u.reg_read(UC_X86_REG_EIP)==stop
        assert get32(u,actor+offset)==value
    return dict(weight=weight,capacity=capacity,packet_hex=packet.hex())


if __name__=='__main__':
    cases=[stage(w,c) for c,weights in ((1000,(0,499,500,665,666,667,799,800,999,1000,1500)),(150,(74,75,99,100,119,120,149,150))) for w in weights]
    totals=[inventory(False),inventory(True),inventory(True,True)]
    updates=[status(w,c) for w,c in ((0,150),(1500,1000),(70000,2250))]
    (ROOT/'evidence/weight_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,stages=cases,inventories=totals,status_updates=updates),indent=2)+'\n',encoding='utf-8')
    print('Native weight:19 boundaries,3 inventory sums,3 status packets PASS')
