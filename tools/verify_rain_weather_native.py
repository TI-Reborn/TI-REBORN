"""Execute the released-chain candidate's x86 rain parser/draw callbacks.

GPU submission, file/resource loading, clock and audio output are explicit
external stubs. This is not a graphical-client or audible-playback test.
"""
from pathlib import Path
import json,struct,sys,hashlib
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE,UC_HOOK_MEM_INVALID
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_rain_weather as fx
from tio.protocol.battle_item_visuals import encode_item_visuals


def run(image_base=0x400000):
    source=(ROOT/'reports/rain-weather/silver-source.dll').read_bytes()
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
        u.mem_write(0x2001000,packet[1:]);u.reg_write(UC_X86_REG_EAX,packet[0]);u.reg_write(UC_X86_REG_EDX,0x2001000);u.reg_write(UC_X86_REG_ECX,len(packet));execute(fx.READER)
    from tio.protocol.weather import encode_weather
    wet=encode_weather(True,0,((1,2),(5,6)))
    snapshot(wet);assert get(0x400000+fx.COUNT)==2
    execute(fx.DRAW);assert len(state['draws'])==2 and state['loads']==['gfx\\rain.tga']
    assert state['sounds']==['tio_weather_rain']
    first=state['draws'][0]['y'];state['tick']+=65;execute(fx.DRAW)
    assert state['draws'][2]['y']!=first and len(state['sounds'])==1
    snapshot(encode_weather(True,1,((1,2),(5,6))));execute(fx.DRAW);execute(fx.DRAW)
    assert state['sounds'].count('tio_weather_thunder')==1
    state['tick']+=1000;execute(fx.DRAW);assert state['sounds'].count('tio_weather_rain')==2
    snapshot(encode_weather(False,0,()));count=len(state['draws']);execute(fx.DRAW);assert len(state['draws'])==count
    for bad in (wet[:-1],wet+b'\0',b'\xfb\2'+wet[2:],b'\xfb\1\1\0\0\0\0\1\0\xff\0'):
        snapshot(wet);snapshot(bad);assert get(0x400000+fx.COUNT)==0
    # Existing F7 parser is reached through the complete previous reader chain.
    snapshot(encode_item_visuals(((1,2,1),)))
    from deploy import client_battle_items as old
    assert get(0x400000+old.COUNT)==1
    snapshot(wet);put(0x2000000,0);execute(fx.DRAW);assert len(state['draws'])==count
    return dict(passed=True,candidate_sha256=hashlib.sha256(candidate).hexdigest(),loads=state['loads'],
        sprite_draws=len(state['draws']),sounds=state['sounds'],animation_advancement=True,malformed_clears=True,
        empty_snapshot_clears=True,city_clears=True,previous_reader_preserved=True,stack_balanced=True,graphical_clients_used=False)



if __name__=='__main__':
    result=run();run(0x1400000);result['relocated_image_passed']=True
    (ROOT/'reports/rain-weather/client-native.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
