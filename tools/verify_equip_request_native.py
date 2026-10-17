"""Verify the original Wear button callback and item action33 writer separately.

UI collection/class checks, metadata lookup and managed lifetime are isolated.
Does not execute the intermediate a6516c policy or prove a server response.
"""
from verify_auth_native import *


def callback(selected=0, owner_index=0):
    u=emulator(); button=DATA+0x100; collection=DATA+0x200
    control=DATA+0x400; item=DATA+0x800; owners=DATA+0xc00; pet=DATA+0xd00
    metadata=DATA+0x2000; calls=[]
    put32(u,button+0x4c,collection)
    put32(u,control+0x294,selected & 0xffffffff); put32(u,control+0x2cc,owner_index & 0xffffffff)
    put32(u,control+0x2c8,item); put32(u,item+0x28,1001)
    put32(u,0xac618c,owners); put32(u,owners,pet); put32(u,pet+0x28,17)
    put32(u,0xac637c,DATA+0x1800); put32(u,DATA+0x1800,metadata)
    sp=u.reg_read(UC_X86_REG_ESP); put32(u,sp+4,button)
    def hook(uc,address,size,user):
        result={0xa424d4:1,0xa424c4:control,0x4095ac:1,0x4095d0:control,0xa7b030:0}
        if address in result:
            uc.reg_write(UC_X86_REG_EAX,result[address]);return_from_stub(uc)
        elif address==0xa6516c:
            pointer=uc.reg_read(UC_X86_REG_EDX)
            calls.append((uc.reg_read(UC_X86_REG_EAX),get32(uc,pointer+0x28),uc.reg_read(UC_X86_REG_ECX)))
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x8d4ab8,STOP,count=1500)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert calls==([] if selected==-1 or owner_index==-1 else [(17,1001,0)])
    return {'selected':selected,'owner_index':owner_index,'policy_arguments':calls}


def writer(pet_id, item_id, option):
    u=emulator(); obj=DATA+0x1000; handle=DATA+0x3000; vtable=DATA+0x3100; flush=DATA+0x3200
    item=DATA+0x4000; metadata=DATA+0x5000
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    put32(u,0xac637c,DATA+0x3300);put32(u,DATA+0x3300,metadata)
    u.mem_write(metadata+0x68d,b'\x01')
    sp=u.reg_read(UC_X86_REG_ESP);put32(u,sp+4,option)
    def hook(uc,address,size,user):
        values={0x99f5d8:0,0xa7b030:0,0x66754c:1,0xa93eec:1,0x6748b0:handle}
        if address in values:
            uc.reg_write(UC_X86_REG_EAX,values[address]);return_from_stub(uc)
        elif address in (0x40cb10,0x40b09c,0x40c9a4,flush):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,pet_id);u.reg_write(UC_X86_REG_EDX,item_id);u.reg_write(UC_X86_REG_ECX,item)
    u.emu_start(0x9903a4,STOP,count=4000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==b'\x33'+struct.pack('<IIB',pet_id,item_id,option)
    return {'pet_id':pet_id,'instance_id':item_id,'option':option,'packet_hex':packet.hex()}


if __name__=='__main__':
    result={'sha256':EXPECTED_SHA,'method':__doc__,
            'static_binding':'m492 Wear -> interface+0xc ->8d52d1 ->8d5458 ->8d4ab8 ->a6516c; a65b53 ->9903a4',
            'callback_cases':[callback(),callback(-1),callback(owner_index=-1)],
            'writer_cases':[writer(17,1001,255),writer(42,0x12345678,0),writer(1,9,3)]}
    (ROOT/'evidence/equip_request_native.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Wear callback 3 cases; original item action33 writer 3 cases PASS')
