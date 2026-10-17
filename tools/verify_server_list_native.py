"""Execute original06 parser, primitive readers and empty CString reader.
UI, allocations and Delphi string management explicitly stubbed; no live UI claim.
"""
import json,struct
from verify_auth_native import emulator,put32,get32,return_from_stub,DATA,STOP,ROOT,EXPECTED_SHA
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EBP,UC_X86_REG_EIP
from tio.protocol.server_list import ServerList,ServerEntry,encode_server_list


def run(packet,expected_entries,accepted=True):
    u=emulator();u.mem_write(DATA,packet)
    put32(u,0xac5d24,DATA+0x1000);put32(u,0xac5b7c,DATA+0x2000)
    records=[];calls=[];consumed=None
    def hook(uc,addr,size,user):
        nonlocal consumed
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if addr==0x87d397:
            consumed=get32(uc,uc.reg_read(UC_X86_REG_EBP)-8)-(DATA+1)
        noops={0xa69aa0,0x71e8ec,0x71e594,0x40b09c,0x40b0fc,0x40c06c,0x40742c}
        if addr==0x4244b4: put32(uc,edx,0)
        elif addr==0x40c244:
            put32(uc,eax,0);sp=uc.reg_read(UC_X86_REG_ESP)
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+32);return
        elif addr==0x40ce98: uc.reg_write(UC_X86_REG_EAX,DATA+0x4000+len(records)*16)
        elif addr==0x40b47c: put32(uc,eax,edx)
        elif addr==0x605ca4:
            assert bytes(uc.mem_read(eax,1))==b'\0';put32(uc,edx,0)
        elif addr==0x71fea0: records.append(bytes(uc.mem_read(edx,16)).hex())
        elif addr not in noops: return
        calls.append(hex(addr));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,6);u.reg_write(UC_X86_REG_EDX,DATA+1);u.reg_write(UC_X86_REG_ECX,len(packet))
    u.emu_start(0x87daa4,STOP,count=50000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert len(records)==len(expected_entries)
    assert ('0x71e594' in calls)==accepted
    if accepted: assert consumed==len(packet)-1
    for raw,e in zip(records,expected_entries):
        b=bytes.fromhex(raw)
        assert b[0]==e.unknown_u8_01 and b[14]==e.unknown_u8_02
        assert struct.unpack('<3H',b[8:14])==(e.unknown_u16_01,e.unknown_u16_02,e.unknown_u16_03)
        assert b[15]==e.unknown_u16_02*100//(e.unknown_u16_03+1)
    return {'packet_hex':packet.hex(),'records_hex':records,'consumed_payload_bytes':consumed,'ui_refresh_called':'0x71e594' in calls,'stubs':sorted(set(calls))}


def main():
    e=ServerEntry(7,b'\x7f\0\0\1',12345,25,100,3)
    cases=[run(encode_server_list(ServerList(flag,entries)),entries) for flag in (0,255) for entries in ((),(e,),(e,e))]
    # Native guard rejects this declared list before record reads. Never send malformed wire live.
    cases.append(run(bytes.fromhex('060100'),(),False))
    for count in (0,1,2,8,16):
        entry=ServerEntry(1,b'\x7f\0\0\1',28513,count,15,0)
        cases.append(run(encode_server_list(ServerList(0,(entry,))),(entry,)))
    out={'silver_sha256':EXPECTED_SHA,'method':__doc__,'cases':cases}
    (ROOT/'evidence/native_server_list_probe.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(f'{len(cases)} original-x86 server-list cases passed.')

if __name__=='__main__':main()
