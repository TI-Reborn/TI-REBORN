"""Execute both real repair-kit predicates and warehouse filter paths.

Uses the exact published/candidate DLLs at two image bases. Later category,
mark and service predicates receive explicit fixture results; no UI rendering
or actual game windows are claimed. No writes outside local report files.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy.client_repair_warehouse import review
REPORT=ROOT/'reports/repair-warehouse-20261017'
DATA=0x2000000
STACK=0x3000000
STOP=STACK+0x100


def put(u,a,n):u.mem_write(a,struct.pack('<I',n))
def get(u,a):return struct.unpack('<I',u.mem_read(a,4))[0]
def ret(u,value):
    sp=u.reg_read(UC_X86_REG_ESP);u.reg_write(UC_X86_REG_EAX,value)
    u.reg_write(UC_X86_REG_EIP,get(u,sp));u.reg_write(UC_X86_REG_ESP,sp+4)


def image(raw,base):
    pe=pefile.PE(data=raw)
    try:
        if base!=pe.OPTIONAL_HEADER.ImageBase:pe.relocate_image(base)
        mapped=pe.get_memory_mapped_image()
        u=Uc(UC_ARCH_X86,UC_MODE_32)
        u.mem_map(base,(len(mapped)+0xfff)&~0xfff);u.mem_write(base,mapped)
        u.mem_map(DATA,0x10000);u.mem_map(STACK,0x10000)
        return u
    finally:pe.close()


def cases(raw,patched,base):
    u=image(raw,base);delta=base-0x400000
    frame=DATA+0x8000;item=frame-0x2a0;panel=DATA+0x1000
    globals_fixture=DATA+0x2000
    put(u,frame-4,panel)
    for index,a in enumerate((0xac5a94,0xac5890,0xac5e68)):
        put(u,a+delta,globals_fixture+index*16)
    state={};results=[]
    def hook(uc,a,n,_):
        original=a-delta
        if original==0xa7b8c0:state['real_repair_predicate_calls']+=1
        # Preserve native repair-kit and upgrade-kit predicates. Only unrelated
        # predicates use explicit fixture outputs; no renderer is emulated.
        elif original in (0xa7b3f0,0xa7b41c,0xa7b524,0xa8b194,0x99f5d8):ret(uc,0)
        elif original==0xa7c058:ret(uc,state['later_filter'])
    u.hook_add(UC_HOOK_CODE,hook)
    for start,end in ((0x9159bc,0x915a84),(0x917168,0x91726c)):
        for template in (0,16,17,18,19,20,30,301,65535):
            for accepted in (0,1):
                for kind in (0,1,2):
                    for later in (0,1):
                        state.update(later_filter=later,real_repair_predicate_calls=0)
                        u.mem_write(panel+0x2d8,bytes((kind,)))
                        put(u,item+8,template);put(u,STACK+0x8000,STOP)
                        for reg,val in ((UC_X86_REG_EAX,item),(UC_X86_REG_EDI,item),(UC_X86_REG_ESI,panel),
                                        (UC_X86_REG_EBP,frame),(UC_X86_REG_EBX,accepted),(UC_X86_REG_ESP,STACK+0x8000)):
                            u.reg_write(reg,val)
                        u.emu_start(start+delta,end+delta,count=200)
                        assert u.reg_read(UC_X86_REG_EIP)==end+delta
                        expected=0 if not patched and template in (17,18,19) else accepted
                        if kind==0 and not later:expected=0
                        actual=u.reg_read(UC_X86_REG_EBX)
                        assert actual==expected,(patched,hex(start),template,accepted,kind,later,actual,expected)
                        assert state['real_repair_predicate_calls']==1
                        assert get(u,item+8)==template
                        results.append(dict(path=hex(start),template=template,kind=kind,
                                            previous_filter=accepted,later_filter=later,result=actual))
    return dict(image_base=hex(base),patched=patched,cases=len(results),results=results)


def main():
    source=(REPORT/'client/baseline/silver.dll').read_bytes()
    candidate=(REPORT/'client/candidate/silver.dll').read_bytes()
    audit=review(source,candidate)
    checks=[cases(raw,patched,base) for base in (0x400000,0x10000000)
            for patched,raw in ((False,source),(True,candidate))]
    report=dict(passed=True,cases=sum(c['cases'] for c in checks),checks=checks,review=audit,
                real_predicate='a7b8c0: template in17..19',graphical_clients=False,
                limitations=__doc__,hosted_changes=False)
    (REPORT/'native-filter-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=True,cases=report['cases'],relocated_bases=2,
                         source_reproduces_hidden_kits=True,candidate_preserves_other_filters=True,
                         graphical_clients=False)))


if __name__=='__main__':main()
