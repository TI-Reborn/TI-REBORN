"""Execute original Gold-shop readers/consumer and request writer; UI isolated."""
from verify_auth_native import *
from tio.city_catalogs import CityCatalogs
from tio.protocol.premium_shop import encode_premium_shop, decode_premium_purchase


def catalog_case(offers):
    packet=encode_premium_shop(0,20260925,offers)
    u=emulator();u.mem_write(DATA,packet)
    obj,rows,flags=DATA+0x1000,DATA+0x2000,DATA+0x4000
    put32(u,0xacd0e8,DATA+1)
    def read_hook(uc,addr,size,user):
        if addr==0x657494:
            n=uc.reg_read(UC_X86_REG_EDX)
            assert n==len(offers)
            put32(uc,obj+0x14,rows);put32(uc,obj+0x18,n);put32(uc,obj+0x1c,flags)
            return_from_stub(uc)
        elif addr==0x40b09c: return_from_stub(uc)
    h=u.hook_add(UC_HOOK_CODE,read_hook)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x656ff0,STOP,count=50000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,0xacd0e8)==DATA+len(packet)
    u.hook_del(h)
    for a,ptr,target in [(0xac5b98,DATA+0x4100,DATA+0x4200),(0xac637c,DATA+0x4800,DATA+0x4900)]:
        put32(u,a,ptr);put32(u,ptr,target)
    for a,ptr in [(0xac5c30,DATA+0x5200),(0xac6004,DATA+0x5210),(0xac64b4,DATA+0x5220),(0xac618c,DATA+0x5230)]:put32(u,a,ptr)
    put32(u,DATA+0x5220,0xffffffff)
    captured=[]
    def consumer(uc,addr,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX)
        if addr==0x40ce98:
            uc.reg_write(UC_X86_REG_EAX,DATA+0x6000);return_from_stub(uc)
        elif addr==0x6573cc:
            index=uc.reg_read(UC_X86_REG_EDX)
            uc.mem_write(uc.reg_read(UC_X86_REG_ECX),bytes(uc.mem_read(rows+112*index,112)))
            return_from_stub(uc)
        elif addr==0xa7b030:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif addr==0x9226cc:
            captured.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),0x2a8)));return_from_stub(uc)
        elif addr in (0x40c8cc,0xa7a13c,0x9799e0,0x40b09c,0x97d340,0x9767fc,0x40c914):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,consumer)
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x991d88,STOP,count=100000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP,hex(u.reg_read(UC_X86_REG_EIP))
    assert len(captured)==len(offers)
    for raw,o in zip(captured,offers):
        for off,val in [(0x30,o.offer_id),(0x10,o.item_id),(0x24,o.pack_count),(0x40,0),(0x44,o.gold)]:
            assert struct.unpack_from('<I',raw,off)[0]==val,(hex(off),o)
        assert raw[0x2a7]==1
    return dict(offers=len(offers),bytes=len(packet),native_gold_and_pack_verified=True)


def purchase_case():
    u=emulator();obj=DATA+0x1000;row=DATA+0x1100;flags=DATA+0x1200
    put32(u,obj,row);put32(u,obj+4,1);put32(u,obj+8,flags);u.mem_write(flags,b'\x01')
    for off,val in [(0,1304),(8,2)]:put32(u,row+off,val)
    u.mem_write(row+4,b'\x01');u.mem_write(row+12,b'\x01')
    for off,val in [(12,7),(20,0),(32,20260925),(36,0),(44,0)]:put32(u,obj+off,val)
    for off in (16,24,40,48):u.mem_write(obj+off,b'\x01')
    put32(u,0xacd0e0,DATA);put32(u,0xacd0f0,0)
    def hook(uc,addr,size,user):
        if addr==0x65fec8:
            uc.mem_write(DATA,bytes([uc.reg_read(UC_X86_REG_EDX)&255]));put32(uc,0xacd0f0,1);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x65782c,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(DATA,get32(u,0xacd0f0)))
    assert decode_premium_purchase(packet)==(7,0,1304,2,20260925)
    return dict(native_purchase_hex=packet.hex())


if __name__=='__main__':
    c=CityCatalogs(ROOT/'config/city_catalogs.json')
    result=[catalog_case(()),catalog_case(c.premium_items),purchase_case()]
    (ROOT/'evidence/premium_shop_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
