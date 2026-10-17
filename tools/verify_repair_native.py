"""Execute original repair writers and durability getters; transport/UI stubs only."""
from verify_auth_native import *
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.protocol.repair import decode_repair


def main():
    cases=[]
    for address,prefix in ((0x9905fc,b'\x7e'),(0x99f218,b'\xc2\x03')):
        u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
        put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
        def hook(uc,address,size,user):
            if address==0x6748b0:
                uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
            elif address==flush:return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook)
        u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,1001)
        u.emu_start(address,STOP,count=10000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
        assert packet==prefix+struct.pack('<II',17,1001),packet.hex()
        assert decode_repair(packet)==(17,1001)
        cases.append(dict(writer=hex(address),packet_hex=packet.hex()))
    for words in ((50,350,350),(341,341,350),(309,600,600),(0,100,350)):
        u=emulator();obj=DATA+0x1000
        item=ItemRecord(1001,301,bytes(2),1,0,0,words,bytes(4),None,bytes(3))
        packet=encode_item_list(17,(item,))[10:]
        u.mem_write(DATA,packet);put32(u,0xacd0e8,DATA)
        def hook(uc,address,size,user):
            if address==0x40b09c:return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,obj)
        u.emu_start(0x63bd38,STOP,count=3000)
        assert get32(u,0xacd0e8)==DATA+len(packet)
        values=[]
        for address in (0x63c830,0x63c894,0x63c8f8):
            u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.reg_write(UC_X86_REG_EAX,obj)
            u.emu_start(address,STOP,count=300)
            values.append(u.reg_read(UC_X86_REG_EAX)&65535)
        assert tuple(values)==words,(values,words)
        cases.append(dict(words=values))
    (ROOT/'evidence/repair_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n')
    print('Original repair writers and durability getters: 6 cases PASS')

if __name__=='__main__':main()
