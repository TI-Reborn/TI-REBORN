"""Execute original TIO x86 dispatcher/parser in Unicorn, with explicit UI stubs.

No ORANGE transport or UI behavior is simulated as a successful login. The
probe verifies opcode dispatch, reader consumption, saved field, and which
follow-up function is called. It also executes the original u32 transform.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tio.protocol.login import LSAuthResult, encode_ls_auth_result, transform_auth_value

BINARY = Path(r'C:\Program Files (x86)\TIOnline\silver.dll')
EXPECTED_SHA = 'a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11'
DATA = 0x2000000
STACK = 0x3000000
STOP = STACK + 0x100


def emulator():
    raw = BINARY.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA:
        raise RuntimeError('Unrecognized silver.dll build; addresses must be re-established')
    pe = pefile.PE(data=raw)
    image = pe.get_memory_mapped_image()
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0, 0x1000)  # Delphi SEH chain at fs:[0]. No exceptions are emulated.
    uc.mem_map(0x400000, (len(image)+0xfff)&~0xfff)
    uc.mem_write(0x400000, image)
    uc.mem_map(DATA, 0x10000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_write(STACK+0x8000, struct.pack('<I',STOP))
    uc.reg_write(UC_X86_REG_ESP, STACK+0x8000)
    return uc


def put32(uc, address, value):
    uc.mem_write(address, struct.pack('<I',value))


def get32(uc, address):
    return struct.unpack('<I',uc.mem_read(address,4))[0]


def return_from_stub(uc):
    sp = uc.reg_read(UC_X86_REG_ESP)
    uc.reg_write(UC_X86_REG_EIP,get32(uc,sp))
    uc.reg_write(UC_X86_REG_ESP,sp+4)


def consume(packet):
    uc = emulator()
    uc.mem_write(DATA, packet)
    sentinel = 0xdeadbeef
    put32(uc,0xacf3ec,sentinel)
    uc.mem_write(0xac48e8,b'\0')  # Select the normal (not alternate auth) branch.
    put32(uc,0xac59a8,DATA+0x1000)  # boolean false
    put32(uc,0xac5788,DATA+0x2000)  # zeroed local account record
    put32(uc,0xac622c,DATA+0x3000)  # opaque UI root indirection
    result = {'payload_hex':packet.hex(),'called':[], 'stubbed':[], 'parser':None}
    noops = {0x9cfa38,0x6061b0,0xa40094,0x6d4190,0x6d4090,0x40b0fc}
    def hook(u,addr,size,user):
        if addr == STOP:
            u.emu_stop(); return
        if addr == 0x87ce60:
            result['parser'] = hex(addr)
        if addr == 0x87cf57:
            result['consumed_payload_bytes'] = get32(u,u.reg_read(UC_X86_REG_EBP)-4)-(DATA+1)
        if addr in noops or addr in (0x688338,0x6d46e8,0x87c604):
            result['stubbed'].append(hex(addr))
            if addr in (0x688338,0x6d46e8):
                put32(u,u.reg_read(UC_X86_REG_EDX),0)
            if addr == 0x87c604:
                result['called'].append('login_builder_0x87c604')
            return_from_stub(u)
    uc.hook_add(UC_HOOK_CODE,hook)
    uc.reg_write(UC_X86_REG_EAX,packet[0])
    uc.reg_write(UC_X86_REG_EDX,DATA+1)
    uc.reg_write(UC_X86_REG_ECX,len(packet))
    uc.emu_start(0x87daa4, STOP+1, count=20000)
    if uc.reg_read(UC_X86_REG_EIP) != STOP:
        raise AssertionError('Parser did not return within instruction budget')
    result['saved_u32'] = get32(uc,0xacf3ec)
    result['dispatcher_handled'] = uc.reg_read(UC_X86_REG_EAX) & 0xff
    return result


def native_transform(value):
    uc = emulator()
    put32(uc,0xacf3ec,value)
    uc.emu_start(0x87c5e4, STOP, count=100)
    if uc.reg_read(UC_X86_REG_EIP) != STOP:
        raise AssertionError('Transform did not return')
    return get32(uc,0xacf3ec)


def main():
    results=[]
    for value in (0,4,0x12345678,0x80000000,0xffffffff):
        packet = encode_ls_auth_result(LSAuthResult(0,value))
        result = consume(packet)
        assert result['parser']=='0x87ce60'
        assert result['saved_u32']==value
        assert result['consumed_payload_bytes']==5
        assert result['called']==['login_builder_0x87c604']
        assert result['dispatcher_handled']==1
        result['transformed_u32']=native_transform(value)
        assert result['transformed_u32']==transform_auth_value(value)
        results.append(result)
    for status in (1,0x12,0xff):
        result=consume(encode_ls_auth_result(LSAuthResult(status)))
        assert result['saved_u32']==0xdeadbeef
        assert result['consumed_payload_bytes']==1
        assert result['called']==[]
        assert result['dispatcher_handled']==1
        results.append(result)
    unknown=consume(b'\xfa')
    assert unknown['dispatcher_handled']==0 and unknown['parser'] is None
    results.append(unknown)
    report = {'binary_sha256':EXPECTED_SHA,'method':'original x86 under Unicorn; UI/log/string lookup and login-builder calls stubbed; no sockets', 'cases':results}
    (ROOT/'evidence'/'native_auth_probe.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'{len(results)} original-x86 dispatcher/parser cases passed; 5 original-x86 transform cases passed.')


if __name__ == '__main__':
    main()
