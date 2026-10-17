"""Execute the published native ACK dispatcher/reader; UI and audio are stubs."""
from pathlib import Path
import hashlib,json,struct,sys
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tio.protocol.quest_ack import encode_ack


def run(identity):
    raw=(ROOT/'reports/throwable-effects/client/silver.dll').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='5f2eb65cede38dc146c0656a35d1ed27c45dec2175ba97c2c7d7ea2c3bbbbac9'
    pe=pefile.PE(data=raw);im=pe.get_memory_mapped_image()
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0,4096);u.mem_map(0x400000,(len(im)+4095)&~4095);u.mem_write(0x400000,im)
    u.mem_map(0x2000000,65536);u.mem_map(0x3000000,65536)
    data=0x2000000;stop=0x3000100;stack=0x3008000;report={}
    get=lambda at:struct.unpack('<I',u.mem_read(at,4))[0]
    def put(at,n):u.mem_write(at,struct.pack('<I',n))
    def ret(n=0):
        sp=u.reg_read(UC_X86_REG_ESP);u.reg_write(UC_X86_REG_EIP,get(sp));u.reg_write(UC_X86_REG_ESP,sp+4+n)
    def hook(u,at,size,_):
        if at==stop:u.emu_stop()
        elif at==0x9cfa38:ret()
        elif at==0x68a850:
            report['callback']=get(u.reg_read(UC_X86_REG_ESP)+4)
            report['payload']=u.reg_read(UC_X86_REG_EDX)
            report['subcode']=u.reg_read(UC_X86_REG_EAX)&255;ret(4)
        elif at==0x698804:
            report['queued_id']=u.reg_read(UC_X86_REG_EDX)
            report['consumed']=get(u.reg_read(UC_X86_REG_EBP)-4)-(data+2);ret()
        elif at==0x6980a4:u.reg_write(UC_X86_REG_EAX,2);ret()
        elif at==0x9cada4:report['native_dialogue_called']=True;ret()
        elif at in (0x40b0fc,0x40c9f4):ret()
    u.hook_add(UC_HOOK_CODE,hook)
    packet=encode_ack(identity);u.mem_write(data,packet);put(stack,stop)
    u.reg_write(UC_X86_REG_ESP,stack);u.reg_write(UC_X86_REG_EAX,0xb8)
    u.reg_write(UC_X86_REG_EDX,data+1);u.reg_write(UC_X86_REG_ECX,len(packet))
    u.emu_start(0x9cc548,stop+1,count=20000)
    assert u.reg_read(UC_X86_REG_EIP)==stop and report['callback']==0x9cc230 and report['subcode']==0x10
    assert u.reg_read(UC_X86_REG_EAX)&255==1
    put(0xac59c4,data+0x100);put(data+0x100,data+0x200)
    put(stack,stop);u.reg_write(UC_X86_REG_ESP,stack);u.reg_write(UC_X86_REG_EAX,report['payload'])
    u.emu_start(report['callback'],stop+1,count=20000)
    assert u.reg_read(UC_X86_REG_EIP)==stop and report['queued_id']==identity and report['consumed']==4
    assert report['native_dialogue_called']
    return report


if __name__=='__main__':
    result=dict(passed=True,cases=[run(n) for n in (1000,1002,1004,1023,1111,1018)],
        limitations=['Quest manager/UI rendering are stubs; no actual graphical client or audible playback'],
        sound_dispatch='Original 9CAFB2 loads ACK.sound and 9CAFB5 calls original sound bridge6A1090',
        continue_button='Original9CB3C0 only drains local queue; no lesson completion network request')
    (ROOT/'reports/tutorial-dialogues/native.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Published native B8/10 dispatcher and Cardinal ACK reader: 6 cases PASS')
