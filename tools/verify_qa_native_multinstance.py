"""Bounded original startup branch probe for the two-branch own QA bypass."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verify_battle_loaded_native import exe_emulator, EXE_SHA
from verify_auth_native import STACK, put32, return_from_stub, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP
import pefile

def case(dev, mutex, other_process, sandbox, bypass=False):
    u=exe_emulator();calls=[];destination=[]
    if bypass:
        assert bytes(u.mem_read(0x759076,2))==b'\x75\x69'
        assert bytes(u.mem_read(0x75907f,2))==b'\x75\x60'
        u.mem_write(0x759076,b'\x90\x90');u.mem_write(0x75907f,b'\x90\x90')
    u.reg_write(UC_X86_REG_EBP,STACK+0x7000)
    u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
    put32(u,0x787646,0)
    def hook(uc,address,size,user):
        if address in (0x7590a0,0x7590e1):
            destination.append(address);uc.emu_stop();return
        answers={0x7498b8:dev,0x74b580:mutex,0x74b5e4:other_process,0x74b6e8:sandbox}
        if address in answers:
            if address==0x7498b8:
                pointer=uc.reg_read(UC_X86_REG_EAX)
                assert bytes(uc.mem_read(pointer,10))=='+dev\0'.encode('utf-16le')
            calls.append(hex(address));uc.reg_write(UC_X86_REG_EAX,int(answers[address]));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x759058,0,count=2000)
    expected=0x7590a0 if dev or not(sandbox or (not bypass and (mutex or other_process))) else 0x7590e1
    assert destination==[expected]
    if dev:assert calls==['0x7498b8']
    return dict(dev_argument=dev,two_branch_bypass=bypass,mutex_exists=mutex,second_ti_process=other_process,
                sbie_module=sandbox,native_calls=calls,destination=hex(expected))

def main():
    original=Path('C:/Program Files (x86)/TIOnline/ti.exe').read_bytes()
    assert hashlib.sha256(original).hexdigest()==EXE_SHA
    mapped=pefile.PE(data=original).get_memory_mapped_image()
    token='+dev\0'.encode('utf-16le');assert mapped.count(token)==5
    string_va=0x759184
    assert mapped[string_va-0x400000:string_va-0x400000+len(token)]==token
    references=[];offset=0;needle=struct.pack('<I',string_va)
    while (offset:=mapped.find(needle,offset))!=-1:
        references.append(hex(0x400000+offset));offset+=1
    assert references==['0x759062']
    cases=[case(False,*values,bypass=True) for values in ((False,False,False),(True,True,False),(False,True,False))]
    cases.extend(case(False,*values) for values in ((False,False,False),(True,False,False),(False,True,False)))
    changed=bytearray(mapped)
    for address in (0x759076,0x75907f):changed[address-0x400000:address-0x400000+2]=b'\x90\x90'
    differences=[hex(0x400000+i) for i,(a,b) in enumerate(zip(mapped,changed)) if a!=b]
    assert differences==['0x759076','0x759077','0x75907f','0x759080']
    assert (ROOT/'launcher/GameStarter.cs').read_bytes()==(ROOT/'reports/arena-surroundings-implementation/client-qa/GameStarter.cs').read_bytes()
    report=dict(passed=True,exe_sha256=EXE_SHA,argument_used=False,alternative_token_audit='+dev',token_string_va=hex(string_va),
        token_references=references,cases=cases,
        native_probe_scope='Original entry branch executes; command-line parser/OS guard function returns are explicit stubs. No clients or sockets.',
        bypass_effects=['Only suppress startup exit branches after named mutex and ti.exe process-count guards'],
        memory_changes=[dict(address='0x759076',before='7569',after='9090'),dict(address='0x75907f',before='7560',after='9090')],
        changed_addresses=differences,
        rejected_native_argument_effects=['Bypass named startup mutex {total_influence}',
            'Bypass repeated ti.exe basename process count','Bypass SbieDll.dll startup detection',
            'Lower Debug and GUI logging severity thresholds at0x6687eb',
            'Enable optional event/window-title logging at0x6f7bb4, gated76d9a4',
            'Register developer console commands at0x703119; registration does not execute them',
            'Set dev76db8d at0x7467eb; enable console-on-error at0x74610a and bypass retail Ctrl+H/Z block at0x748221'],
        renderer_effects='No +dev argument or dev global changes: ordinary render/fog/ground-mask/console initialization remains byte-identical. Only two startup exit branches change in own memory.',
        non_startup_dev_references=['0x6687eb','0x6f7bb4','0x703119','0x7467e1'],
        production_launcher_sha256=hashlib.sha256((ROOT/'launcher/GameStarter.cs').read_bytes()).hexdigest(),
        qa_loader_sha256=hashlib.sha256((ROOT/'reports/arena-surroundings-implementation/client-qa/GameStarter.cs').read_bytes()).hexdigest(),
        qa_helper_sha256=hashlib.sha256((ROOT/'reports/arena-surroundings-implementation/client-qa/bin/TioQaClient.exe').read_bytes()).hexdigest(),
        native_files_changed=False,production_launcher_changed=False,graphical_clients_started=0)
    path=ROOT/'reports/arena-surroundings-implementation/client-qa/native-multi-instance-verification.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,cases=len(cases),renderer_flags_modified=False,report=str(path))))

if __name__=='__main__':main()
