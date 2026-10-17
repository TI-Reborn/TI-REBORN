"""Original09 dispatcher/key derivation/builders; send1c90 stubbed.
Original2680 cipher then runs with derived key; socket/allocation not emulated.
"""
import json,struct,hashlib,sys
from pathlib import Path
import unicorn as U
from unicorn.x86_const import UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EIP
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tio.protocol.mode1 import *
from tio.protocol.transport import InitialCipher

def run(raw,seed,declared=None):
    u=U.Uc(U.UC_ARCH_X86,U.UC_MODE_32);base=0xc9b0000
    u.mem_map(base,0x7000);u.mem_write(base,raw);u.mem_map(0x2000000,0x20000)
    obj=0x2000000;conn=obj+0x1000;buf=obj+0x2000;stack=obj+0x18000;stop=obj+0x1f000
    payload=encode_mode1_challenge(seed);length=len(payload) if declared is None else declared
    u.mem_write(buf,payload);u.mem_write(conn+0x1e,struct.pack('<H',2))
    u.mem_write(obj+0x1bf,struct.pack('<II',0x12345678,0x11223344))
    u.mem_write(stack,struct.pack('<4I',stop,conn,buf,length))
    u.reg_write(UC_X86_REG_ECX,obj);u.reg_write(UC_X86_REG_ESP,stack)
    sent=[]
    def hook(uc,addr,size,user):
        if addr==base+0x1c90:
            sp=uc.reg_read(UC_X86_REG_ESP);ret,p,n=struct.unpack('<3I',uc.mem_read(sp,12))
            sent.append(bytes(uc.mem_read(p,n)));uc.reg_write(UC_X86_REG_ESP,sp+12);uc.reg_write(UC_X86_REG_EIP,ret)
    u.hook_add(U.UC_HOOK_CODE,hook);u.emu_start(base+0x2250,stop,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==stop
    if length<=8:
        assert not sent and bytes(u.mem_read(conn+5,1))==b'\0'
        return {'declared_length':length,'sent':False}
    key=derive_mode1_key(seed)
    assert bytes(u.mem_read(conn+6,8))==key and bytes(u.mem_read(conn+14,8))==key
    assert bytes(u.mem_read(conn+5,1))==b'\1'
    assert bytes(u.mem_read(conn+0x1e,2))==b'\x02\0'
    assert sent==[encode_mode1_reply(Mode1Reply(0x12345678,0x11223344))]
    # Execute actual native sender cipher with the negotiated key.
    u.mem_write(buf,sent[0]);u.mem_write(stack,struct.pack('<4I',stop,conn,buf,len(sent[0])))
    u.reg_write(UC_X86_REG_ECX,obj);u.reg_write(UC_X86_REG_ESP,stack)
    u.emu_start(base+0x2680,stop,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==stop
    cipher=InitialCipher('C2S',key);expected=cipher.transform(sent[0],encrypt=True)
    assert bytes(u.mem_read(buf,len(sent[0])))==expected
    assert bytes(u.mem_read(conn+14,8))==bytes(cipher.key)
    return {'seed_hex':seed.hex(),'key_hex':key.hex(),'reply_hex':sent[0].hex(),'encrypted_hex':expected.hex(),'key_after_hex':cipher.key.hex()}

def completion(raw,status,state):
    u=U.Uc(U.UC_ARCH_X86,U.UC_MODE_32);base=0xc9b0000
    u.mem_map(base,0x7000);u.mem_write(base,raw);u.mem_map(0x2000000,0x20000)
    obj=0x2000000;conn=obj+0x1000;buf=obj+0x2000;stack=obj+0x18000;stop=obj+0x1f000
    payload=encode_mode1_completion(status);u.mem_write(buf,payload)
    u.mem_write(conn+0x1e,struct.pack('<H',state));u.mem_write(stack,struct.pack('<4I',stop,conn,buf,len(payload)))
    u.reg_write(UC_X86_REG_ECX,obj);u.reg_write(UC_X86_REG_ESP,stack);queued=[]
    def hook(uc,addr,size,user):
        if addr==base+0x1f70:
            sp=uc.reg_read(UC_X86_REG_ESP);ret,p,n=struct.unpack('<3I',uc.mem_read(sp,12))
            queued.append(bytes(uc.mem_read(p,n)).hex());uc.reg_write(UC_X86_REG_ESP,sp+12);uc.reg_write(UC_X86_REG_EIP,ret)
    u.hook_add(U.UC_HOOK_CODE,hook);u.emu_start(base+0x2250,stop,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==stop
    after=int.from_bytes(u.mem_read(conn+0x1e,2),'little')
    assert queued==([payload.hex()] if state==2 else [])
    assert after==(3 if state==2 and status==0 else state)
    return {'completion_hex':payload.hex(),'state_before':state,'state_after':after,'queue_hex':queued,'stub':'queue1f70'}

def main():
    image=ROOT/'evidence/loader-user32-fix/unpacked-0xc9b0000.bin';raw=image.read_bytes()
    manifest=json.loads((ROOT/'evidence/manifest.json').read_text(encoding='utf-8'))
    expected=next(x['sha256'] for x in manifest['files'] if x['path']==image.relative_to(ROOT/'evidence').as_posix())
    assert hashlib.sha256(raw).hexdigest()==expected
    cases=[run(raw,seed) for seed in (b'\0'*8,b'\xff'*8,bytes(range(8)))]
    cases += [run(raw,bytes(range(8)),n) for n in range(1,9)]
    cases += [completion(raw,status,2) for status in (0,1,255)]+[completion(raw,0,1)]
    (ROOT/'evidence/native_mode1_probe.json').write_text(json.dumps({'sha256':expected,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('15 original-x86 mode1 cases passed.')
if __name__=='__main__':main()
