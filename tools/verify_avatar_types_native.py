"""Execute the released-chain avatar assignment and original catalog/image readers.

GPU submission, file/resource loading, clock and audio output are explicit
external stubs. This is not a graphical-client or audible-playback test.
"""
from pathlib import Path
import json,struct,sys,hashlib
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE,UC_HOOK_MEM_INVALID
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_avatar_types as fx
from tio.protocol.battle_item_visuals import encode_item_visuals


def run(image_base=0x400000, *, source_path=None, max_avatar=10006):
    source=(source_path or ROOT/'reports/avatar-types/silver-source.dll').read_bytes()
    candidate=fx.patch(source);pe=pefile.PE(data=candidate);delta=image_base-0x400000
    pe.relocate_image(image_base)
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0,0x1000);u.mem_map(image_base,(pe.OPTIONAL_HEADER.SizeOfImage+4095)&~4095)
    u.mem_write(image_base,pe.get_memory_mapped_image());u.mem_map(0x2000000,0x10000);u.mem_map(0x3000000,0x10000)
    stop=0x3000100;clock=0x2000200;state=dict(tick=10000,draws=[],sounds=[],loads=[])
    def canonical(at):return at+delta if 0x400000<=at<0x400000+pe.OPTIONAL_HEADER.SizeOfImage else at
    def put(at,v):u.mem_write(canonical(at),struct.pack('<I',v))
    def get(at):return struct.unpack('<I',u.mem_read(canonical(at),4))[0]
    def ret(n=0,result=None):
        sp=u.reg_read(UC_X86_REG_ESP);target=get(sp);u.reg_write(UC_X86_REG_ESP,sp+n+4);u.reg_write(UC_X86_REG_EIP,target)
        if result is not None:u.reg_write(UC_X86_REG_EAX,result)
    def hook(u,at,size,_):
        if image_base<=at<image_base+pe.OPTIONAL_HEADER.SizeOfImage:at-=delta
        if at in (0x814608,0xc79000):ret()
        elif at==clock:ret(result=state['tick'])
        elif at==0xa896f0:
            x=u.reg_read(UC_X86_REG_EAX);y=u.reg_read(UC_X86_REG_EDX);put(x,get(x)+500);put(y,get(y)+300);ret()
        elif at==0x2000260:
            sp=u.reg_read(UC_X86_REG_ESP);row=get(sp+4);name=get(sp+8)
            text=bytes(u.mem_read(name,get(name-4))).decode()
            assert text=='gfx\\rain.tga'
            state['loads'].append(text);put(row,0x12345678);put(row+4,0);put(row+8,(get(sp+16)&65535)|((get(sp+12)&65535)<<16));ret(28)
        elif at==0x2000220:
            sp=u.reg_read(UC_X86_REG_ESP);args=[get(sp+4+i*4) for i in range(10)]
            handle,_,_,x,y,width,height,frame,tint,flags=args
            assert flags==0 and frame<32 and width==8 and height==32,args
            assert handle==0x12345678
            state['draws'].append(dict(x=x,y=y,frame=frame,width=width,height=height,tint=tint))
            ret(40)
        elif at==0x4f2864:ret(12)
        elif at==0x2000240:
            name=get(u.reg_read(UC_X86_REG_ESP)+4);state['sounds'].append(bytes(u.mem_read(name,get(name-4))).decode());ret(4)
        elif at==stop:u.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    def invalid(u,access,address,size,value,_):
        raise AssertionError('Unmapped access '+hex(address)+' at '+hex(u.reg_read(UC_X86_REG_EIP)))
    u.hook_add(UC_HOOK_MEM_INVALID,invalid)
    for global_at,target,value in ((0xac64a0,0x2000000,1),(0xac61b0,0x2000004,0),(0xac6068,0x2000008,0)):
        put(global_at,target);put(target,value)
    put(0xb79b10,clock)
    for global_at,slot,target in ((0xac5b88,0x2000280,0x2000220),(0xac5ce4,0x2000284,0x2000240),(0xac5dfc,0x2000288,0x2000260)):
        put(global_at,slot);put(slot,target)
    def execute(address):
        sp=0x3008000;put(sp,stop);u.reg_write(UC_X86_REG_ESP,sp)
        try:u.emu_start(address+delta,stop,count=200000)
        except Exception as error:
            raise RuntimeError('Native failure at '+hex(u.reg_read(UC_X86_REG_EIP))+' EBX='+hex(u.reg_read(UC_X86_REG_EBX))+' EAX='+hex(u.reg_read(UC_X86_REG_EAX))) from error
        assert u.reg_read(UC_X86_REG_EIP)==stop
        assert u.reg_read(UC_X86_REG_ESP)==sp+4,'Stack imbalance'
    def snapshot(packet):
        u.mem_write(0x2001000,packet[1:]);u.reg_write(UC_X86_REG_EAX,packet[0]);u.reg_write(UC_X86_REG_EDX,0x2001000);u.reg_write(UC_X86_REG_ECX,len(packet));execute(fx.ENTRY)
    from tio.avatars import encode_assignments
    put(0xac618c,0x2006000)
    for slot,identity in enumerate((1,2,9)):
        pointer=0x2007000+slot*0x400;put(0x2006000+slot*4,pointer);put(pointer+0x28,identity);put(pointer+0x278,0)
    def assign(packet):
        u.mem_write(0x2001000,packet[1:]);u.reg_write(UC_X86_REG_EAX,packet[0]);u.reg_write(UC_X86_REG_EDX,0x2001000);u.reg_write(UC_X86_REG_ECX,len(packet));execute(fx.ENTRY)
    first,second,third=max_avatar-2,max_avatar-1,max_avatar
    wire=encode_assignments(((1,first),(2,second),(9,third)))
    assign(wire);assert get(0x2007278)==first and get(0x2007678)==second and get(0x2007a78)==third
    assign(encode_assignments(((1,0),)));assert get(0x2007278)==0
    for invalid in (wire[:-1],wire+b'\0',b'\xfc\2'+wire[2:],b'\xfc\1\1\0'+bytes(8),b'\xfc\1\1\0'+struct.pack('<II',1,max_avatar+1)):
        assign(invalid);assert get(0x2007278)==0 and get(0x2007678)==second
    from deploy import client_battle_items as old
    assign(encode_item_visuals(((1,2,1),)));assert get(0x400000+old.COUNT)==1
    return dict(passed=True,candidate_sha256=hashlib.sha256(candidate).hexdigest(),native_actor_assignment=True,
        reset_to_default=True,invalid_packets_atomic=True,previous_reader_preserved=True,stack_balanced=True,graphical_clients_used=False)



