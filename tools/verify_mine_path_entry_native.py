"""Execute the exact scene-entry candidate, including TI's original reset.

This is isolated x86 execution and bounded file/PE review, not a live-client
claim. It never contacts or writes hosting and never touches installed files.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
from functools import lru_cache

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.x86_const import *

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_mine_path_entry as entry
from tools.publish_battle_ui_hd_remote import native_preserved, native_structure_preserved

BASELINE=ROOT/'reports/mine-path-scale-20261010/baseline'
CANDIDATE=ROOT/'reports/mine-path-entry-20261010/client/silver.dll'
OUT=ROOT/'reports/mine-path-entry-20261010/audit/native-wrapper-proof.json'
TI_SHA='e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
STACK=0x30000000
DATA=0x31000000
INITIAL_SP=STACK+0xf000
REGISTERS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,
           'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,'edi':UC_X86_REG_EDI,
           'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}


def put(u,a,v):u.mem_write(a,struct.pack('<I',v))
def get(u,a):return struct.unpack('<I',u.mem_read(a,4))[0]


@lru_cache(maxsize=6)
def mapped(raw,base):
    p=pefile.PE(data=raw)
    try:
        if base!=p.OPTIONAL_HEADER.ImageBase:p.relocate_image(base)
        return (p.OPTIONAL_HEADER.SizeOfImage+0xfff)&~0xfff,p.get_memory_mapped_image()
    finally:p.close()


def image(u,raw,base):
    size,data=mapped(raw,base)
    u.mem_map(base,size);u.mem_write(base,data)


def execute(silver,ti,base,map_state,flags,patched):
    u=Uc(UC_ARCH_X86,UC_MODE_32)
    image(u,ti,entry.IMAGE_BASE);image(u,silver,base)
    u.mem_map(STACK,0x10000);u.mem_map(DATA,0x10000)
    delta=base-entry.IMAGE_BASE
    pointer=DATA+0x100
    matrix=DATA+0x1000
    canary=bytes((i*37+11)&255 for i in range(256))
    u.mem_write(matrix,canary)
    u.mem_write(matrix+0x14,b'\1')
    canary=bytes(u.mem_read(matrix,256))
    if map_state=='valid':put(u,entry.HOST_MAP_POINTER,pointer);put(u,pointer,matrix)
    elif map_state=='null_outer':put(u,entry.HOST_MAP_POINTER,0)
    elif map_state=='null_map':put(u,entry.HOST_MAP_POINTER,pointer);put(u,pointer,0)
    else:raise ValueError(map_state)
    # Physical mouse/camera and the matrix actor ID remain untouched. Existing
    # cached path/target flags are deliberately dirty to prove native reset.
    u.mem_write(0x76d9dc,b'\1');put(u,0x78574c,42);put(u,0x785750,43)
    u.mem_write(entry.ACTIVE_ROUTE-8,b'\xa5'*(0x190+0x4c4+8))
    put(u,entry.ROUTE_COUNT-8,0x12345678);put(u,entry.ROUTE_COUNT,7)
    u.mem_write(0x76d9dd,b'\xab\xcd\xef')
    put(u,entry.ROUTE_COUNT+4,0x87654321)
    put(u,0x785754,0xaabbccdd)
    assert get(u,0x76e400)==entry.ACTIVE_ROUTE
    route_before=bytes(u.mem_read(entry.ACTIVE_ROUTE-8,0x190+0x4c4+8))
    for a,v in [(0x787150,1337),(0x787154,777),(0x787070,12),(0x787074,34)]:put(u,a,v)
    host_before={a:bytes(u.mem_read(a,n)) for a,n in [(0x76e5f4,4),(0x785750,4),
                     (0x787150,8),(0x787070,8),(entry.ROUTE_COUNT-8,4),(0x76d9dd,3),
                     (entry.ROUTE_COUNT+4,4),(0x785754,4)]}
    initial={'eax':0x11aabbcc,'ebx':0x22334455,'ecx':0x33445566,'edx':0x44556677,
             'esi':0x55667788,'edi':0x66778899,'ebp':0x778899aa,'esp':INITIAL_SP,
             'eflags':flags}
    for name,value in initial.items():u.reg_write(REGISTERS[name],value)
    # EFLAGS bit1 is architecturally set by Unicorn, so compare the captured
    # native state to the original-prologue control run, not a guessed mask.
    initial['eflags']=u.reg_read(UC_X86_REG_EFLAGS)
    # Occupied x87 registers and vector canaries prove that the integer-only
    # clear preserves extended register state as well as GPR/DF/EFLAGS.
    u.reg_write(UC_X86_REG_FPCW,0x37f);u.reg_write(UC_X86_REG_FPSW,0x1800)
    for i in range(8):
        u.reg_write(UC_X86_REG_FP0+i,(0x8000000000000000+i,0x3fff+i))
        u.reg_write(UC_X86_REG_XMM0+i,(1<<120)+i*1234567)
    u.reg_write(UC_X86_REG_FPTAG,0)
    extended=[UC_X86_REG_FPCW,UC_X86_REG_FPSW,UC_X86_REG_FPTAG,
              *range(UC_X86_REG_FP0,UC_X86_REG_FP7+1),
              *range(UC_X86_REG_XMM0,UC_X86_REG_XMM7+1)]
    extended_before=[u.reg_read(reg) for reg in extended]
    put(u,INITIAL_SP,0x12345678)
    calls=[];writes=[];stopped=[]
    def trace_code(u,a,n,_):
        if a==entry.HOST_RESET:calls.append(a)
        if a==entry.RESUME+delta:stopped.append(a);u.emu_stop()
    def trace_write(u,access,a,n,value,_):writes.append((a,n,value))
    u.hook_add(UC_HOOK_CODE,trace_code);u.hook_add(UC_HOOK_MEM_WRITE,trace_write)
    u.emu_start(entry.HOOK+delta,entry.RESUME+delta,count=1000)
    # emu_start stops at the end address before invoking its code hook.
    assert u.reg_read(UC_X86_REG_EIP)==entry.RESUME+delta
    after={name:u.reg_read(register) for name,register in REGISTERS.items()}
    expected=dict(initial,ecx=0x19,ebp=INITIAL_SP-4,esp=INITIAL_SP-4)
    assert after==expected,(after,expected)
    assert get(u,INITIAL_SP-4)==initial['ebp']
    assert get(u,INITIAL_SP)==0x12345678
    actual_matrix=bytes(u.mem_read(matrix,256))
    expected_matrix=bytearray(canary)
    if patched and map_state=='valid':expected_matrix[0x14]=0
    assert actual_matrix==bytes(expected_matrix)
    assert all(bytes(u.mem_read(a,len(value)))==value for a,value in host_before.items())
    assert [u.reg_read(reg) for reg in extended]==extended_before
    if patched:
        assert calls==[entry.HOST_RESET]
        assert u.mem_read(0x76d9dc,1)==b'\0' and get(u,0x78574c)==0xffffffff
        assert bytes(u.mem_read(entry.ACTIVE_ROUTE,0x190))==bytes(0x190)
        assert bytes(u.mem_read(entry.FULL_ROUTE,0x4c4))==bytes(0x4c4)
        assert bytes(u.mem_read(entry.ACTIVE_ROUTE-8,8))==route_before[:8]
        assert get(u,entry.ROUTE_COUNT)==0
        allowed=[(STACK,STACK+0x10000),(0x76d9dc,0x76d9dd),(0x78574c,0x785750),
                 (entry.ACTIVE_ROUTE,entry.FULL_ROUTE+0x4c4),
                 (entry.ROUTE_COUNT,entry.ROUTE_COUNT+4)]
        if map_state=='valid':allowed.append((matrix+0x14,matrix+0x15))
        assert all(any(lo<=a and a+n<=hi for lo,hi in allowed) for a,n,v in writes),writes
    else:
        assert calls==[] and u.mem_read(0x76d9dc,1)==b'\1' and get(u,0x78574c)==42
        assert all(STACK<=a and a+n<=STACK+0x10000 for a,n,v in writes)
        assert bytes(u.mem_read(entry.ACTIVE_ROUTE-8,len(route_before)))==route_before
        assert get(u,entry.ROUTE_COUNT)==7
    return {'base':hex(base),'map':map_state,'eflags':hex(initial['eflags']),
            'exact_original_prologue_replayed':True,'registers_and_eflags_match_original':True,
            'native_reset_calls':len(calls),'map_canary_except_valid_flag_preserved':True,
            'physical_mouse_camera_and_actor_id_preserved':True,
            'x87_and_xmm_state_preserved':True,'route_arrays_zeroed_before_next_preview':patched,
            'surrounding_array_and_count_canaries_preserved':True,
            'writes_only_reviewed_native_state_and_private_stack':True,'register_state':after}


def refused(action):
    try:action()
    except (ValueError,pefile.PEFormatError):return
    raise AssertionError('Expected guarded refusal')


def main():
    source=(BASELINE/'silver.dll').read_bytes();ti=(BASELINE/'ti.exe').read_bytes()
    candidate=CANDIDATE.read_bytes()
    assert entry.sha(source)==entry.BASE_SHA and entry.sha(ti)==TI_SHA
    assert entry.patch(source)==candidate
    review=entry.review(source,candidate)
    structure=native_preserved(source,candidate,review)
    source_pe=pefile.PE(data=source);candidate_pe=pefile.PE(data=candidate)
    try:
        assert len(candidate_pe.sections)==len(source_pe.sections)==13
        assert candidate_pe.OPTIONAL_HEADER.CheckSum==source_pe.OPTIONAL_HEADER.CheckSum==0
        assert candidate_pe.OPTIONAL_HEADER.SizeOfImage==0x85b000
        assert candidate_pe.sections[-1].Misc_VirtualSize==0x37200
        assert candidate_pe.sections[-1].SizeOfRawData==0x37200
        assert candidate_pe.get_offset_from_rva(entry.APPEND_RVA)==len(source)
        assert candidate_pe.get_data(entry.APPEND_RVA,entry.APPEND_SIZE)==entry.payload()
        assert [(x.name,x.address) for x in source_pe.DIRECTORY_ENTRY_EXPORT.symbols]==[(x.name,x.address) for x in candidate_pe.DIRECTORY_ENTRY_EXPORT.symbols]
        # Refusal tests exercise strict source identity and the independently
        # reviewed structural validator, including previously found PE gaps.
        refusals=[]
        wrong=bytearray(source);wrong[0x1000]^=1
        refused(lambda:entry.patch(bytes(wrong)));refusals.append('modified source identity')
        refused(lambda:entry.patch(source+b'\0'*512));refusals.append('different source size')
        wrong=bytearray(candidate);wrong[0x1000]^=1
        refused(lambda:entry.review(source,bytes(wrong)));refusals.append('undeclared existing native byte')
        wrong=bytearray(candidate);wrong[-1]^=1
        refused(lambda:entry.review(source,bytes(wrong)));refusals.append('modified appended wrapper')
        wrong=bytearray(candidate);struct.pack_into('<I',wrong,candidate_pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),0)
        refused(lambda:native_structure_preserved(source,bytes(wrong),entry.APPEND_SIZE));refusals.append('zero SizeOfImage')
        refused(lambda:native_structure_preserved(source,source+b'\0'*512,512));refusals.append('unmapped append/overlay')
        wrong=bytearray(candidate);struct.pack_into('<I',wrong,candidate_pe.sections[-1].get_field_absolute_offset('PointerToRawData'),0)
        refused(lambda:native_structure_preserved(source,bytes(wrong),entry.APPEND_SIZE));refusals.append('final section raw bounds')
        wrong=bytearray(candidate);struct.pack_into('<I',wrong,candidate_pe.OPTIONAL_HEADER.get_field_absolute_offset('AddressOfEntryPoint'),entry.APPEND_RVA)
        refused(lambda:native_structure_preserved(source,bytes(wrong),entry.APPEND_SIZE));refusals.append('changed original entry point')
    finally:source_pe.close();candidate_pe.close()
    cases=[]
    for base in (0x10400000,0x20400000):
        for map_state in ('valid','null_outer','null_map'):
            for flags in (0x202,0xa57,0xed7):
                control=execute(source,ti,base,map_state,flags,False)
                actual=execute(candidate,ti,base,map_state,flags,True)
                assert actual.pop('register_state')==control['register_state']
                cases.append(actual)
    report={'result':'PASS','source_sha256':entry.sha(source),'candidate_sha256':entry.sha(candidate),
            'candidate_size':len(candidate),'ti_sha256':TI_SHA,'native_review':review,
            'native_structure':structure,'cases':cases,'refusal_cases':refusals,
            'executed_original_ti_reset':hex(entry.HOST_RESET),'native_body_after_hook_preserved':True,
            'hosting_mutations':0,'installed_client_modified':False,'real_client_validated':False,
            'limitations':['Scene entry/late-collision reproduction is a separate genuine-wave native proof',
                           'Isolated native execution does not assert a live GUI result']}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: {len(cases)} exact candidate/original prologue ABI/rebase/null cases; {len(refusals)} guarded refusals')


if __name__=='__main__':main()
