"""Execute create battle a0a6f4, typed setters/serializer and real numeric writers.
Only packet begin/end629764/629938 are stubbed.
"""
from verify_auth_native import *

if __name__=='__main__':
    cases=[]
    for args in ((0,1,2,3,4,500,6,7),(18,3,8,900,2,140,2,3)):
        mode,map_size,players,s8,s12,s16,s20,s24=args
        u=emulator();put32(u,0xacd0e0,DATA);put32(u,0xacd0f0,0)
        for i,value in enumerate((s8,s12,s16,s20,s24)):put32(u,STACK+0x8004+i*4,value)
        def hook(uc,addr,size,user):
            if addr in (0x629764,0x629938):return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook)
        u.reg_write(UC_X86_REG_EAX,mode);u.reg_write(UC_X86_REG_EDX,map_size);u.reg_write(UC_X86_REG_ECX,players)
        u.emu_start(0xa0a6f4,STOP,count=3000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        packet=bytes(u.mem_read(DATA,get32(u,0xacd0f0)))
        expected=b'\xc8\x2b'+struct.pack('<IBBBIBBBI',mode,map_size,players,s20,s16,s24,s24,s12,s8)
        assert packet==expected,(packet.hex(),expected.hex())
        cases.append({'arguments':args,'packet_hex':packet.hex()})
    (ROOT/'evidence/arena_create_request_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Create battle C8/2B original builder/serializer:2 cases PASS')