def original_catalog():
    from verify_auth_native import emulator,DATA,STACK,STOP,get32,return_from_stub
    from tio.avatars import encode_catalog,catalog,image_packet
    import zlib
    u=emulator();packet=encode_catalog();u.mem_write(DATA,packet[1:]);calls=[]
    def hook(uc,at,size,user):
        if at in (0x6afdf4,0x6afd88,0x9cfa38):return_from_stub(uc)
        elif at==0x6ac0a6:uc.reg_write(UC_X86_REG_EIP,0x6ac0fd)
        elif at==0x6aff04:
            p=uc.reg_read(UC_X86_REG_EAX)
            calls.append((get32(uc,p),int.from_bytes(uc.mem_read(p+4,1),'little'),get32(uc,p+8),uc.reg_read(UC_X86_REG_ESI)));return_from_stub(uc)
        elif at in (0x6ac1ef,STOP):uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,0xac);u.reg_write(UC_X86_REG_EDX,DATA);u.reg_write(UC_X86_REG_ECX,len(packet));u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.mem_write(STACK+0x8000,struct.pack('<I',STOP));u.emu_start(0x6ac188,STOP,count=10000)
    assert calls==[(i,int(r.get('premium',True)),0,r['crc32']) for i,r in catalog().items()],calls
    def execute(at):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.mem_write(STACK+0x8000,struct.pack('<I',STOP));u.emu_start(at,STOP,count=100000)
    execute(0x68abec)
    for identity in catalog():
        raw=image_packet(identity)[8:];u.mem_write(DATA,raw);u.reg_write(UC_X86_REG_EAX,0xffffffff);u.reg_write(UC_X86_REG_EDX,DATA);u.reg_write(UC_X86_REG_ECX,len(raw));execute(0x68ab38)
        assert (~u.reg_read(UC_X86_REG_EAX)&0xffffffff)==zlib.crc32(raw)
    for identity in catalog():
        receiver=emulator();packet=image_packet(identity);receiver.mem_write(DATA,packet[1:]);saved=[]
        def image_hook(uc,at,size,user):
            if at==0x9cfa38:return_from_stub(uc)
            elif at==0x6abefa:uc.reg_write(UC_X86_REG_EIP,0x6abf7e)
            elif at==0xa89740:
                saved.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),uc.reg_read(UC_X86_REG_ECX))));return_from_stub(uc)
            elif at==0x6ac1ef:uc.emu_stop()
        receiver.hook_add(UC_HOOK_CODE,image_hook);receiver.reg_write(UC_X86_REG_EAX,0xac);receiver.reg_write(UC_X86_REG_EDX,DATA)
        receiver.reg_write(UC_X86_REG_ESP,STACK+0x8000);receiver.mem_write(STACK+0x8000,struct.pack('<I',STOP));receiver.emu_start(0x6ac188,STOP,count=10000)
        assert saved==[packet[8:]]
    return dict(passed=True,original_ac08_reader_records=calls,original_ac06_images_received=len(catalog()),original_crc32_checked=True,file_cache_and_gui_stubs=True,graphical_clients_used=False)


if __name__=='__main__':
    result=run();run(0x1400000);result['relocated_image_passed']=True;result['original_catalog']=original_catalog()
    (ROOT/'reports/avatar-types/client-native.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
