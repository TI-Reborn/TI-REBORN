"""Compare Python cipher state against original unpacked TI x86 routines."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import unicorn as U
from unicorn.x86_const import UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EIP
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.protocol.transport import InitialCipher,INITIAL_KEY

def main():
    image=ROOT/'evidence/loader-user32-fix/unpacked-0xc9b0000.bin'
    raw=image.read_bytes(); base=0xc9b0000
    manifest=json.loads((ROOT/'evidence/manifest.json').read_text())
    expected=next(x['sha256'] for x in manifest['files'] if x['path']==str(image.relative_to(ROOT/'evidence')).replace('\\','/'))
    assert hashlib.sha256(raw).hexdigest()==expected
    records=[]
    for direction in ('S2C','C2S'):
        uc=U.Uc(U.UC_ARCH_X86,U.UC_MODE_32)
        uc.mem_map(base,0x7000); uc.mem_write(base,raw)
        uc.mem_map(0x2000000,0x20000)
        obj=0x2000000; buf=obj+0x1000; stack=obj+0x18000; stop=obj+0x1f000
        uc.mem_write(obj+5,b'\1')
        keyoffset=6 if direction=='S2C' else 14
        uc.mem_write(obj+keyoffset,INITIAL_KEY)
        cipher=InitialCipher(direction)
        for data in (bytes(range(255)),b'\x00\x01\xff\x80',b'\x02',b'\xaa'*1025):
            uc.mem_write(buf,data)
            uc.mem_write(stack,struct.pack('<4I',stop,obj,buf,len(data)))
            uc.reg_write(UC_X86_REG_ECX,obj)
            uc.reg_write(UC_X86_REG_ESP,stack)
            uc.emu_start(base+(0x2710 if direction=='S2C' else 0x2680),stop,count=100000)
            assert uc.reg_read(UC_X86_REG_EIP)==stop
            result=bytes(uc.mem_read(buf,len(data)))
            expected=cipher.transform(data,encrypt=direction=='C2S')
            assert result==expected
            assert bytes(uc.mem_read(obj+keyoffset,8))==bytes(cipher.key)
            records.append({'direction':direction,'length':len(data),'key_after':cipher.key.hex(),'output_sha256':hashlib.sha256(result).hexdigest()})
    (ROOT/'evidence/native_transport_probe.json').write_text(json.dumps({'source':str(image),'sha256':hashlib.sha256(raw).hexdigest(),'method':'original x86 0x2680/0x2710; no function stubs; 4 sequential calls per direction','cases':records},indent=2)+'\n',encoding='utf-8')
    print('8 original-x86 cipher/state cases passed.')

if __name__=='__main__':main()
