"""Execute the pinned original LSLoginResult error consumer; no game or sockets.

The dispatcher, byte reader and status-to-text table run as original x86.
Opaque UI calls and Delphi string allocation/cleanup are explicitly stubbed.
This proves the selected UI calls and message, not actual dialog rendering.
"""
import argparse
import json
from pathlib import Path

from verify_auth_native import emulator, put32, get32, return_from_stub, DATA, STOP, EXPECTED_SHA
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_EBP, UC_X86_REG_EIP
from tio.protocol.login import LoginFailureStatus, encode_login_failure


def wide_string(uc, pointer):
    length = get32(uc, pointer-4)
    if length > 256: raise AssertionError('Unexpected native error string length')
    return bytes(uc.mem_read(pointer, length*2)).decode('utf-16le')


def consume(status):
    packet = encode_login_failure(status)
    uc = emulator()
    uc.mem_write(DATA, packet)
    uc.mem_write(0xac48e9, b'\0')
    put32(uc,0xac622c,DATA+0x3000)
    result = dict(payload_hex=packet.hex(), parser=None, called=[], stubbed=[])
    noops = {0x9cfa38,0x6061b0,0xa40094,0x6d4190,0x6d4090,
        0x40b0fc,0x435664,0x40b09c,0x4244b4,0x40c1bc}
    def hook(u, addr, size, user):
        if addr == STOP:
            u.emu_stop(); return
        if addr == 0x87d00c: result['parser'] = hex(addr)
        if addr == 0x87d0fd:
            result['consumed_payload_bytes'] = get32(u,u.reg_read(UC_X86_REG_EBP)-8)-(DATA+1)
        if addr == 0x87c76c:
            raise AssertionError('Denial invoked the successful server-list request')
        if addr == 0x40b47c:
            # Preserve the actual static wide-string chosen by native 6d46e8.
            put32(u,u.reg_read(UC_X86_REG_EAX),u.reg_read(UC_X86_REG_EDX))
            result['stubbed'].append(hex(addr));return_from_stub(u)
        elif addr in noops:
            result['stubbed'].append(hex(addr))
            if addr == 0xa40094: result['called'].append('stop_waiting_0xa40094')
            if addr == 0x6d4190:
                result['error_text'] = wide_string(u,u.reg_read(UC_X86_REG_EAX))
                result['called'].append('error_dialog_0x6d4190')
            if addr == 0x6d4090: result['called'].append('login_return_0x6d4090')
            return_from_stub(u)
    uc.hook_add(UC_HOOK_CODE,hook)
    uc.reg_write(UC_X86_REG_EAX,packet[0])
    uc.reg_write(UC_X86_REG_EDX,DATA+1)
    uc.reg_write(UC_X86_REG_ECX,len(packet))
    uc.emu_start(0x87daa4, STOP+1, count=20000)
    assert uc.reg_read(UC_X86_REG_EIP) == STOP, 'Instruction budget exhausted'
    assert result['parser'] == '0x87d00c'
    assert result['consumed_payload_bytes'] == 1
    assert result['called'] == ['stop_waiting_0xa40094','error_dialog_0x6d4190','login_return_0x6d4090']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    expected = {3:'Wrong username or password',4:'Access failed',7:'Account already in use',
        15:'Server overloaded',16:'Server maintenance. Try again later.'}
    cases = [consume(status) for status in LoginFailureStatus]
    for case in cases: assert case['error_text'] == expected[bytes.fromhex(case['payload_hex'])[1]]
    report = dict(binary_sha256=EXPECTED_SHA,
        method='Original x86 dispatcher, LSLoginResult parser and status text table under Unicorn; opaque UI and string allocation/cleanup stubbed; no sockets',
        actual_dialog_rendering_verified=False,cases=cases)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'{len(cases)} original-x86 login denial cases passed; no game or network used.')


if __name__ == '__main__': main()
