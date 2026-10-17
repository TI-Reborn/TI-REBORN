"""Execute Arena BA/02 dispatch and numeric room parser; isolate allocation/strings/UI.
Nonempty cases stop after field decoding, before filtering/list insertion.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX


def run_case(nonempty):
    u=emulator(); heap=DATA+0x3000; captured={}
    # Independently hand-built wire hypothesis from 85fa88 call order.
    body=struct.pack('<IIBBIBB',101,202,3,4,303,5,6)+b'Room\0'+struct.pack('<IBBBB',404,7,8,9,10)
    packet=b'\xba\x02'+struct.pack('<h',int(nonempty))+(body if nonempty else b'')
    u.mem_write(DATA,packet)
    def hook(uc,addr,size,user):
        nonlocal heap
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if addr==0x40ce98:
            uc.reg_write(UC_X86_REG_EAX,heap);heap+=0x100;return_from_stub(uc)
        elif addr==0x605f1c:
            ptr=get32(uc,eax);raw=bytes(uc.mem_read(ptr,64)).split(b'\0',1)[0]
            put32(uc,eax,ptr+len(raw)+1);put32(uc,edx,heap);uc.mem_write(heap,raw+b'\0');heap+=0x100
            captured['string_hex']=raw.hex();return_from_stub(uc)
        elif addr==0x40b47c:
            put32(uc,eax,edx);return_from_stub(uc)
        elif addr in (0x9cfa38,0x68a094,0x8723e4):return_from_stub(uc)
        elif addr==0x85fcf6:
            captured['consumed']=get32(uc,uc.reg_read(UC_X86_REG_EBP)-8)-DATA
        elif addr==0x85fb8e:
            frame=get32(uc,uc.reg_read(UC_X86_REG_EBP)+8)
            record=get32(uc,frame-4)
            captured['consumed']=get32(uc,uc.reg_read(UC_X86_REG_EBX))-DATA
            captured['u32_at_00']=get32(uc,record);captured['u32_at_04']=get32(uc,record+4)
            captured['bytes']={hex(o):bytes(uc.mem_read(record+o,1))[0] for o in (0x10,0x1e,0x1d,0x1c,0x1a,0x1b,0x18,0x20)}
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,0xba);u.reg_write(UC_X86_REG_EDX,DATA+1)
    u.emu_start(0x86021c,STOP,count=20000)
    assert captured['consumed']==len(packet),captured
    if nonempty:
        assert captured['u32_at_00']==101 and captured['u32_at_04']==404
        assert list(captured['bytes'].values())==[3,4,5,6,7,8,9,10]
        assert captured['string_hex']==b'Room'.hex()
    else:assert u.reg_read(UC_X86_REG_EIP)==STOP
    return dict(packet_hex=packet.hex(),**captured)

if __name__=='__main__':
    result={'sha256':EXPECTED_SHA,'method':__doc__,'cases':[run_case(False),run_case(True)]}
    (ROOT/'evidence/arena_room_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Arena BA/02: empty dispatch and nonempty field parser PASS')

