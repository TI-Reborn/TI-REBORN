"""Verify F0/449 dispatch and original result-close/scene-event13 branch.

Managed event construction and UI calls isolated; branch runs original stores.
No claim of full live scene teardown from this isolated check.
"""
from verify_auth_native import *


def main():
    u=emulator();calls=[]
    raw=BINARY.read_bytes();mapped=pefile.PE(data=raw).get_memory_mapped_image()
    index=mapped[0x7d1db4-0x400000+449]
    assert struct.unpack_from('<I',mapped,0x7d1fbf-0x400000+index*4)[0]==0x7d2481
    for i,va in enumerate((0xac5f24,0xac585c,0xac59e4,0xac5520)):
        put32(u,va,DATA+i*16);u.mem_write(DATA+i*16,b'\1')
    def hook(uc,a,size,user):
        if a==0xa6a114:
            calls.append(('close',uc.reg_read(UC_X86_REG_EAX)));return_from_stub(uc)
        elif a==0x66754c:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif a==0x43afc0:
            calls.append(('event',uc.reg_read(UC_X86_REG_EDX)));return_from_stub(uc)
        elif a==0xa88a78:
            calls.append(('dispatch',));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EBP,STACK+0x7000)
    u.emu_start(0x7d2481,0x7d24ea,count=500)
    assert calls==[('close',0x7d420c),('event',13),('dispatch',)]
    assert all(u.mem_read(DATA+i*16,1)==b'\0' for i in range(4))
    (ROOT/'evidence/finish_results_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'command':449,'calls':calls},indent=2)+'\n')
    print('Original finish-results branch: PASS')


if __name__=='__main__':main()
