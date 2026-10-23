"""Execute direct-start rejection and launcher release, inspect actual PE icons."""
import hashlib,json,struct
from pathlib import Path
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ESP,UC_X86_REG_EIP
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'work/launcher-required-20261020';OUT=ROOT/'reports/launcher-required-20261020'

def main():
    raw=(WORK/'ti.exe').read_bytes();plan=json.loads((OUT/'native-gate-plan.json').read_text());assert hashlib.sha256(raw).hexdigest()==plan['after_sha256']
    pe=pefile.PE(data=raw);ico=(ROOT/'launcher/Assets/tio-launcher.ico').read_bytes()
    resources={}
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        for name in t.directory.entries:
            for lang in name.directory.entries:
                entry=lang.data.struct
                resources[t.id,str(name.name) if name.name else name.id,lang.id]=pe.get_data(entry.OffsetToData,entry.Size)
    for index in range(struct.unpack_from('<H',ico,4)[0]):
        size,at=struct.unpack_from('<II',ico,6+16*index+8)
        assert resources[3,5000+index,1049]==ico[at:at+size]
    calls=[]
    for base in (0x400000,0x10000000):
        for released in (False,True):
            u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(pe.OPTIONAL_HEADER.SizeOfImage+4095)//4096*4096)
            image=pe.get_memory_mapped_image();u.mem_write(base,image)
            stack=0x20000000;u.mem_map(stack,0x10000);u.reg_write(UC_X86_REG_ESP,stack+0x8000)
            stub=0x30000000;u.mem_map(stub,4096)
            u.mem_write(base+0x388f54,struct.pack('<I',stub));u.mem_write(base+0x388ddc,struct.pack('<I',stub+32))
            observed=[]
            def hook(uc,address,size,_):
                if address==base+plan['original_entry']:observed.append('game');uc.emu_stop()
                elif address==stub:
                    esp=uc.reg_read(UC_X86_REG_ESP);ptr=struct.unpack('<I',uc.mem_read(esp+8,4))[0]
                    text=bytes(uc.mem_read(ptr,190)).decode('utf-16le').split('\0')[0]
                    assert 'TIO Launcher' in text;observed.append('message')
                    ret=struct.unpack('<I',uc.mem_read(esp,4))[0];uc.reg_write(UC_X86_REG_ESP,esp+20);uc.reg_write(UC_X86_REG_EIP,ret)
                elif address==stub+32:
                    observed.append('exit');uc.emu_stop()
            u.hook_add(UC_HOOK_CODE,hook)
            entry=base+plan['guard_rva']
            if released:u.mem_write(entry,b'\xe9'+struct.pack('<i',plan['original_entry']-plan['guard_rva']-5))
            u.emu_start(entry,stub+100,count=500)
            assert observed==(['game'] if released else ['message','exit']),observed
            calls.append(dict(image_base=hex(base),released=released,events=observed))
    result=dict(passed=True,icon_images_match_launcher=9,native_cases=calls,sha256=plan['after_sha256'],original_code_preserved=True)
    (OUT/'native-gate-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
