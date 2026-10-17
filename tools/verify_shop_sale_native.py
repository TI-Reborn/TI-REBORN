"""Original request builder99034c; packet-buffer and UI helpers are stubs."""
from verify_auth_native import *
from tio.protocol.shop_sale import ShopSale,encode_sale_request
from tio.protocol.shop_sale import encode_sale_quote
from unicorn.x86_const import UC_X86_REG_EBX


def main():
    quote=encode_sale_quote(1,65)
    reader=emulator();reader.mem_write(DATA,quote[2:]);reader.reg_write(UC_X86_REG_EAX,DATA)
    reader.emu_start(0x8a15a0,0x8a15d0,count=200)
    assert reader.reg_read(UC_X86_REG_EIP)==0x8a15d0
    assert reader.reg_read(UC_X86_REG_EBX)==65
    assert get32(reader,reader.reg_read(UC_X86_REG_EBP)-4)==DATA+8
    (ROOT/'evidence/shop_sale_quote_native.json').write_text(json.dumps({
        'sha256':EXPECTED_SHA,'packet_hex':quote.hex(),'reader':'8a15a0',
        'stop_before_ui':'8a15d0','price':65,'bytes_consumed':8,
        'limitation':'Numeric reader prefix only; UI confirmation not executed'},indent=2)+'\n')
    results=[]
    for request in (ShopSale(1,1002,1),ShopSale(123,456,7)):
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
        u.reg_write(UC_X86_REG_EDX,request.instance_id)
        u.reg_write(UC_X86_REG_ECX,request.quantity)
        u.emu_start(0x99034c,STOP,count=2000)
        assert bytes(out)==encode_sale_request(request)
        results.append({'packet_hex':out.hex()})
    (ROOT/'evidence/shop_sale_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':results},indent=2)+'\n')
    print('Original shop sale writer:2 cases PASS')
if __name__=='__main__':main()
