"""Original992294 writer6B; list allocation/refcounts/UI isolated, writers run.
Group meanings and mode policy are not inferred from packet shape.
"""
from verify_auth_native import *

def run(mode,first,second):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,DATA+0x3100);put32(u,DATA+0x3100,flush)
    put32(u,0xac600c,handle);put32(u,0xac5940,DATA+0x3300);put32(u,0xac55cc,DATA+0x3400)
    for base,values in ((DATA+0x4000,first),(DATA+0x7000,second)):
        put32(u,base-4,len(values))
        for n,(identity,count) in enumerate(values):
            put32(u,base+n*0x290+0x28,identity);put32(u,base+n*0x290+0x1c,count)
    put32(u,STACK+0x8004,DATA+0x7000)
    packets=[]
    def hook(uc,addr,size,user):
        if addr==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif addr in (0x40d748,0x40d6c8,0x914544):return_from_stub(uc)
        elif addr==flush:
            packets.append(bytes(uc.mem_read(obj+4,get32(uc,obj+0x1004))))
            put32(uc,obj+0x1004,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,mode);u.reg_write(UC_X86_REG_EDX,17);u.reg_write(UC_X86_REG_ECX,DATA+0x4000)
    u.emu_start(0x992294,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    expected=b'\x6b'+bytes((mode,))+struct.pack('<I',17)
    for values in (first,second):
        expected+=struct.pack('<H',len(values))+b''.join(struct.pack('<II',*v) for v in values)
    assert packets==[expected]
    return {'mode':mode,'identity':17,'first':first,'second':second,'packet_hex':expected.hex()}

if __name__=='__main__':
    cases=[run(0,(),()),run(1,((1001,1),),()),run(5,((1001,3),(1002,4)),((2001,7),))]
    (ROOT/'evidence/item_batch_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Original item batch6B:3 layouts PASS')
