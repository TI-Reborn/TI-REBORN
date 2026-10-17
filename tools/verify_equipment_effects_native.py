"""Execute original XML generic bonus construction; isolate Delphi allocation/string helpers."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX
from normalize_equipment_effects import EFFECTS


def run(stat, value):
    u=emulator(); bp=STACK+0x7000; table=DATA+0x2000; arr=DATA+0x9000
    u.reg_write(UC_X86_REG_EBP,bp);u.reg_write(UC_X86_REG_EBX,DATA+0x1000)
    put32(u,DATA+0x100c,0);put32(u,0xac637c,DATA+0x1800);put32(u,DATA+0x1800,table)
    raw=stat.encode('ascii');u.mem_write(bp-0x2f0,bytes([len(raw)])+raw)
    u.mem_write(bp-0x148,struct.pack('<f',float(value)))
    strings={};copied=[]
    def hook(uc,addr,size,user):
        a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX);c=uc.reg_read(UC_X86_REG_ECX)
        if addr==0x40b88c:
            n=uc.mem_read(d,1)[0];ptr=DATA+0xa000;strings[ptr]=bytes(uc.mem_read(d+1,n));put32(uc,a,ptr)
        elif addr==0x40b934:
            ptr=DATA+0xa100;strings[ptr]=b'it_'+strings[c];put32(uc,a,ptr)
        elif addr==0x40b8b8:
            raw=strings[d];uc.mem_write(a,bytes([len(raw)])+raw)
        elif addr==0x40742c:
            uc.reg_write(UC_X86_REG_EAX,int(value))
        elif addr==0x40d5a4:
            put32(uc,a,arr);put32(uc,arr-4,1)
        elif addr==0x40cc38:
            uc.mem_write(a,bytes(uc.mem_read(d,0x114)));copied.append(a)
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0xa72ac1,0xa72c22,count=1000)
    assert copied==[arr]
    amount=get32(u,arr);n=u.mem_read(arr+4,1)[0]
    key=bytes(u.mem_read(arr+5,n)).decode('ascii')
    assert (key,amount)==('it_'+stat,int(value))
    return {'stat':stat,'localization_key':key,'value':amount}


if __name__=='__main__':
    import struct
    cases=[run(*effect) for effect in sorted(set(EFFECTS.values()))]
    (ROOT/'evidence/equipment_effects_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases,
         'limitation':'Native metadata construction verified; live tooltip rendering still requires client restart.'},indent=2)+'\n')
    print('Native bonus records:',cases)
