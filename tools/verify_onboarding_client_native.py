"""Run patched original status/list hooks in x86, including a relocated image."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EDI
from deploy.client_character_onboarding import patch,RVA,FLAG


def run(base,status):
    data=patch(BINARY.read_bytes());assert patch(data)==data
    pe=pefile.PE(data=data);pe.relocate_image(base)
    u=Uc(UC_ARCH_X86,UC_MODE_32)
    u.mem_map(base,pe.OPTIONAL_HEADER.SizeOfImage);u.mem_write(base,pe.get_memory_mapped_image())
    u.mem_map(DATA,0x10000);u.mem_map(STACK,0x10000)
    delta=base-0x400000
    calls=[]
    def hook(uc,address,size,user):
        if address==0x8a2868+delta:return_from_stub(uc)
        if address==0x6d0318+delta:
            calls.append(uc.reg_read(UC_X86_REG_EAX));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.reg_write(UC_X86_REG_EAX,(status-4)&255)
    u.emu_start(0x88a8ad+delta,0x88a8b4+delta,count=100)
    assert bytes(u.mem_read(base+FLAG,1))==bytes([status==5])
    put32(u,0xac618c+delta,DATA);put32(u,DATA+12,DATA+0x1000)
    put32(u,0xac64b4+delta,DATA+0x2000)
    for _ in range(2):
        u.reg_write(UC_X86_REG_ESP,STACK+0x7000);u.reg_write(UC_X86_REG_EBP,STACK+0x7040)
        put32(u,STACK+0x7044,STOP)
        u.emu_start(0x88a435+delta,STOP,count=500)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert calls==([3] if status==5 else [])
    return dict(base=hex(base),status=status,native_editor_calls=calls)


if __name__=='__main__':
    cases=[run(base,status) for base in (0x400000,0x600000) for status in (0,5,255)]
    (ROOT/'evidence/onboarding-client-native.json').write_text(json.dumps(cases,indent=2)+'\n')
    print('6 native patched status/list/relocation cases PASS')
