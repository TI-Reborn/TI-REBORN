"""Execute the conditional caption adapter at preferred and relocated bases."""
import json,sys
from pathlib import Path
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/training-base-20261018/client'
def main():
    data=(OUT/'silver.dll').read_bytes();p=pefile.PE(data=data)
    report=json.loads((OUT/'native-review.json').read_text());cases=[]
    for base in (0x400000,0x18000000,0x31000000):
        for training in (False,True):
            u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(p.OPTIONAL_HEADER.SizeOfImage+4095)&~4095)
            u.mem_write(base,p.get_memory_mapped_image())
            u.mem_map(0x50000000,0x10000);sp=0x50008000
            u.reg_write(UC_X86_REG_ESP,sp);u.reg_write(UC_X86_REG_EAX,0x12345678)
            u.reg_write(UC_X86_REG_EDX,0x98765432);u.reg_write(UC_X86_REG_ECX,0x21436587)
            hit=[]
            def hook(u,pc,size,_):
                if pc==base+0x822234-0x400000:
                    u.reg_write(UC_X86_REG_EAX,int(training))
                    # Native register-call callee may clobber these.
                    u.reg_write(UC_X86_REG_EDX,0xdeadbeef);u.reg_write(UC_X86_REG_ECX,0xdeadbeef)
                    stack=u.reg_read(UC_X86_REG_ESP)
                    u.reg_write(UC_X86_REG_EIP,int.from_bytes(u.mem_read(stack,4),'little'))
                    u.reg_write(UC_X86_REG_ESP,stack+4)
                elif pc==base+0x6675e0-0x400000:
                    assert u.reg_read(UC_X86_REG_EDX)==0x98765432 and u.reg_read(UC_X86_REG_ECX)==0x21436587
                    assert u.reg_read(UC_X86_REG_ESP)==sp
                    key=u.reg_read(UC_X86_REG_EAX)
                    assert key==(base+report['new_key_va']-0x400000 if training else 0x12345678)
                    if training:assert bytes(u.mem_read(key,10)).decode('utf-16-le')=='tb02t'
                    hit.append(True);u.emu_stop()
            u.hook_add(UC_HOOK_CODE,hook)
            u.emu_start(base+report['helper_va']-0x400000,base+p.OPTIONAL_HEADER.SizeOfImage,count=100)
            assert hit;cases.append(dict(base=hex(base),training=training,passed=True))
    guard_cases=[]
    for base in (0x400000,0x18000000,0x31000000):
      for training in (False,True):
       for clan in (False,True):
        for adapter in (False,):
            u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(p.OPTIONAL_HEADER.SizeOfImage+4095)&~4095);u.mem_write(base,p.get_memory_mapped_image())
            u.mem_map(0x50000000,0x10000);sp=0x50008000;stop=base+0x800
            character=base+0xa00;u.mem_write(character+0x280,int(clan).to_bytes(4,'little'))
            u.mem_write(sp,stop.to_bytes(4,'little'));u.reg_write(UC_X86_REG_ESP,sp)
            u.reg_write(UC_X86_REG_EAX,character);u.reg_write(UC_X86_REG_EDX,0x98765432);u.reg_write(UC_X86_REG_ECX,0x21436587);u.reg_write(UC_X86_REG_EFLAGS,0x247)
            def detect(u,pc,size,_):
                if pc==base+0x822234-0x400000:
                    u.reg_write(UC_X86_REG_EAX,int(training));u.reg_write(UC_X86_REG_EDX,0xdeadbeef);u.reg_write(UC_X86_REG_ECX,0xdeadbeef)
                    stack=u.reg_read(UC_X86_REG_ESP);u.reg_write(UC_X86_REG_EIP,int.from_bytes(u.mem_read(stack,4),'little'));u.reg_write(UC_X86_REG_ESP,stack+4)
            u.hook_add(UC_HOOK_CODE,detect)
            u.emu_start(base+report['guard_va']-0x400000,stop,count=100)
            assert u.reg_read(UC_X86_REG_EIP)==stop and u.reg_read(UC_X86_REG_ESP)==sp+4
            assert bool(u.reg_read(UC_X86_REG_EFLAGS)&0x40)==(not (training or clan))
            assert u.reg_read(UC_X86_REG_ECX)==0x21436587
            assert u.reg_read(UC_X86_REG_EAX)==character and u.reg_read(UC_X86_REG_EDX)==0x98765432
            assert bytes(u.mem_read(character+0x280,4))==int(clan).to_bytes(4,'little')
            guard_cases.append(dict(base=hex(base),training=training,clan=clan,passed=True))
    ready_cases=[]
    for base in (0x400000,0x18000000,0x31000000):
      for training in (False,True):
       for ready in (0,1):
        u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,(p.OPTIONAL_HEADER.SizeOfImage+4095)&~4095);u.mem_write(base,p.get_memory_mapped_image())
        u.mem_map(0x50000000,0x10000);sp=0x50008000;stop=base+0x800;out=base+0xa00
        u.mem_write(sp,stop.to_bytes(4,'little'));u.reg_write(UC_X86_REG_ESP,sp);u.reg_write(UC_X86_REG_EAX,out);u.reg_write(UC_X86_REG_EDX,ready);u.reg_write(UC_X86_REG_ECX,0x21436587);u.reg_write(UC_X86_REG_EFLAGS,0x247)
        def is_training(u,pc,size,_):
            if pc==base+0x822234-0x400000:
                u.reg_write(UC_X86_REG_EAX,int(training));u.reg_write(UC_X86_REG_EDX,0xdeadbeef);u.reg_write(UC_X86_REG_ECX,0xdeadbeef)
                stack=u.reg_read(UC_X86_REG_ESP);u.reg_write(UC_X86_REG_EIP,int.from_bytes(u.mem_read(stack,4),'little'));u.reg_write(UC_X86_REG_ESP,stack+4)
        u.hook_add(UC_HOOK_CODE,is_training);u.emu_start(base+report['ready_va']-0x400000,stop,count=100)
        assert bytes(u.mem_read(out,2))==bytes((ready^int(training),1))
        assert u.reg_read(UC_X86_REG_EFLAGS)==0x247 and u.reg_read(UC_X86_REG_ECX)==0x21436587 and u.reg_read(UC_X86_REG_EAX)==out and u.reg_read(UC_X86_REG_ESP)==sp+4
        ready_cases.append(dict(base=hex(base),training=training,previous_ready=ready,passed=True))
    # Every byte in the previous file must be covered by the reviewed hooks,
    # relocation removals or three section/image size fields.
    original=(OUT/'silver-before.dll').read_bytes();before=pefile.PE(data=original);allowed=set()
    for row in report['changes']:allowed.update(range(row['offset'],row['offset']+len(bytes.fromhex(row['before']))))
    for row in report['relocation_changes']:allowed.update(range(row['offset'],row['offset']+2))
    for obj,field in [(before.sections[-1],'Misc_VirtualSize'),(before.sections[-1],'SizeOfRawData'),(before.OPTIONAL_HEADER,'SizeOfImage')]:
        offset=obj.get_field_absolute_offset(field);allowed.update(range(offset,offset+4))
    assert all(i in allowed for i,(a,b) in enumerate(zip(original,data)) if a!=b)
    result=dict(passed=True,cases=cases,guard_cases=guard_cases,ready_cases=ready_cases,all_prefix_changes_reviewed=True,graphical_validation=False)
    (OUT/'native-execution.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
