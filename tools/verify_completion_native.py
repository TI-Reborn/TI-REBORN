"""Original transport02 branch, queue call captured rather than executing allocator."""
import json,struct,hashlib,sys
from pathlib import Path
import unicorn as U
from unicorn.x86_const import UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EIP
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.protocol.transport import InitialCompletion,encode_initial_completion

def run(status,flag,value,state):
    raw=(ROOT/'evidence/loader-user32-fix/unpacked-0xc9b0000.bin').read_bytes()
    uc=U.Uc(U.UC_ARCH_X86,U.UC_MODE_32);base=0xc9b0000
    uc.mem_map(base,0x7000);uc.mem_write(base,raw)
    uc.mem_map(0x2000000,0x20000)
    obj=0x2000000;conn=obj+0x1000;buf=obj+0x2000;stack=obj+0x18000;stop=obj+0x1f000
    payload=encode_initial_completion(InitialCompletion(status,flag,value))
    uc.mem_write(buf,payload);uc.mem_write(conn+0x1e,struct.pack('<H',state))
    uc.mem_write(stack,struct.pack('<4I',stop,conn,buf,len(payload)))
    uc.reg_write(UC_X86_REG_ECX,obj);uc.reg_write(UC_X86_REG_ESP,stack)
    queues=[]
    def hook(u,address,size,user):
        if address==base+0x1f70:
            sp=u.reg_read(UC_X86_REG_ESP)
            ret,p,n=struct.unpack('<3I',u.mem_read(sp,12))
            queues.append(bytes(u.mem_read(p,n)).hex())
            u.reg_write(UC_X86_REG_ESP,sp+12);u.reg_write(UC_X86_REG_EIP,ret)
    uc.hook_add(U.UC_HOOK_CODE,hook)
    uc.emu_start(base+0x2250,stop,count=10000)
    assert uc.reg_read(UC_X86_REG_EIP)==stop
    after=int.from_bytes(uc.mem_read(conn+0x1e,2),'little')
    saved=int.from_bytes(uc.mem_read(obj+0x1c3,4),'little')
    if state!=0:assert not queues and after==state
    elif status==0:
        assert after==1 and saved==value and queues==[(b'\x02\0'+struct.pack('<I',value)).hex()]
    else:
        assert after==0 and saved==0 and bytes.fromhex(queues[0])[:2]==bytes((2,status))
    return {'input_hex':payload.hex(),'state_before':state,'state_after':after,'queue_hex':queues,'saved_u32':saved}

def main():
    image=ROOT/'evidence/loader-user32-fix/unpacked-0xc9b0000.bin'
    manifest=json.loads((ROOT/'evidence/manifest.json').read_text())
    expected=next(x['sha256'] for x in manifest['files'] if x['path']==image.relative_to(ROOT/'evidence').as_posix())
    assert hashlib.sha256(image.read_bytes()).hexdigest()==expected
    cases=[run(0,flag,value,0) for flag in (0,0xff) for value in (0,0x11223344,0xffffffff)]
    cases += [run(status,0,None,0) for status in (1,0xff)]
    cases += [run(0,0,0x11223344,1)]
    raw=(ROOT/'evidence/loader-user32-fix/unpacked-0xc9b0000.bin').read_bytes()
    (ROOT/'evidence/native_completion_probe.json').write_text(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'method':'original 0x2250 dispatcher/02 parser and primitive readers/writers; queue 0x1f70 stubbed to record bytes; no socket','cases':cases},indent=2)+'\n',encoding='utf-8')
    print('9 original-x86 completion cases passed.')

if __name__=='__main__':main()
