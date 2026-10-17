"""Run original63f60c and63ead4 serializers; only managed string cleanup stubbed.

Ordinary item records have all optional metadata absent.
"""
from verify_auth_native import *
from tio.protocol.warehouse import WarehouseItem, encode_warehouse_list


def run(kind, total, segment, items):
    u=emulator();record=DATA+0x1000;array=DATA+0x2000
    put32(u,0xacd0e0,DATA);put32(u,0xacd0f0,0)
    u.mem_write(record,bytes((kind,1))+struct.pack('<H',total)+b'\x01\0'+struct.pack('<H',segment)+b'\x01')
    put32(u,record+12,array);put32(u,record+16,len(items));put32(u,record+20,DATA+0x3000)
    if items:u.mem_write(DATA+0x3000,b'\x01'*len(items))
    for index,item in enumerate(items):
        base=array+index*84
        for offset,value in ((0,item.instance_id),(8,item.template_id),(16,item.count)):
            put32(u,base+offset,value);u.mem_write(base+offset+4,b'\x01')
        for offset,value in ((22,item.durability),(26,item.max_durability),(30,item.calculated_max_durability)):
            u.mem_write(base+offset,struct.pack('<H',value));u.mem_write(base+offset+2,b'\x01')
        for offset,value in ((33,item.enhance_level),(35,item.damage_enhance_level),(37,item.special_enhance),(39,item.marked),(41,item.rented)):
            u.mem_write(base+offset,bytes((int(value),1)))
        if item.mark_time_left is not None:
            put32(u,base+52,item.mark_time_left);u.mem_write(base+56,b'\x01')
    def hook(uc,address,size,user):
        if address==0x40b0e4:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,record)
    u.emu_start(0x63f60c,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(DATA,get32(u,0xacd0f0)))
    assert packet==encode_warehouse_list(kind,total,segment,items)
    return dict(packet_hex=packet.hex(),items=len(items))


if __name__=='__main__':
    item=WarehouseItem(1001,301,1,280,300,300)
    cases=[run(0,1,0,()),run(0,1,0,(item,)),run(1,2,1,(item,WarehouseItem(2002,326,3,1,2,3,4,5,True,True,True,123456)))]
    (ROOT/'evidence/warehouse_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Original warehouse serializers: 3 cases PASS')
