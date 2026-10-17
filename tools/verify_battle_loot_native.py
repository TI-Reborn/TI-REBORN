"""Original47 serializer/consumer and46/40 client request writers.

Transport, refcount and string cleanup stubbed; original field writers run.
"""
from verify_auth_native import *
from tio.protocol.battle_loot import encode_container,encode_loot_transfer,LootTransfer
from tio.protocol.battle_position import encode_position_request,BattlePositionRequest
from tio.protocol.item_list import ItemRecord
from unicorn.x86_const import UC_X86_REG_EBX


def container_record(items):
    u=emulator();record=DATA+0x1000;array=DATA+0x2000
    put32(u,0xacd0e0,DATA);put32(u,0xacd0f0,0)
    put32(u,record,17);u.mem_write(record+4,b'\x01')
    for offset,value in ((6,18),(10,11)):
        u.mem_write(record+offset,struct.pack('<H',value)+b'\x01')
    put32(u,record+16,array);put32(u,record+20,len(items));put32(u,record+24,DATA+0x3000)
    if items:u.mem_write(DATA+0x3000,b'\x01'*len(items))
    for index,item in enumerate(items):
        base=array+index*60
        for offset,value in ((0,item.instance_id),(8,item.template_id),(16,item.count)):
            put32(u,base+offset,value);u.mem_write(base+offset+4,b'\x01')
        for offset,value in zip((22,26,30),item.unknown_words):
            u.mem_write(base+offset,struct.pack('<H',value)+b'\x01')
        for offset,value in zip((33,35,37,39,41),(item.unknown_bytes_02[0],item.unknown_bytes_03[0],*item.unknown_bytes_02[1:])):
            u.mem_write(base+offset,bytes((value,1)))
    return u,record


def container(items):
    u,record=container_record(items)
    def hook(uc,a,size,user):
        if a==0x40b0e4:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,record)
    u.emu_start(0x640718,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(DATA,get32(u,0xacd0f0)))
    assert packet==encode_container(17,18,11,items),(packet.hex(),encode_container(17,18,11,items).hex())
    return packet.hex()


def consumer(items):
    u,record=container_record(items)
    cell=DATA+0x4000;runtime=DATA+0x5000;actor=DATA+0x8000
    put32(u,0xac618c,DATA+0x7000);put32(u,DATA+0x7000,actor)
    put32(u,actor+0x6c,DATA+0x6000)
    observed={}
    def hook(uc,a,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if a==0x40c8cc:uc.mem_write(eax,bytes(60))
        elif a==0x40cc38:uc.mem_write(eax,bytes(uc.mem_read(edx,60)))
        elif a==0x40d5a4:
            count=get32(uc,uc.reg_read(UC_X86_REG_ESP)+4)
            assert count==len(items)
            put32(uc,eax,runtime);put32(uc,runtime-4,count)
        elif a==0x9db9a4:
            assert (edx,uc.reg_read(UC_X86_REG_ECX))==(18,11)
            uc.reg_write(UC_X86_REG_EAX,cell)
        elif a==0xa7a13c:uc.mem_write(eax,bytes(656))
        elif a==0xa93f70:
            assert eax==17
            uc.reg_write(UC_X86_REG_EAX,0)
        elif a==0xa843ac:uc.reg_write(UC_X86_REG_EAX,1)
        elif a==0x6675e0:put32(uc,edx,0)
        elif a==0x9b122c:pass
        elif a==0x9b1440:
            assert (eax,edx,uc.reg_read(UC_X86_REG_ECX))==(0,DATA+0x6000,runtime)
            observed['native_inventory_window_called']=True
            uc.emu_stop();return
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,record)
    u.emu_start(0x991508,STOP,count=20000)
    assert observed.get('native_inventory_window_called')
    for index,item in enumerate(items):
        base=runtime+index*656
        assert (get32(u,base+0x28),get32(u,base+8),get32(u,base+0x1c))==(item.instance_id,item.template_id,item.count)
        assert bytes(u.mem_read(base+0x48,6))==struct.pack('<HHH',*item.unknown_words)
        assert u.mem_read(base+0x4e,1)[0]==item.unknown_bytes_02[0]
        assert u.mem_read(base+0x54,1)[0]==item.unknown_bytes_03[0]
    observed['items']=len(items)
    observed['isolated']='Managed record copy/allocation, world cell/actor lookup, runtime initialization, UI. Original getters and consumer field writes executed.'
    return observed


def costs():
    u=emulator();u.reg_write(UC_X86_REG_EBX,DATA)
    u.emu_start(0x9dc861,0x9dc885,count=100)
    values=tuple(u.mem_read(DATA+7,3))
    assert values==(4,1,2)
    return dict(unseal_ap=values[0],open_ap=values[1],equip_ap=values[2])


def request(deposits=(),withdrawals=(),opening=False):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush)
    put32(u,0xac600c,handle);put32(u,0xac5834,DATA+0x3300)
    for base,items,offset in ((DATA+0x4000,deposits,12),(DATA+0x8000,withdrawals,8)):
        put32(u,base-4,len(items));put32(u,STACK+0x8000+offset,base)
        for n,(identity,count) in enumerate(items):
            put32(u,base+n*656+0x28,identity);put32(u,base+n*656+0x1c,count)
    def hook(uc,a,size,user):
        if a==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif a in (flush,0x40d748,0x40c9f4,0x9dc760):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,18);u.reg_write(UC_X86_REG_ECX,11)
    # Delphi prologue makes [ebp+8] the caller's ESP+4.
    put32(u,STACK+0x8004,DATA+0x8000);put32(u,STACK+0x8008,DATA+0x4000)
    u.emu_start(0x95e114 if opening else 0x98f5cc,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    expected=encode_position_request(BattlePositionRequest(17,18,11)) if opening else encode_loot_transfer(LootTransfer(17,18,11,deposits,withdrawals))
    assert packet==expected,(packet.hex(),expected.hex())
    return packet.hex()


if __name__=='__main__':
    item=lambda i,t,n:ItemRecord(i,t,b'\0\0',n,0,0,(0,0,0),b'\0'*4,None,b'\0'*3)
    cases=[container(()),container((item(0x60000000,301,1),item(0x60000001,3,50))),
           request(opening=True),request(),request(((1001,2),),((0x60000001,20),(0x60000000,1)))]
    cases.extend((consumer(()),consumer((item(0x60000000,301,1),item(0x60000001,3,50))),costs()))
    (ROOT/'evidence/battle_loot_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Original loot writers, consumer-to-window and AP defaults:8 cases PASS')
