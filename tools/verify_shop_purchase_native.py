"""Original request builder9919c8; packet-buffer and UI helpers are stubs."""
from verify_auth_native import *
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase


def main():
    results=[]
    for request in (ShopPurchase(1,0,2,1),ShopPurchase(123,2,456,7)):
        u=emulator();out=bytearray()
        handle=DATA+0x1000;obj=DATA+0x1100;vtable=DATA+0x1200;flush=DATA+0x1300
        put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush)
        put32(u,0xac600c,handle);put32(u,0xac5940,DATA+0x1400)
        def hook(uc,addr,size,user):
            if addr==0x6748b0:
                uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
            elif addr in (0x675bf8,0x6ac248):
                width=1 if addr==0x675bf8 else 4
                out.extend((uc.reg_read(UC_X86_REG_EDX)&((1<<(width*8))-1)).to_bytes(width,'little'))
                uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
            elif addr in (flush,0x9dc760):return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook)
        u.reg_write(UC_X86_REG_EAX,request.owner_id)
        u.reg_write(UC_X86_REG_EDX,request.offer_id)
        u.reg_write(UC_X86_REG_ECX,request.quantity)
        put32(u,STACK+0x8004,request.category)
        u.emu_start(0x9919c8,STOP,count=2000)
        assert bytes(out)==encode_shop_purchase(request)
        results.append({'packet_hex':out.hex()})
    (ROOT/'evidence/shop_purchase_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':results},indent=2)+'\n')
    print('Original shop purchase writer:2 cases PASS')
if __name__=='__main__':main()
