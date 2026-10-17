"""Execute original single-item UI branches a66645/a667b2 until transfer builder.

Synthetic widgets and managed array allocation/copy; real array choice and ABI.
Widget type3 maps warehouse kind0; visible widget identity remains separately inferred.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EDI, UC_X86_REG_ESI


def run(entry):
    u=emulator();context=DATA+0x1000;widget=DATA+0x2000;table=DATA+0x3000;actor=DATA+0x4000;array=DATA+0x5000
    put32(u,context+16,widget);put32(u,widget+0x278,3)
    put32(u,0xac64b4,DATA+0x6000);put32(u,0xac618c,table);put32(u,table,actor);put32(u,actor+0x28,17)
    put32(u,DATA+0x6100,widget)
    put32(u,0xb768e0+0x28,1001);put32(u,0xb768e0+0x1c,1)
    observed=[]
    def hook(uc,address,size,user):
        if address==0x40d5a4:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),array);put32(uc,array-4,1);return_from_stub(uc)
        elif address==0x40d6c8:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),0);return_from_stub(uc)
        elif address==0x40cc38:
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),656)));return_from_stub(uc)
        elif address==0x992294:
            first=uc.reg_read(UC_X86_REG_ECX);second=get32(uc,uc.reg_read(UC_X86_REG_ESP)+4)
            observed.append(dict(kind=uc.reg_read(UC_X86_REG_EAX)&255,actor=uc.reg_read(UC_X86_REG_EDX),
                first=[] if not first else [get32(uc,first+0x28)],second=[] if not second else [get32(uc,second+0x28)]))
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EDI,context);u.reg_write(UC_X86_REG_ESI,DATA+0x6100)
    u.emu_start(entry,STOP,count=1000)
    assert observed==[dict(kind=0,actor=17,first=[1001] if entry==0xa66645 else [],second=[] if entry==0xa66645 else [1001])],observed
    return dict(entry=hex(entry),transfer=observed[0])

if __name__=='__main__':
    cases=[run(e) for e in (0xa66645,0xa667b2)]
    (ROOT/'evidence/warehouse_ui_arrays_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Original warehouse UI array selection: 2 cases PASS')
