"""Trace original PetInfo66 branches with explicit UI/model/allocation stubs.

Zero input is a structural probe, NOT a valid in-game character fixture.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EDI


def trace(*, new_slot=False, human=True, appearance=False, owner_fields=False, overrides=None, body=None):
    u=emulator()
    pet=0x4000000
    u.mem_map(pet,0x10000)
    slots=DATA+0x4000
    put32(u,0xac618c,slots);put32(u,slots,0 if new_slot else pet)
    put32(u,pet+0x28,1)
    put32(u,pet+4,1)
    for address in (0xac64a0,0xac64b4,0xac55cc,0xac5fe4):
        put32(u,address,DATA+0x5000)
    # Existing slot1 ID, resource1, empty name, nonzero state avoids early removal.
    if body is None:
        body=struct.pack('<II',1,1)+b'\0\1'+bytes([int(owner_fields),0,0,int(appearance)])+bytes(2000)
    name_length=body[8:].index(0)
    appearance=bool(body[13+name_length])
    owner_fields=bool(body[10+name_length])
    overrides=overrides or {}
    u.mem_write(DATA,body)
    reads=[]
    numeric={0x605d68:1,0x605d8c:2,0x605da0:4,0x605db8:4,0x605de4:4}
    noops={0x40c8cc,0x40eca8,0xa853cc,0x40b47c,0x68a204,0x43afc0,
           0x68a774,0x43b31c,0xa7a13c,0x98f978,0xa855ac,0xa88a78,
           0xa86df8,0x8731cc,0x917484,0x6747dc,0x98fc48}
    def hook(uc,addr,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX)
        if addr in numeric:
            ptr=get32(uc,eax)
            callsite=hex(get32(uc,uc.reg_read(UC_X86_REG_ESP))-5)
            if callsite in overrides:
                uc.mem_write(ptr,overrides[callsite].to_bytes(numeric[addr],'little'))
            reads.append({'callsite':callsite,
                          'offset':ptr-DATA,'size':numeric[addr],'reader':hex(addr)})
        elif addr==0x605f1c:
            ptr=get32(uc,eax)
            name=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
            reads.append({'callsite':hex(get32(uc,uc.reg_read(UC_X86_REG_ESP))-5),
                          'offset':ptr-DATA,'size':len(name)+1,'reader':'CString'} )
            put32(uc,eax,ptr+len(name)+1);put32(uc,uc.reg_read(UC_X86_REG_EDX),0)
            return_from_stub(uc)
        elif addr==0x4092ac:
            uc.reg_write(UC_X86_REG_EAX,DATA+0x6000);return_from_stub(uc)
        elif addr==0xa844a0:
            uc.reg_write(UC_X86_REG_EAX,pet);return_from_stub(uc)
        elif addr==0xa93f9c:
            uc.reg_write(UC_X86_REG_EAX,0 if human else 1);return_from_stub(uc)
        elif addr==0xa84704:
            return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+8)
        elif addr in noops:
            return_from_stub(uc)
        elif addr==0x8c4fb7:
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,DATA);u.reg_write(UC_X86_REG_EDX,len(body))
    try:
        u.emu_start(0x8c4380,STOP,count=50000)
    except Exception:
        print("Failed at",hex(u.reg_read(UC_X86_REG_EIP)),"last reads",reads[-3:])
        raise
    assert u.reg_read(UC_X86_REG_EIP)==0x8c4fb7,hex(u.reg_read(UC_X86_REG_EIP))
    consumed=get32(u,u.reg_read(UC_X86_REG_EBP)-0x29c)-DATA
    assert consumed==sum(r['size'] for r in reads)
    assert get32(u,slots)==pet
    assert get32(u,pet+0x28)==1
    result={'profile':{'new_slot':new_slot,'human':human,'appearance':appearance,'owner_fields':owner_fields},'body_hex':bytes(u.mem_read(DATA,consumed)).hex(),'sha256':EXPECTED_SHA,'method':__doc__,'consumed':consumed,'reads':reads,
            'native_health':{'maximum':int.from_bytes(u.mem_read(pet+0x6008,2),'little'),'current':int.from_bytes(u.mem_read(pet+0x6006,2),'little')},
            'native_max_weight':get32(u,pet+0x6024),
            'native_armor':get32(u,pet+0x6010),
            'native_rank':{'index':get32(u,pet+0x604c),'points':get32(u,pet+0x6050),
                           'recovery':get32(u,pet+0x6054),'remaining':get32(u,pet+0x6058)},
            'limitations':['allocation/constructor stubs for new slot','equipment resource lookup result supplied explicitly','timed and trailing-string states absent','managed name conversion stub','UI/model/runtime stubs','not a live valid actor']}
    return result


def main():
    results=[]
    for new_slot, human, appearance, owner_fields in (
        (False,True,False,False), (True,True,True,False),
        (True,False,True,False), (False,True,True,True)):
        results.append(trace(new_slot=new_slot,human=human,appearance=appearance,owner_fields=owner_fields))
    (ROOT/'evidence/pet_info_native_variants.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Original PetInfo variants:', [(r['profile'],r['consumed']) for r in results])
if __name__=='__main__':main()
