"""Original nonempty10 parser and nested6d01f8. UI/lifecycle/property calls and CString conversion stubbed."""
import json,pefile,capstone
from verify_auth_native import *
from tio.protocol.character_select import CharacterRecord,encode_character_list

def run(optional):
    packet=encode_character_list((CharacterRecord(7,b'Probe',1,0x12345678,9,0,255 if optional else 0,bytes(range(1,7)) if optional else b'',tuple(range(101,120)),8,0xabcdef01,255),))
    u=emulator();u.mem_map(DATA+0x10000,0x30000);u.mem_write(DATA,packet)
    put32(u,0xac618c,DATA+0x1000);put32(u,0xac5a40,DATA+0x2000);put32(u,0xac5814,DATA+0x3000)
    obj=DATA+0x10000;props=[];consumed=None;strings=[];stubs=[]
    pe=pefile.PE(str(BINARY));md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
    targets={int(i.op_str,16) for i in md.disasm(pe.get_data(0x889eac-0x400000,0x590),0x889eac) if i.mnemonic=='call' and i.op_str.startswith('0x')}
    readers={0x605d68,0x605d8c,0x605db8,0x605d74,0x6d01f8}
    def hook(uc,addr,size,user):
        nonlocal consumed
        a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX)
        if addr==0x88a3e6:consumed=get32(uc,uc.reg_read(UC_X86_REG_EBP)-0x29c)-(DATA+1)
        if addr==0x605f1c:
            ptr=get32(uc,a);raw=bytearray()
            while bytes(uc.mem_read(ptr,1))!=b'\0':raw.extend(uc.mem_read(ptr,1));ptr+=1
            put32(uc,a,ptr+1);put32(uc,d,0);strings.append(raw.hex())
        elif addr==0xa844a0:uc.reg_write(UC_X86_REG_EAX,obj)
        elif addr==0xa93f70:uc.reg_write(UC_X86_REG_EAX,0xffffffff)
        elif addr==0xa69d68:uc.reg_write(UC_X86_REG_EAX,0)
        elif addr==0x98f978:props.append([uc.reg_read(UC_X86_REG_ECX),get32(uc,d+8)])
        elif addr not in targets or addr in readers:return
        stubs.append(hex(addr));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+1);u.reg_write(UC_X86_REG_EDX,len(packet))
    u.emu_start(0x889eac,STOP,count=30000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==len(packet)-1
    assert get32(u,obj+0x28)==7 and get32(u,obj+0x6000)==0x12345678
    assert get32(u,obj+0x60dc)==0xabcdef01 and bytes(u.mem_read(obj+0x5ff0,1))==b'\1'
    assert get32(u,obj+0x5ffc)==8  # same level destination as PetInfo 8c4afd
    assert [v for _,v in props]==[101,102,105,106,107,108,109,110,111,112,113]
    assert bytes(u.mem_read(obj+0x60,12))==(bytes.fromhex('020003000400010005000600') if optional else b'\0'*12)
    assert strings==[b'Probe'.hex()]
    return {'packet_hex':packet.hex(),'consumed':consumed,'properties':props,'appearance_hex':bytes(u.mem_read(obj+0x60,12)).hex(),'stubs':sorted(set(stubs))}

def missing_catalog():
    import unicorn as U
    u=emulator();u.mem_unmap(0,0x1000)
    put32(u,0xac637c,DATA+0x1000);put32(u,0xac4e70,0)
    u.reg_write(UC_X86_REG_EAX,0);reads=[]
    def invalid(uc,access,address,size,value,user):
        reads.append(address);return False
    u.hook_add(U.UC_HOOK_MEM_INVALID,invalid)
    try:u.emu_start(0xa78afc,STOP,count=1000)
    except U.UcError:pass
    else:raise AssertionError('Expected missing catalog access')
    assert reads==[0x116] and u.reg_read(UC_X86_REG_EIP)==0xa78b1c
    return {'method':'original catalog lookup, NULL table, no UI','fault_va':'0xa78b1c','read_address':'0x116'}

def main():
    cases=[run(False),run(True),missing_catalog()]
    (ROOT/'evidence/native_character_record_probe.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('3 original-x86 record/catalog cases passed.')
if __name__=='__main__':main()
