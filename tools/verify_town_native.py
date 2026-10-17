"""Original TI TownInfo decoder64a3fc with optional branches absent."""
from verify_auth_native import *
import struct
from tio.protocol.town_info import encode_town_info, diagnostic_town_info

def main():
    body=encode_town_info(diagnostic_town_info())[2:]
    u=emulator();put32(u,0xacd0e8,DATA);u.mem_write(DATA,body)
    obj=DATA+0x2000
    def hook(uc,addr,size,user):
        if addr==0x40b0fc:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x64a3fc,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,0xacd0e8)-DATA==len(body)
    assert bytes(u.mem_read(obj,3))==b'\3\0\1'
    assert bytes(u.mem_read(obj+0x20,4))==struct.pack('<f',1.)
    (ROOT/'evidence/native_town_decoder.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'packet_hex':(b'\xc8\x2d'+body).hex(),'consumed':len(body),'method':__doc__},indent=2)+'\n')
    print('Original TownInfo decoder passed; body bytes:',len(body))
if __name__=='__main__':main()
