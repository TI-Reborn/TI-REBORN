"""Execute original item-record63bd38 with both optional-u32 branches."""
from verify_auth_native import *
from tio.protocol.item_list import ItemRecord,encode_item_list


def main():
    results=[]
    for optional in (None,0,0xffffffff):
        item=ItemRecord(1001,301,b'\x02\x03',17,4,5,(6,7,8),b'\x09\x0a\x0b\x0c',optional,b'\x0d\x0e\x0f')
        body=encode_item_list(1,(item,))[10:]
        u=emulator();u.mem_write(DATA,body);put32(u,0xacd0e8,DATA)
        def hook(uc,addr,size,user):
            if addr==0x40b09c:return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook);obj=DATA+0x2000
        u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x63bd38,STOP,count=5000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        assert get32(u,0xacd0e8)-DATA==len(body)
        for offset,value in ((0,1001),(8,301),(0x14,17),(0x1c,5)):
            assert get32(u,obj+offset)==value
        assert bytes(u.mem_read(obj+0x44,1))==bytes([optional is not None])
        if optional is not None:assert get32(u,obj+0x40)==optional
        results.append({'body_hex':body.hex(),'consumed':len(body),'object_hex':bytes(u.mem_read(obj,100)).hex()})
    (ROOT/'evidence/item_record_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'cases':results},indent=2)+'\n')
    print('Original item record:3 cases PASS')
if __name__=='__main__':main()
