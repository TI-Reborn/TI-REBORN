"""Original item type classification a713cf..a719a8.

XML lookup and managed string/variant comparisons are isolated; original
fallback branches and metadata writes execute. This is not the entire loader.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EFLAGS


def run(itype='',type_name=''):
    u=emulator(); closure=DATA+0x1000; table=DATA+0x3000; variants={}; strings={}; reads=[]
    put32(u,closure+0xc,0);put32(u,0xac637c,DATA+0x2000);put32(u,DATA+0x2000,table)
    def string(pointer):
        if pointer in strings:return strings[pointer]
        if not pointer:return ''
        data=bytearray()
        while True:
            pair=bytes(u.mem_read(pointer+len(data),2))
            if pair==b'\0\0':return data.decode('utf-16le')
            data.extend(pair)
    def hook(uc,address,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if address==0x6807d0:
            key=string(edx);reads.append(key);assert key in ('itype','type')
            pointer=DATA+0x2200+len(reads)*0x10;strings[pointer]=itype if key=='itype' else type_name
            sp=uc.reg_read(UC_X86_REG_ESP);put32(uc,get32(uc,sp+4),pointer)
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8)
        elif address==0x4237d0:
            put32(uc,edx,eax);return_from_stub(uc)
        elif address==0x43b3f0:
            variants[eax]=string(edx);return_from_stub(uc)
        elif address in (0x43e840,0x43e850):
            equal=variants[eax]==variants[edx]
            # Branches consume ZF as the comparison predicate.
            predicate=equal if address==0x43e840 else not equal
            flags=uc.reg_read(UC_X86_REG_EFLAGS)
            uc.reg_write(UC_X86_REG_EFLAGS,(flags & ~0x40) | (0x40 if predicate else 0))
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EBP,STACK+0x7000);u.reg_write(UC_X86_REG_EBX,closure)
    u.reg_write(UC_X86_REG_EDI,DATA+0x2100)
    u.emu_start(0xa713cf,0xa719a8,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==0xa719a8
    return {'itype':itype,'type':type_name,'metadata_type':int.from_bytes(u.mem_read(table+0x118,2),'little'),'reads':reads}


if __name__=='__main__':
    # Only the empty-key path is established here. Nonempty variant comparison
    # behavior requires original managed-runtime execution before claiming it.
    case=run()
    assert case['metadata_type']==1
    (ROOT/'evidence/item_type_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,
         'limitation':'Empty keys only; comparison predicates isolated. No nonempty classification claim.',
         'cases':[case]},indent=2)+'\n',encoding='utf-8')
    print('Original empty item type path: default1 PASS; nonempty classification unverified')
