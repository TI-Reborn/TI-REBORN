"""Original BattleMemberList25 numeric reader, records without nested arrays.
Dynamic allocation and string conversion isolated; no UI consumer is executed.
"""
from verify_auth_native import *

if __name__=='__main__':
    cases=[]
    for count in (0,1,2,4,8):
        u=emulator();root=DATA+0x2000;records=DATA+0x3000;flags=DATA+0x5000;scratch=DATA+0x6000
        member=struct.pack('<I',101)+b'Player\0'+struct.pack('<I6BII',202,1,2,3,4,5,6,0,0)
        body=struct.pack('<BBI',7,8,count)+member*count
        u.mem_write(DATA,body);put32(u,0xacd0e8,DATA)
        def hook(uc,addr,size,user):
            eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
            if addr==0x64ea6c:
                put32(uc,eax+4,records);put32(uc,eax+8,edx);put32(uc,eax+12,flags);return_from_stub(uc)
            elif addr==0x6297e0:
                ptr=get32(uc,0xacd0e8);raw=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
                put32(uc,0xacd0e8,ptr+len(raw)+1);put32(uc,edx,scratch);uc.mem_write(scratch,bytes([len(raw)])+raw);return_from_stub(uc)
            elif addr==0x40c06c:
                n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));return_from_stub(uc)
            elif addr==0x40b09c:return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,root)
        u.emu_start(0x64e6b4,STOP,count=10000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP and get32(u,0xacd0e8)-DATA==len(body)
        for i in range(count):
            r=records+i*0x134
            assert get32(u,r)==101 and get32(u,r+0x108)==202
            assert [bytes(u.mem_read(r+j,1))[0] for j in (0x10d,0x10f,0x111,0x113,0x115,0x117)]==[1,2,3,4,5,6]
        cases.append({'packet_hex':(b'\x25'+body).hex(),'count':count,'consumed_body':len(body)})
    (ROOT/'evidence/battle_member_list_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('BattleMemberList25 original numeric reader:0/1/2/4/8 members PASS; nested arrays empty')
