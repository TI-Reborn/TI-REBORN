"""Execute original B2/06 request writer, B2/07 reader and 200-second expiry.

The wire scalars and reader branches run unmodified in Unicorn. Transport,
allocation, ignored-name lookup, palette and generic-list append are explicit
stubs. This verifies the native ABI and lifetime, without GUI-client claims.
"""
from dataclasses import asdict
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX
from tio.protocol.tactical_marks import (TacticalMark, PLACE, REMOVE, NATIVE_TTL_SECONDS,
    encode_tactical_mark,encode_tactical_mark_notification)


def builder(value):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    calls=[]
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==flush:
            calls.append(hex(address));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    sp=u.reg_read(UC_X86_REG_ESP);put32(u,sp+4,value.y)
    u.reg_write(UC_X86_REG_EAX,value.kind)
    u.reg_write(UC_X86_REG_EDX,value.character_id)
    u.reg_write(UC_X86_REG_ECX,value.x)
    u.emu_start(0x70e0a0,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert u.reg_read(UC_X86_REG_ESP)==sp+8
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==encode_tactical_mark(value)
    assert calls==[hex(flush)]
    return dict(fields=asdict(value),packet_hex=packet.hex(),builder='70e0a0')


def gui_place(*,button=1,x=2,y=3):
    """Run the physical right-button caller with the native LeftShift flag."""
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    for index,(global_address,value) in enumerate(((0xac60dc,1),(0xac5a30,1),
        (0xac57ac,0),(0xac561c,38),(0xac5494,38),(0xac5a98,17))):
        address=DATA+0x4000+index*16;put32(u,global_address,address);put32(u,address,value)
    calls=[]
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==0x9db7ac:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),x)
            put32(uc,uc.reg_read(UC_X86_REG_EDX),y);return_from_stub(uc)
        elif address==flush:
            calls.append(hex(address));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EDX,button)
    u.emu_start(0x710960,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    admitted=button==1 and 0<x<38 and 0<y<38
    assert packet==(encode_tactical_mark(TacticalMark(PLACE,17,x,y)) if admitted else b'')
    assert len(calls)==int(admitted)
    return dict(button=button,left_shift=True,x=x,y=y,packet_hex=packet.hex(),
                caller='710960→7109e2→70e0a0',coordinate_lookup_stub='9db7ac')


def reader(value):
    u=emulator();marker=DATA+0x1000;members=DATA+0x2000;list_root=DATA+0x4000
    pointer=DATA+0x5000;entries=DATA+0x5100;now=DATA+0x5200;palette=DATA+0x5300
    packet=encode_tactical_mark_notification(value)
    u.mem_write(DATA,packet[2:]);put32(u,0xac62a4,members)
    u.mem_write(members+2*0x1c0,b'\x01')
    put32(u,members+2*0x1c0+4,value.character_id)
    u.mem_write(members+2*0x1c0+0x10e,b'\x01')
    put32(u,0xac5dbc,pointer);put32(u,pointer,list_root)
    put32(u,list_root+4,entries);put32(u,list_root+8,int(value.kind==REMOVE))
    put32(u,entries,marker);put32(u,0xac5fe4,now);put32(u,now,1_000_000)
    put32(u,0xac5474,palette);put32(u,palette+4,0xff123456)
    if value.kind==REMOVE:
        u.mem_write(marker,bytes((PLACE,value.x,value.y)))
        put32(u,marker+4,900_000)
    allocated=marker if value.kind==PLACE else DATA+0x6000
    appended=[];freed=[];body_consumed=[]
    def hook(uc,address,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if address==0x406a50:
            assert eax==0x1c;uc.reg_write(UC_X86_REG_EAX,allocated);return_from_stub(uc)
        elif address==0x40c0d8:
            put32(uc,eax,0);return_from_stub(uc)
        elif address==0x67bf80:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0xa89494:
            uc.reg_write(UC_X86_REG_EAX,0xff123456);return_from_stub(uc)
        elif address==0x711358:
            appended.append(edx);return_from_stub(uc)
        elif address==0x406a6c:
            freed.append(eax);return_from_stub(uc)
        elif address==0x40b09c:return_from_stub(uc)
        elif address==0x70e2e6:
            body_consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x70e100,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert body_consumed==[7]
    if value.kind==PLACE:
        assert appended==[marker] and not freed
        assert bytes(u.mem_read(marker,3))==bytes((value.kind,value.x,value.y))
        assert get32(u,marker+4)==1_000_000 and get32(u,marker+0x14)==2
    else:
        assert not appended and not freed
        assert get32(u,marker+4)==1_000_000-NATIVE_TTL_SECONDS*1000+1000
    return dict(fields=asdict(value),packet_hex=packet.hex(),reader='70e100',
                consumed_body_bytes=body_consumed[0],appended=len(appended),
                mark_start_ms=get32(u,marker+4),member_index=get32(u,marker+0x14))


def expiry(elapsed_ms):
    u=emulator();marker=DATA+0x1000;now=DATA+0x2000;frame=STACK+0x7000
    put32(u,marker+4,1_000_000);put32(u,now,1_000_000+elapsed_ms);put32(u,0xac5fe4,now)
    u.reg_write(UC_X86_REG_EBX,marker);u.reg_write(UC_X86_REG_EBP,frame)
    destinations=[]
    def hook(uc,address,size,user):
        if address in (0x710ce5,0x710cfa):
            destinations.append(hex(address));uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x710cd4,STOP,count=100)
    assert destinations==[hex(0x710ce5 if elapsed_ms>200_000 else 0x710cfa)]
    return dict(elapsed_ms=elapsed_ms,removes=elapsed_ms>200_000,branch=destinations[0])


def main():
    cases=(TacticalMark(PLACE,17,2,3),TacticalMark(PLACE,0x12345678,255,0),
           TacticalMark(REMOVE,0,2,3))
    report=dict(binary_sha256=EXPECTED_SHA,method=__doc__,
                builders=[builder(value) for value in cases],
                gui_place=[gui_place(),gui_place(button=0),gui_place(x=0)],
                readers=[reader(value) for value in cases],
                expiry=[expiry(ms) for ms in (199_999,200_000,200_001)],
                native_gui='7109e2 places kind1;710a96 removes kindFF/character0',
                dispatch='962659 schedules70e100 for B2/07 (C2S builder writes B2/06)',
                ttl_source='710cde cmp elapsed_ms,0x30d40; strictly greater expires',
                left_shift_source='9f4f04..9f4f16 GetKeyState(VK_LSHIFT=0xA0) stores AC60DC')
    raw=BINARY.read_bytes();pe=pefile.PE(data=raw);md=Cs(CS_ARCH_X86,CS_MODE_32);md.skipdata=True
    selector=pe.get_data(0x962602+7-0x400000,1)[0]
    assert struct.unpack('<I',pe.get_data(0x962619+selector*4-0x400000,4))[0]==0x962659
    ranges=((0x70e0a0,0x60),(0x70e100,0x20a),(0x710960,0x175),
            (0x9f4ef4,0x3a),(0x962659,0x25),(0x710cd4,0x35))
    lines=[f'; Original binary: {BINARY}',f'; SHA-256: {EXPECTED_SHA}']
    for start,size in ranges:
        lines.append(f'\n; Native range {start:08x}+{size:x}')
        lines.extend(f'{ins.address:08x} {ins.bytes.hex():24} {ins.mnemonic:8} {ins.op_str}'
                     for ins in md.disasm(pe.get_data(start-0x400000,size),start))
    pe.close()
    (ROOT/'evidence/tactical_marks_native.asm').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (ROOT/'evidence/tactical_marks_native.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Original tactical marks: 3 writers / 3 right-button callers / 3 readers / 3 expiry gates PASS')


if __name__=='__main__':main()
