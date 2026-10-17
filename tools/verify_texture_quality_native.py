"""Execute guarded sampler installer and original native TI setters in x86.

Only the GPU COM endpoint and Windows API calls are ABI fixtures. The original
sampler methods, cache writes, device-ready gates and runtime entry wrappers
execute. This validates machine code and failure handling, not game imagery.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from functools import lru_cache

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
                              UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                              UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP,
                              UC_X86_REG_EFLAGS)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_texture_quality as q

DATA, STACK, API = 0x30000000, 0x31000000, 0x32000000
END, VP, MODULE, PROC, PROCESS, FLUSH, GPU = (API+off for off in (0,0x100,0x200,0x300,0x400,0x500,0x600))
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
        UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
VALUES = (0x11111111,0x22222222,0x33333333,0x44444444,0x55555555,0x66666666,0x77777777)


def put(u, at, value): u.mem_write(at, struct.pack('<I',value&0xffffffff))
def get(u, at): return struct.unpack('<I',u.mem_read(at,4))[0]


@lru_cache(maxsize=2)
def silver_image(candidate, base):
    pe=pefile.PE(data=candidate)
    pe.relocate_image(base)
    result=pe.get_memory_mapped_image()
    pe.close()
    return result


@lru_cache(maxsize=1)
def ti_image(ti):
    pe=pefile.PE(data=ti)
    result=pe.get_memory_mapped_image()
    pe.close()
    return result


class Fixture:
    def __init__(self, candidate, ti, base, *, denied=False, restore_fail=False,
                 flush_fail=False, missing_flush=False, damaged=False):
        self.base, self.u = base, Uc(UC_ARCH_X86,UC_MODE_32)
        mapped = silver_image(candidate,base)
        self.u.mem_map(base,(len(mapped)+0xfff)&~0xfff); self.u.mem_write(base,mapped)
        ti_mapped=ti_image(ti)
        self.u.mem_map(q.IMAGE_BASE,0x400000);self.u.mem_write(q.IMAGE_BASE,ti_mapped)
        self.u.mem_map(DATA,0x10000); self.u.mem_map(STACK,0x10000);self.u.mem_map(API,0x1000)
        self.u.mem_write(API,b'\xc3'*0x1000)
        for rva,value in ((q.VP_RVA,VP),(q.GET_MODULE_RVA,MODULE),(q.GET_PROC_RVA,PROC),(q.PROCESS_RVA,PROCESS)):
            put(self.u,base+rva,value)
        if damaged:self.u.mem_write(q.SETTERS[1][0]+0x31,b'\xcc')
        self.original_page=bytes(self.u.mem_read(q.PAGE,q.PAGE_SIZE))
        self.protection=0x20
        self.u.mem_protect(q.PAGE,q.PAGE_SIZE,UC_PROT_READ|UC_PROT_EXEC)
        self.denied,self.restore_fail,self.flush_fail,self.missing_flush=denied,restore_fail,flush_fail,missing_flush
        self.vps,self.flushes,self.gpu,self.previous=[],[],[],0
        self.u.hook_add(UC_HOOK_CODE,self.hook)
        self.sampler,self.owner,self.renderer,self.device,self.vtable=(DATA+p for p in (0x1000,0x2000,0x3000,0x4000,0x5000))
        put(self.u,self.sampler+4,self.owner);put(self.u,self.owner+4,self.renderer)
        self.u.mem_write(self.renderer+0x244,b'\x01');put(self.u,self.renderer+0x44,self.device)
        put(self.u,self.device,self.vtable);put(self.u,self.vtable+0x114,GPU)

    def state(self,offset=0):return get(self.u,self.base+q.STATE+offset)

    def ret(self,arguments=0,result=None):
        if result is not None:self.u.reg_write(UC_X86_REG_EAX,result)
        sp=self.u.reg_read(UC_X86_REG_ESP);destination=get(self.u,sp)
        self.u.reg_write(UC_X86_REG_ESP,sp+4+arguments)
        self.u.reg_write(UC_X86_REG_EIP,destination)

    def hook(self,u,address,size,extra):
        sp=u.reg_read(UC_X86_REG_ESP)
        if address==END:u.emu_stop()
        elif address==MODULE:self.ret(4,0x70000000)
        elif address==PROC:self.ret(8,0 if self.missing_flush else FLUSH)
        elif address==PROCESS:self.ret(0,0xffffffff)
        elif address==VP:
            page,length,protection,output=[get(u,sp+i*4) for i in range(1,5)]
            assert (page,length)==(q.PAGE,q.PAGE_SIZE)
            failed=(self.denied and protection==0x40) or (self.restore_fail and protection==0x20 and not any(v['failed'] for v in self.vps))
            self.vps.append(dict(protection=protection,failed=failed))
            if failed:self.ret(16,0)
            else:
                put(u,output,self.protection);self.protection=protection
                u.mem_protect(page,length,7 if protection==0x40 else UC_PROT_READ|UC_PROT_EXEC)
                self.ret(16,1)
        elif address==FLUSH:
            args=[get(u,sp+i*4) for i in range(1,4)]
            assert args==[0xffffffff,q.PAGE,q.PAGE_SIZE]
            self.flushes.append(args);self.ret(12,0 if self.flush_fail and len(self.flushes)==1 else 1)
        elif address==GPU:
            args=[get(u,sp+i*4) for i in range(1,5)]
            assert args[0]==self.device
            self.gpu.append(args);self.ret(16,0)
        elif address==self.base+q.PREVIOUS_STARTUP-q.IMAGE_BASE:
            self.previous+=1;self.ret()

    def run(self,address,*,self_register=None,stage=0,value=0):
        for register,default in zip(REGS,VALUES):self.u.reg_write(register,default)
        self.u.reg_write(UC_X86_REG_EFLAGS,0x246)
        self.u.reg_write(UC_X86_REG_ESP,STACK+0xc000);put(self.u,STACK+0xc000,END)
        if self_register is not None:
            self.u.reg_write(UC_X86_REG_EAX,self_register);self.u.reg_write(UC_X86_REG_EDX,stage)
            self.u.reg_write(UC_X86_REG_ECX,value)
        self.u.emu_start(address,END,count=100000)
        assert self.u.reg_read(UC_X86_REG_EIP)==END
        assert self.u.reg_read(UC_X86_REG_ESP)==STACK+0xc004


def verify(candidate,ti):
    cases=[]
    for base in (0x10000000,0x17000000):
        f=Fixture(candidate,ti,base)
        f.run(base+q.STARTUP-q.IMAGE_BASE)
        assert f.previous==1 and f.state()==1 and f.state(4)==0
        assert [f.u.reg_read(r) for r in REGS]==list(VALUES)
        assert f.u.reg_read(UC_X86_REG_EFLAGS)==0x246 and f.protection==0x20
        after=bytes(f.u.mem_read(q.PAGE,q.PAGE_SIZE))
        changed=[i for i,(before,new) in enumerate(zip(f.original_page,after)) if before!=new]
        allowed={at-q.PAGE+i for at,_,_ in q.SETTERS for i in range(6)}
        assert set(changed)<=allowed and len(f.vps)==2 and len(f.flushes)==1
        for at,wrapper,_ in q.SETTERS:
            raw=bytes(f.u.mem_read(at,6))
            assert raw[0]==0xe9 and raw[5]==0x90
            assert at+5+struct.unpack_from('<i',raw,1)[0]==base+wrapper-q.IMAGE_BASE
        f.run(base+q.INSTALL-q.IMAGE_BASE)
        assert len(f.vps)==2 and len(f.flushes)==1
        cases.append(dict(base=hex(base),check='install_and_idempotence',changed_ti_bytes=len(changed),exact_declared_ranges=True,protection_restored=True,previous_startup_chained=True))
        for index,(address,_,_) in enumerate(q.SETTERS):
            sampler_offset=(0x68,0x88,0xa8)[index];state_type=5+index
            for stage in (0,1,7):
                for value in (0,1,2,3,4,0xffffffff):
                    expected=2 if (value==1 or (index<2 and value==0)) else value
                    f.run(address,self_register=f.sampler,stage=stage,value=value)
                    assert get(f.u,f.sampler+sampler_offset+stage*4)==expected
                    assert f.gpu[-1]==[f.device,stage,state_type,expected]
                    assert [f.u.reg_read(r) for r in (UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP)]==[VALUES[i] for i in (1,4,5,6)]
                    cases.append(dict(base=hex(base),check='original_setter_cache_and_gpu',sampler_state=state_type,stage=stage,input=value,output=expected))
                f.u.mem_write(f.renderer+0x244,b'\0')
                count=len(f.gpu);f.run(address,self_register=f.sampler,stage=stage,value=1)
                assert len(f.gpu)==count and get(f.u,f.sampler+sampler_offset+stage*4)==2
                f.u.mem_write(f.renderer+0x244,b'\1')
                cases.append(dict(base=hex(base),check='device_reset_not_ready_gate',sampler_state=state_type,stage=stage,cache_retained=True,gpu_not_called=True))
        for name,settings,error in (('unknown_method',dict(damaged=True),1),('missing_flush_api',dict(missing_flush=True),1),('write_protection_denied',dict(denied=True),2),('restore_failure_rollback',dict(restore_fail=True),3),('flush_failure_rollback',dict(flush_fail=True),4)):
            failed=Fixture(candidate,ti,base,**settings);failed.run(base+q.STARTUP-q.IMAGE_BASE)
            assert failed.state()==0xffffffff and failed.state(4)==error and failed.previous==1
            assert bytes(failed.u.mem_read(q.PAGE,q.PAGE_SIZE))==failed.original_page and failed.protection==0x20
            assert [failed.u.reg_read(r) for r in REGS]==list(VALUES)
            cases.append(dict(base=hex(base),check=name,error=error,all_original_ti_bytes_restored=True,protection_restored=True,startup_continues=True))
    return dict(passed=True,candidate_sha256=q.sha(candidate),ti_sha256=q.sha(ti),cases=len(cases),details=cases,
                proof_kind=__doc__,original_engine_sampler_methods_executed=True,gpu_and_windows_apis_stubbed=True,
                image_resource_bytes_changed=0,uv_alpha_and_dimensions_unchanged=True,combat_effects_unchanged=True,
                global_atlas_mips_not_generated=True,graphical_game_client=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--ti',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=verify(a.candidate.read_bytes(),a.ti.read_bytes())
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','candidate_sha256','cases','graphical_game_client')}))


if __name__=='__main__':main()
