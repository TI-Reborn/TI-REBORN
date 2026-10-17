"""Run original Arena request builders and real byte/u32 writers; stub transport/UI."""
from verify_auth_native import *


def run(entry,eax=0,edx=0,*,room_id=0xffffffff,character_id=1,target_id=2,ready=0):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vtable=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush)
    put32(u,0xac600c,handle);put32(u,0xac5fa0,DATA+0x3300)
    put32(u,0xac489c,room_id)
    put32(u,0xac5a98,DATA+0x3400);put32(u,DATA+0x3400,character_id)
    put32(u,0xac48a4,target_id)
    put32(u,0xac62a4,DATA+0x5000)
    u.mem_write(DATA+0x5000,b'\x01');put32(u,DATA+0x5004,character_id)
    u.mem_write(DATA+0x5110,bytes((ready,)))
    def hook(uc,addr,size,user):
        if addr==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif addr in (0x87b43c,0x87b4c0):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif addr in (0x87b170,0x8723e4,flush):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,eax);u.reg_write(UC_X86_REG_EDX,edx)
    u.emu_start(entry,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))

if __name__=='__main__':
    cases=[]
    for entry,a,b,expected in (
        (0x85f890,0,0,'ba01'),(0x85f954,3,7,'ba030307'),
        (0x85f99c,0x12345678,0,'ba0478563412'),
        (0x85f9d4,0x12345678,9,'ba057856341209'),
        (0x85fa18,5,0,'ba0705'),(0x85fa50,6,0,'ba0906')):
        packet=run(entry,a,b);assert packet.hex()==expected,(hex(entry),packet.hex())
        cases.append({'entry':hex(entry),'eax':a,'edx':b,'packet_hex':packet.hex()})
    for entry,room,char,target,expected in (
        (0x872430,0xffffffff,11,22,''),
        (0x872430,42,11,22,'ba050b00000000'),
        (0x87a0ac,42,11,22,'ba051600000001')):
        packet=run(entry,room_id=room,character_id=char,target_id=target)
        assert packet.hex()==expected
        cases.append({'entry':hex(entry),'room_id':room,'character_id':char,'target_id':target,'packet_hex':packet.hex()})
    (ROOT/'evidence/arena_requests_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Arena original request builders/callbacks:9 cases PASS')
