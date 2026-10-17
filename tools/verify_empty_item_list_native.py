"""Original ItemList30 decoder63ce00, empty array branch (no allocation stubs)."""
from verify_auth_native import *
from tio.protocol.item_list import encode_empty_item_list

def main():
    cases=[]
    for owner,unknown in ((1,0),(12345,255)):
        packet=encode_empty_item_list(owner,unknown)
        u=emulator();u.mem_write(DATA,packet[1:]);put32(u,0xacd0e8,DATA)
        obj=DATA+0x2000;u.reg_write(UC_X86_REG_EAX,obj)
        u.emu_start(0x63ce00,STOP,count=5000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        assert get32(u,0xacd0e8)-DATA==9
        assert get32(u,obj)==owner
        assert bytes(u.mem_read(obj+5,1))==bytes([unknown])
        assert get32(u,obj+12)==0
        cases.append({'packet_hex':packet.hex(),'body_consumed':9})
    (ROOT/'evidence/empty_item_list_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'cases':cases},indent=2)+'\n')
    print('Original empty ItemList reader:2 cases PASS')
if __name__=='__main__':main()
