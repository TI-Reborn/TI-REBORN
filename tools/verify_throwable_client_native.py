"""Execute the released-chain candidate's x86 effects parser/draw callbacks.

GPU submission, file/resource loading, clock and audio output are explicit
external stubs. This is not a graphical-client or audible-playback test.
"""
from pathlib import Path
import json,struct,sys,hashlib
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE,UC_HOOK_MEM_INVALID
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_throwable_effects as fx
from tio.protocol.battle_item_visuals import encode_item_visuals


def run(image_base=0x400000):
    source=(ROOT/'reports/throwable-effects/silver-source.dll').read_bytes()
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
        if at==0x814608:ret()
        elif at==clock:ret(result=state['tick'])
        elif at==0xa896f0:
            x=u.reg_read(UC_X86_REG_EAX);y=u.reg_read(UC_X86_REG_EDX);put(x,get(x)+500);put(y,get(y)+300);ret()
        elif at==0x2000260:
            sp=u.reg_read(UC_X86_REG_ESP);row=get(sp+4);name=get(sp+8)
            text=bytes(u.mem_read(name,get(name-4))).decode()
            assert text.startswith('gfx\\tio-effects\\')
            state['loads'].append(text);put(row,0x12345678);put(row+4,0);put(row+8,(get(sp+16)&65535)|((get(sp+12)&65535)<<16));ret(28)
        elif at==0x2000220:
            sp=u.reg_read(UC_X86_REG_ESP);args=[get(sp+4+i*4) for i in range(10)]
            handle,_,_,x,y,width,height,frame,tint,flags=args
            assert flags==0 and frame<32 and 16<=width<=256 and 16<=height<=256,args
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
        u.mem_write(0x2001000,packet[1:]);u.reg_write(UC_X86_REG_EAX,packet[0]);u.reg_write(UC_X86_REG_EDX,0x2001000);u.reg_write(UC_X86_REG_ECX,len(packet));execute(fx.READER)
    snapshot(encode_item_visuals(((1,2,1),(2,2,2),(3,2,4),(4,2,5),(5,2,3))))
    assert get(0x400000+fx.old.COUNT)==5
    execute(fx.DRAW);assert len(state['draws'])==4 and len(state['loads'])==4
    assert state['sounds']==['tio_fx_flare_start','tio_fx_smoke','tio_fx_fire']
    first=state['draws'][1]['frame'];state['tick']+=65;execute(fx.DRAW)
    assert state['draws'][5]['frame']!=first and len(state['sounds'])==3
    state['tick']+=1000;execute(fx.DRAW);assert len(state['sounds'])==6
    snapshot(encode_item_visuals(()));count=len(state['draws']);execute(fx.DRAW);assert len(state['draws'])==count
    snapshot(b'\xf7\1\1\0\1\2\6');assert get(0x400000+fx.old.COUNT)==0
    snapshot(encode_item_visuals(((1,2,1),)));put(0x2000000,0);execute(fx.DRAW);assert len(state['draws'])==count
    return dict(passed=True,candidate_sha256=hashlib.sha256(candidate).hexdigest(),loads=state['loads'],
        sprite_draws=len(state['draws']),sounds=state['sounds'],frame_advancement=True,malformed_clears=True,
        empty_snapshot_clears=True,city_clears=True,stack_balanced=True,graphical_clients_used=False)


if __name__=='__main__':
    result=run();run(0x1400000);result['relocated_image_passed']=True
    (ROOT/'reports/throwable-effects/client-native.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
