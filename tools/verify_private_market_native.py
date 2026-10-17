"""Pinned original x86 private-store and SC builders; real numeric wire writers.

Transport, managed allocation and GUI calls are explicit stubs. Goods readers
execute the original numeric parsing and verify every stored field and consumed
byte. This does not claim graphical-client acceptance or prove SC S2C packets.
"""
from verify_auth_native import *
from tio.protocol.private_shops import encode_goods,encode_traders,decode
from tio.protocol.sc_auction import decode as decode_sc
from tio.sc_auction import prize,policy


def build(entry,eax=0,edx=0,ecx=0,*,array=False,stack=()):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vtable=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    u.mem_write(0xac490e,b'\1')
    if array:
        ptr=DATA+0x5004;put32(u,ptr-4,1)
        put32(u,ptr+8,3);put32(u,ptr+0x28,77);put32(u,ptr+0x1c,25)
        u.mem_write(ptr+0x44,struct.pack('<f',0.25));u.mem_write(ptr+0x4f,b'\5');u.mem_write(ptr+0x55,b'\1')
        if entry==0x860d48:eax=ptr
        else:edx=ptr
    for i,value in enumerate(stack,1):put32(u,STACK+0x8000+i*4,value)
    def hook(uc,addr,size,user):
        if addr==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif addr==0x864cdc:uc.reg_write(UC_X86_REG_EAX,12);return_from_stub(uc)
        elif addr in (0x40d748,0x40d6c8,0x40b47c,0x40b09c,flush):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,eax);u.reg_write(UC_X86_REG_EDX,edx);u.reg_write(UC_X86_REG_ECX,ecx)
    u.emu_start(entry,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP,hex(u.reg_read(UC_X86_REG_EIP))
    return bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))


def consume_goods(packet,buying):
    u=emulator();u.mem_write(DATA,packet[2:]);array=DATA+0x5004
    put32(u,0xac5a98,DATA+0x4000);put32(u,DATA+0x4000,1)
    u.mem_write(0xac5eec,b'\0')
    put32(u,0xac5eec,DATA+0x4020)
    captured={}
    def hook(uc,addr,size,user):
        a=uc.reg_read(UC_X86_REG_EAX)
        if addr==0x40d5a4:
            put32(uc,a,array);put32(uc,array-4,1);return_from_stub(uc)
        elif addr in (0x865fac,0xa7a13c):return_from_stub(uc)
        elif addr==(0x861310 if buying else 0x8610d3):
            captured['consumed']=get32(uc,uc.reg_read(UC_X86_REG_EBP)-8)-DATA
            captured['template']=get32(uc,array+8);captured['units']=get32(uc,array+0x1c)
            captured['id']=get32(uc,array+(0x2c if buying else 0x28))
            captured['price']=struct.unpack('<f',uc.mem_read(array+0x44,4))[0]
            captured['enhance']=bytes(uc.mem_read(array+0x4e,1))[0]
            captured['special']=bytes(uc.mem_read(array+0x57,1))[0]
            if buying:captured['filtered']=bytes(uc.mem_read(array+0x55,1))[0]
            else:captured['durability']=struct.unpack('<HH',uc.mem_read(array+0x48,4))
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x861160 if buying else 0x860fe0,STOP,count=5000)
    assert captured['consumed']==len(packet)-2,captured
    assert captured['template']==3 and captured['units']==25 and captured['id']==7 and captured['price']==0.25
    assert captured['enhance']==(0 if buying else 5) and captured['special']==0
    return dict(packet_hex=packet.hex(),**captured)


def main():
    cases=[]
    for entry,eax,edx,ecx,array,stack,expected in (
        (0x860a0c,1,3,0,False,(),'ae010103000000'),
        (0x860a60,42,0,0,False,(),'ae032a000000'),
        (0x860a98,42,0,0,True,(),'ae062a000000010000004d00000019000000'),
        (0x860b70,42,0,0,True,(),'ae072a000000010000000c0000004d00000019000000'),
        (0x860c5c,1,0,0,True,(),'ae0801010000004d000000190000000000803e'),
        (0x860d48,0,0,0,True,(),'ae090100000003000000190000000000803e0501'),
        (0x89d5a0,2,0x1234,0,False,(),'bd01023412'),
        (0x89d62c,42,0x1234,0,False,(),'bd032a0000003412'),
        (0x89d5f4,42,0,0,False,(),'bd062a000000'),
        (0x89d6f8,42,0,0,False,(),'bd072a000000'),
        (0x89d730,42,1,0,False,(),'bd092a00000001'),
        (0x89dd00,0,0,0,False,(),'bd12'),
        (0x89dd2c,1,42,10,False,(30,20),'bd14012a0000000a000000140000001e000000'),
        (0x89dd2c,0,42,0,False,(0,0),'bd14002a000000')):
        packet=build(entry,eax,edx,ecx,array=array,stack=stack)
        assert packet.hex()==expected,(hex(entry),packet.hex(),expected)
        result=decode(packet) if packet[0]==0xae else decode_sc(packet)
        cases.append(dict(entry=hex(entry),packet_hex=packet.hex(),decoded=result))
    item=prize({**policy()['offers'][0],'template':3,'count':25,'enhance':5})
    from dataclasses import replace
    item=replace(item,unknown_words=(11,22,22))
    shop=dict(id=42,sales=((7,item,25),),orders=((7,3,25,25,None,7),))
    readers=[consume_goods(encode_goods(shop),False),consume_goods(encode_goods(shop,buying=True),True)]
    (ROOT/'evidence/private_market_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,builders=cases,private_goods_readers=readers,open_abi=['SC BD incoming lots/history; private trader conditional field semantics']),indent=2)+'\n',encoding='utf-8')
    print('Original private-market/SC builders:14, private goods readers:2 PASS')


if __name__=='__main__':main()
