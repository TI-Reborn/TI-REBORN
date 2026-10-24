"""Execute the exact published constructor and edit clamp with fabricated strings."""
import hashlib,json,struct,sys
from pathlib import Path
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EBX,UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EIP
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/password-recovery-20261023/client'
raw=(OUT/'previous-silver.dll').read_bytes();assert hashlib.sha256(raw).hexdigest()=='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
pe=pefile.PE(data=raw);image=pe.get_memory_mapped_image();DATA=0x2000000;STACK=0x3000000

def run(length,patched):
 u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0x400000,(len(image)+4095)&~4095);u.mem_write(0x400000,image)
 u.mem_map(DATA,0x10000);u.mem_map(STACK,0x10000);u.reg_write(UC_X86_REG_EBX,DATA);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
 if patched:u.mem_write(0x87edbe,b'\x40')
 u.emu_start(0x87edb8,0x87edbf,count=1);cap=u.mem_read(DATA+0x280,1)[0];assert cap==(64 if patched else 16)
 string=DATA+0x1000;u.mem_write(string-4,struct.pack('<I',length));u.mem_write(string,('A'*length).encode('utf-16le'));u.mem_write(DATA+0x58,struct.pack('<I',string))
 calls=[]
 def hook(uc,address,size,user):
  if address==0xa46cf2:uc.emu_stop()
  elif address in (0x40c3d4,0xa45c0c):
   if address==0x40c3d4:
    # Execute the real branch and Delphi call convention. The allocation/
    # delete helper is a controlled fake: only its target length is modeled.
    assert uc.reg_read(UC_X86_REG_EAX)==DATA+0x58
    removed=uc.reg_read(UC_X86_REG_ECX);calls.append(removed)
    uc.mem_write(string-4,struct.pack('<I',length-removed))
   sp=uc.reg_read(UC_X86_REG_ESP);ret=struct.unpack('<I',uc.mem_read(sp,4))[0];uc.reg_write(UC_X86_REG_ESP,sp+4);uc.reg_write(UC_X86_REG_EIP,ret)
 u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0xa46cbb,0xa46cf2,count=1000)
 result=struct.unpack('<I',u.mem_read(string-4,4))[0];assert result==min(length,cap)
 return {'input_characters':length,'cap':cap,'result_characters':result,'delete_helper_stubbed':bool(calls)}

cases=[run(n,p) for p in (False,True) for n in (12,16,17,32,64,65)]
report={'passed':True,'cases':cases,'method':'Original x86 constructor instruction and edit-clamp branch under Unicorn; fabricated strings and stubbed delete/allocation/UI helper; no real credentials','real_graphical_client':False}
(OUT/'native-field.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'cases':len(cases)}))
