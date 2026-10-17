"""Original request builder8c3c34; packet-buffer and UI helpers are stubs."""
from verify_auth_native import *
from tio.protocol.hire import encode_hire_request


def main():
    results=[]
    for request in (1, 123456):
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
        u.reg_write(UC_X86_REG_EAX,request)
        u.emu_start(0x8c3c34,STOP,count=2000)
        assert bytes(out)==encode_hire_request(request)
        results.append({'packet_hex':out.hex()})
    (ROOT/'evidence/hire_request_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':results},indent=2)+'\n')
    print('Original hire request writer:2 cases PASS')
if __name__=='__main__':main()
