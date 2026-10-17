"""Execute AA field reader and C812 writer; isolate managed allocation/UI.

Metadata enrichment and UI callback are skipped in AA, numeric readers run.
"""
from verify_auth_native import *
from tio.protocol.abilities import encode_skill_tree

def tree_case(entries):
    packet=encode_skill_tree(4,entries);u=emulator();u.mem_write(DATA,packet)
    array=DATA+0x3000;result=[]
    def hook(uc,addr,size,user):
        if addr==0x4092ac:
            uc.reg_write(UC_X86_REG_EAX,DATA+0x2000);return_from_stub(uc)
        elif addr==0x40eca8:return_from_stub(uc)
        elif addr==0x40d5a4:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),array);put32(uc,array-4,len(entries));return_from_stub(uc)
        elif addr==0x8c22b7:uc.reg_write(UC_X86_REG_EIP,0x8c2395)
        elif addr==0x8c239d:
            assert get32(uc,uc.reg_read(UC_X86_REG_EBP)-0xc)==DATA+len(packet)
            for n in range(len(entries)):
                p=array+n*0x348
                result.append((get32(uc,p+8),uc.mem_read(p+0x31e,1)[0],uc.mem_read(p+0x324,1)[0],uc.mem_read(p+0x325,1)[0],get32(uc,p+0x310),get32(uc,p+0x318)))
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+1)
    u.emu_start(0x8c2174,STOP,count=10000)
    assert result==entries
    return {'packet_hex':packet.hex(),'fields':result}

def list_request(owner):
    u=emulator();record=DATA+0x1000;out=DATA+0x2000
    put32(u,record,owner);u.mem_write(record+4,b'\x01')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,record);u.emu_start(0x62fa90,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==b'\xc8\x12'+owner.to_bytes(4,'little')
    return packet.hex()

if __name__=='__main__':
    results=[tree_case([]),tree_case([(1,1,0,1,100,0),(23,3,1,7,0x12345678,0x87654321)])]
    requests=[list_request(n) for n in (1,0x12345678)]
    (ROOT/'evidence/skill_tree_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'trees':results,'list_requests':requests},indent=2)+'\n')
    print('Native tree field reader and list request writer PASS')
