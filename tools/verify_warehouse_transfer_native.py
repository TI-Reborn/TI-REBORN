"""Original992294 array traversal and writers; transport/refcount/UI isolated."""
from verify_auth_native import *
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer


def run(first,second):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush)
    put32(u,0xac600c,handle);put32(u,0xac5940,DATA+0x3300);put32(u,0xac55cc,DATA+0x3400)
    pointers=[]
    for base,items in ((DATA+0x4000,first),(DATA+0x8000,second)):
        put32(u,base-4,len(items));pointers.append(base)
        for n,(item,count) in enumerate(items):
            put32(u,base+n*656+0x28,item);put32(u,base+n*656+0x1c,count)
    put32(u,STACK+0x8004,pointers[1])
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address in (flush,0x40d748,0x40d6c8,0x914544):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,0);u.reg_write(UC_X86_REG_EDX,17);u.reg_write(UC_X86_REG_ECX,pointers[0])
    u.emu_start(0x992294,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==encode_warehouse_transfer(WarehouseTransfer(0,17,first,second))
    return dict(first=first,second=second,packet_hex=packet.hex())


if __name__=='__main__':
    cases=[run(a,b) for a,b in (((),()),(((1001,1),),()),((),((2002,3),)),(((1001,2),(1002,1)),((2002,4),)))]
    (ROOT/'evidence/warehouse_transfer_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Original warehouse transfer arrays: 4 cases PASS')
