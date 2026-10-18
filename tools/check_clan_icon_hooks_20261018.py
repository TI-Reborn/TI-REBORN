"""Execute actual patched hooks with explicit Windows/codec call boundaries."""
import json,struct,sys
from pathlib import Path
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/clan-icons-20261018'
raw=(OUT/'silver.dll').read_bytes();proof=json.loads((OUT/'native-review.json').read_text())
cases=[]
for base in (0x400000,0x17000000,0x61000000):
 pe=pefile.PE(data=raw);pe.relocate_image(base);mapped=pe.get_memory_mapped_image();delta=base-0x400000
 for stage in ('normalize','release'):
  for failure in (('none','library','export','image') if stage=='normalize' else ('none','export')):
   u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(len(mapped)+4095)&~4095);u.mem_write(base,mapped)
   stack=0x2000000;external=0x3000000;u.mem_map(stack,0x10000);u.mem_map(external,0x10000)
   put=lambda a,v:u.mem_write(a,struct.pack('<I',v&0xffffffff))
   get=lambda a:struct.unpack('<I',u.mem_read(a,4))[0]
   frame=stack+0x9000;sp=stack+0x5000;put(frame-4,external+0x1000);put(frame-0x18,0x1234)
   u.mem_write(external+0x1000,'source.png\0'.encode('utf-16le'));u.mem_write(external+0x1100,'converted.bmp\0'.encode('utf-16le'))
   calls=[];target=0x837635 if stage=='normalize' and failure=='none' else (0x83774f if stage=='normalize' else 0x8376f6)
   regs={UC_X86_REG_EAX:0x11112222,UC_X86_REG_EBX:0x33334444,UC_X86_REG_ECX:0x55556666,UC_X86_REG_EDX:0x77778888,UC_X86_REG_ESI:0x9999aaaa,UC_X86_REG_EDI:0xbbbbcccc,UC_X86_REG_EBP:frame,UC_X86_REG_ESP:sp}
   for reg,v in regs.items():u.reg_write(reg,v)
   addresses={0xb7a100:'load',0xb7a170:'getproc',int(proof['free_library_iat'],16):'free'}
   for index,(iat,kind) in enumerate(addresses.items()):put(iat+delta,external+0x2000+index*16)
   def ret(value=None,argc=0):
    p=u.reg_read(UC_X86_REG_ESP);u.reg_write(UC_X86_REG_EIP,get(p));u.reg_write(UC_X86_REG_ESP,p+4+argc*4)
    if value is not None:u.reg_write(UC_X86_REG_EAX,value)
   def hook(uc,a,size,_):
    if a==target+delta:uc.emu_stop();return
    if a==0x4092dc+delta:calls.append('destroy');ret();return
    if a==0xa0202c+delta:calls.append('error');ret();return
    if external+0x2000<=a<external+0x2030:
     name=list(addresses.values())[(a-external-0x2000)//16];calls.append(name)
     if name=='load':ret(0 if failure=='library' else 0x1234,1)
     elif name=='getproc':ret(0 if failure=='export' else external+0x2100,2)
     else:ret(1,1)
    elif a==external+0x2100:
     calls.append(stage)
     if stage=='normalize':assert get(uc.reg_read(UC_X86_REG_ESP)+4)==external+0x1000;ret(0 if failure=='image' else external+0x1100,1)
     else:ret(0)
   u.hook_add(UC_HOOK_CODE,hook);u.emu_start((0x83762e if stage=='normalize' else 0x8376f1)+delta,target+delta+1,count=2000)
   assert u.reg_read(UC_X86_REG_EIP)==target+delta
   for reg in (UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP):assert u.reg_read(reg)==regs[reg]
   assert u.reg_read(UC_X86_REG_ESP)==sp-(4 if stage=='normalize' and failure=='none' else 0)
   if stage=='normalize' and failure=='none':assert u.reg_read(UC_X86_REG_ECX)==external+0x1100 and u.reg_read(UC_X86_REG_EDX)&255==1
   if stage=='release':assert calls[0]=='destroy' and calls[-1]=='free'
   cases.append(dict(base=hex(base),stage=stage,failure=failure,calls=calls))
report=dict(passed=True,cases=cases,method='Actual x86 hooks under relocation; Win32, conversion and original stream destructor are explicit stubs. Real native codec is tested separately.')
(OUT/'native-hook-execution.json').write_text(json.dumps(report,indent=2));print(json.dumps(dict(passed=True,cases=len(cases))))
