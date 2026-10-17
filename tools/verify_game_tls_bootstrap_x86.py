"""Independently execute actual generated launcher bootstrap bytes in Unicorn.

No native client, credentials, sockets or host access. The proof JSON comes
from launcher --tls-bootstrap-proof, avoiding a hand-written code substitute.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                              UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
                              UC_X86_REG_EIP, UC_X86_REG_EFLAGS)

ROOT = Path(__file__).resolve().parents[1]
REGISTERS = dict(eax=UC_X86_REG_EAX, ebx=UC_X86_REG_EBX, ecx=UC_X86_REG_ECX, edx=UC_X86_REG_EDX,
                 esi=UC_X86_REG_ESI, edi=UC_X86_REG_EDI, ebp=UC_X86_REG_EBP, esp=UC_X86_REG_ESP)
PROTECTIONS = {0x04: UC_PROT_READ | UC_PROT_WRITE, 0x20: UC_PROT_READ | UC_PROT_EXEC,
               0x40: UC_PROT_READ | UC_PROT_WRITE | UC_PROT_EXEC}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def execute(proof, case='valid', api_failure=None):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    base, orange, unpacked = proof['allocation'], proof['orange_base'], proof['unpacked_base']
    export, target = proof['export_address'], proof['original_target']
    code = bytes.fromhex(proof['bootstrap_hex'])
    thunk = bytes.fromhex(proof['initial_thunk_hex'])
    uc.mem_map(base, 8192)
    uc.mem_map(orange, 8192)
    uc.mem_map(unpacked, 0x6000)
    uc.mem_map(proof['loader_store'] & ~0xfff, 4096)
    uc.mem_map(0x76d000, 4096)
    uc.mem_map(proof['virtual_protect'], 0x3000)
    stack, stack_size = 0x70000000, 0x10000
    uc.mem_map(stack, stack_size)
    uc.mem_write(base, code)
    uc.mem_write(proof['thunk_address'], thunk)
    uc.mem_write(proof['host_address'], b'127.0.0.1\0')
    signature = bytearray.fromhex(proof['original_signature_hex'])
    struct.pack_into('<I', signature, 1, unpacked + 0x50f5)
    struct.pack_into('<I', signature, 11, unpacked + 0x50f0)
    if case == 'wrong-opcode':
        signature[20] ^= 1
    elif case == 'wrong-data-relocation-1':
        struct.pack_into('<I', signature, 1, unpacked + 0x50f4)
    elif case == 'wrong-data-relocation-2':
        struct.pack_into('<I', signature, 11, unpacked + 0x50f1)
    uc.mem_write(target, bytes(signature))
    if case == 'misaligned-target':
        target += 1
    elif case == 'zero-unpacked-base':
        target = 0x1670
    elif case == 'orange-as-unpacked-base':
        target = orange + 0x1670
    uc.mem_write(export, b'\xe9' + struct.pack('<I', (target - export - 5) & 0xffffffff))
    if case == 'wrong-export-opcode':
        uc.mem_write(export, b'\xcc')
    uc.mem_write(proof['loader_store'], b'\xe9' + struct.pack('<I', (base - proof['loader_continue']) & 0xffffffff))
    uc.mem_write(proof['loader_continue'], b'\xcc')
    tracked_protection = {orange: 0x20, orange + 4096: 0x20, proof['loader_store'] & ~0xfff: 0x20, base: 0x40}
    uc.mem_protect(orange, 8192, PROTECTIONS[0x20])
    uc.mem_protect(proof['loader_store'] & ~0xfff, 4096, PROTECTIONS[0x20])
    uc.mem_protect(base + 4096, 4096, PROTECTIONS[0x04])
    initial = {name: 0x11110000 + index * 0x101 for index, name in enumerate(REGISTERS)}
    initial['eax'] = orange + (0x1000 if case == 'wrong-library-handle' else 0)
    initial['esp'] = stack + 0x8000
    for name, value in initial.items():
        uc.reg_write(REGISTERS[name], value)
    uc.reg_write(UC_X86_REG_EFLAGS, 0x247)
    initial_flags = uc.reg_read(UC_X86_REG_EFLAGS)
    state = dict(api_calls=[], api_count=0, exit_code=None, returned=False)
    def u32(address):
        return struct.unpack('<I', bytes(uc.mem_read(address, 4)))[0]
    def native_return(arguments, value):
        esp = uc.reg_read(UC_X86_REG_ESP)
        uc.reg_write(UC_X86_REG_EAX, value)
        uc.reg_write(UC_X86_REG_EIP, u32(esp))
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + arguments * 4)
    def hook(machine, address, size, unused):
        if address == proof['loader_continue']:
            state['returned'] = True
            machine.emu_stop()
            return
        if address == proof['exit_process']:
            state['exit_code'] = u32(machine.reg_read(UC_X86_REG_ESP) + 4)
            machine.emu_stop()
            return
        if address not in (proof['virtual_protect'], proof['flush_instruction_cache']):
            return
        state['api_count'] += 1
        fail = state['api_count'] == api_failure
        if address == proof['virtual_protect']:
            esp = machine.reg_read(UC_X86_REG_ESP)
            location, length, protection, old_pointer = [u32(esp + 4 + index * 4) for index in range(4)]
            state['api_calls'].append(dict(api='VirtualProtect', address=location, bytes=length,
                                          protection=protection, success=not fail))
            if not fail:
                page = location & ~0xfff
                old = tracked_protection.get(page, 0x04)
                machine.mem_write(old_pointer, struct.pack('<I', old))
                tracked_protection[page] = protection
                pages = ((location + length + 4095) & ~0xfff) - page
                machine.mem_protect(page, pages, PROTECTIONS[protection])
            native_return(4, 0 if fail else 1)
        else:
            state['api_calls'].append(dict(api='FlushInstructionCache', success=not fail))
            native_return(3, 0 if fail else 1)
    uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(base, base + len(code), count=10000)
    except Exception as error:
        raise AssertionError(dict(error=type(error).__name__, eip=hex(uc.reg_read(UC_X86_REG_EIP)),
                                  esp=hex(uc.reg_read(UC_X86_REG_ESP)), state=state)) from error
    success = case == 'valid' and api_failure is None
    if success:
        require(state['returned'] and state['exit_code'] is None, 'Bootstrap did not restore original loader continuation')
        require(all(uc.reg_read(REGISTERS[name]) == value for name, value in initial.items()), 'Bootstrap changed caller registers')
        require(uc.reg_read(UC_X86_REG_EFLAGS) == initial_flags, 'Bootstrap changed caller flags')
        require(u32(0x76da80) == orange, 'Original LoadLibrary result store was not performed')
        require(bytes(uc.mem_read(proof['loader_store'], 5)) == bytes.fromhex('a380da7600'), 'One-shot loader store was not restored')
        require(u32(proof['state_address'] + 12) == 3, 'Bootstrap did not reach complete phase')
        actual_thunk = bytes(uc.mem_read(proof['thunk_address'], len(thunk)))
        require(actual_thunk[:-4] == thunk[:-4] and
                (proof['thunk_address'] + len(thunk) + struct.unpack('<i', actual_thunk[-4:])[0]) & 0xffffffff == proof['original_target'],
                'Bootstrap route did not retain the real original ORANGE destination')
        export_jump = bytes(uc.mem_read(export, 5))
        require(export_jump[0] == 0xe9 and (export + 5 + struct.unpack('<i', export_jump[1:])[0]) & 0xffffffff == proof['thunk_address'],
                'Production export did not route to the authored thunk')
        require(tracked_protection[base] == 0x20 and tracked_protection[export & ~0xfff] == 0x20 and
                tracked_protection[proof['loader_store'] & ~0xfff] == 0x20, 'Bootstrap did not restore executable page protection')
    else:
        require(state['exit_code'] == 1 and not state['returned'], 'Failed guard/API resumed an unsafe native client')
    return dict(case=case, failing_api=api_failure, passed=True, returned_to_original_loader=state['returned'],
                own_process_exit_code=state['exit_code'], api_calls=len(state['api_calls']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof', type=Path, default=ROOT / 'reports/tls-launcher/bootstrap-thunk.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/game-tls/bootstrap-x86-verification.json')
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text(encoding='utf-8'))
    cases = [execute(proof)]
    cases.extend(execute(proof, case) for case in ('wrong-library-handle', 'wrong-export-opcode', 'misaligned-target',
        'zero-unpacked-base', 'orange-as-unpacked-base', 'wrong-opcode', 'wrong-data-relocation-1', 'wrong-data-relocation-2'))
    cases.extend(execute(proof, api_failure=index) for index in range(1, 7))
    report = dict(passed=True, kind='independent Unicorn execution of actual generated production bootstrap bytes',
        proof=str(args.proof.resolve()), checks=cases, sockets_created=0, native_clients_started=0,
        scope='x86 guards, real loader result/registers/flags, route destination, API fail-closed and page protection; no graphical gameplay')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, checks=len(cases), report=str(args.output))))


if __name__ == '__main__':
    main()
