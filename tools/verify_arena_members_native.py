"""Original BA0B dispatcher/member consumer through return; strings/chat/UI isolated."""
from verify_auth_native import *


def run(member_id,pet_count):
    u=emulator();heap=DATA+0x3000;captured={};slots=DATA+0x5000
    for i,addr in enumerate((0xac6184,0xac6370,0xac5524,0xac5a98)):
        put32(u,addr,DATA+0x8000+i*16)
    put32(u,DATA+0x8030,1);put32(u,0xac62a4,slots)
    pet=bytes([2,1,0])+struct.pack('<5I',101,102,103,104,105)+b'Fighter\0'+struct.pack('<2I',106,107)
    member=struct.pack('<I',member_id)+b'Player\0'+struct.pack('<IBBh',55,7,1,pet_count)+pet*pet_count
    packet=b'\xba\x0b'+struct.pack('<IBh',42,0,1)+member
    u.mem_write(DATA,packet)
    def hook(uc,addr,size,user):
        nonlocal heap
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if addr==0x605f1c:
            ptr=get32(uc,eax);raw=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
            put32(uc,eax,ptr+len(raw)+1);put32(uc,edx,heap);uc.mem_write(heap,bytes([len(raw)])+raw);heap+=0x100;return_from_stub(uc)
        elif addr==0x40c06c:
            n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));return_from_stub(uc)
        elif addr==0x40b47c:put32(uc,eax,edx);return_from_stub(uc)
        elif addr in (0x9cfa38,0x68a094,0x40b09c,0x40b0fc,0xa03698,0xa03864,0xa03344,0xa01ef4,0xa017c8,0x8724ec,0xa03040,0x872480,0x8724d0):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif addr==0x8601f7:captured['consumed']=get32(uc,uc.reg_read(UC_X86_REG_EBP)-12)-DATA
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,0xba);u.reg_write(UC_X86_REG_EDX,DATA+1)
    u.emu_start(0x86021c,STOP,count=30000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert captured['consumed']==len(packet)
    captured['room_id']=get32(u,DATA+0x8000);captured['in_room']=bytes(u.mem_read(DATA+0x8010,1))[0]
    assert captured['room_id']==(42 if member_id==1 else 0xffffffff)
    assert captured['in_room']==int(member_id==1)
    assert get32(u,slots+4)==member_id and get32(u,slots+0x114)==55
    for i in range(pet_count):
        ptr=slots+0x120+i*0x28
        assert get32(u,ptr+4)==101 and get32(u,ptr+8)==102
        assert get32(u,ptr+0x1c)==102 # third wireu32 is decremented
        assert get32(u,ptr+0x20)==104 and get32(u,ptr+0x24)==105
        assert get32(u,ptr+0x10)==106 and get32(u,ptr+0x14)==107
    return dict(packet_hex=packet.hex(),pet_count=pet_count,member_id=member_id,**captured)

if __name__=='__main__':
    cases=[run(1,0),run(1,3),run(2,1)]
    (ROOT/'evidence/arena_members_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Arena BA0B full consumer:3 cases PASS (self present/absent,0/3 pets)')
