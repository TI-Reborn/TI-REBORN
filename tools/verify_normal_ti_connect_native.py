"""Isolated original TI Unicode adapter -> TLS thunk -> ORANGE byte-mode proof.

Executes pinned x86 code only. No game process, credentials or network are used.
Unicode conversion/allocation and FillChar are isolated helper stubs; original
TI dispatch, endpoint copying, string release and ORANGE mode gates execute.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct

import pefile
import unicorn as U
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP

ROOT = Path(__file__).resolve().parents[1]
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
ORIGINAL_SHA = 'a3cabaf3ba571d737ec7cc6105f96b3f11ce217398477209fcf54f7737feae47'


def run_cases(ti_path):
    raw = Path(ti_path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == TI_SHA
    pe = pefile.PE(data=raw)
    image = pe.get_memory_mapped_image()
    original = (ROOT / 'evidence/loader-user32-fix/unpacked-0xc9b0000.bin').read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    cases = []
    for mode in (0, 1):
        for fixed in (False, True):
            machine = U.Uc(U.UC_ARCH_X86, U.UC_MODE_32)
            machine.mem_map(0, 0x1000)
            machine.mem_map(0x400000, (len(image) + 0xfff) & ~0xfff)
            machine.mem_write(0x400000, image)
            machine.mem_map(0xc9b0000, 0x7000)
            machine.mem_write(0xc9b0000, original)
            machine.mem_map(0x10000000, 0x20000)
            machine.mem_map(0x20000000, 0x1000)
            machine.mem_map(0x30000000, 0x10000)
            stack, thunk_address, loopback = 0x10010000, 0x20000000, 0x20000080
            stop, obj, heap = 0x20000800, 0x30008000, [0x30000100]

            def read_u32(address):
                return struct.unpack('<I', machine.mem_read(address, 4))[0]

            def write_u32(address, value):
                machine.mem_write(address, struct.pack('<I', value))

            def string(value, wide=True):
                pointer = heap[0]
                unit = 2 if wide else 1
                data = value.encode('utf-16le' if wide else 'ascii')
                machine.mem_write(pointer, struct.pack('<HHiI', 1200 if wide else 1251, unit, -1, len(value)) + data + b'\0' * unit)
                heap[0] += ((12 + len(data) + unit + 15) // 16) * 16
                return pointer + 12

            host, key = string('185.184.42.88'), string('')
            machine.mem_write(loopback, b'127.0.0.1\0')
            write_u32(0x786518, thunk_address)
            write_u32(0x76da80, 1)
            write_u32(0x76da84, 0)
            write_u32(0xc9b50f0, obj)
            machine.mem_write(0xc9b50f5, b'\1')
            thunk = bytearray.fromhex('9c50c744240c') + struct.pack('<I', loopback)
            thunk += bytes.fromhex('8b442418') + bytes([0x80 if fixed else 0x83, 0xf8, 0, 0xb8])
            thunk += struct.pack('<I', 41001) + bytes.fromhex('7405b8') + struct.pack('<I', 41002)
            thunk += bytes.fromhex('89442410589de9')
            thunk += struct.pack('<I', (0xc9b1670 - (thunk_address + len(thunk) + 4)) & 0xffffffff)
            assert len(thunk) == 40
            machine.mem_write(thunk_address, bytes(thunk))
            captured = {}

            def return_from_stub(pop=0):
                position = machine.reg_read(UC_X86_REG_ESP)
                target = read_u32(position)
                machine.reg_write(UC_X86_REG_ESP, position + 4 + pop)
                machine.reg_write(UC_X86_REG_EIP, target)

            def hook(_machine, address, _size, _user):
                if address in (0x40ba4c, 0x40be68):
                    wide = address == 0x40ba4c
                    source = machine.reg_read(UC_X86_REG_EDX)
                    count = read_u32(source - 4) if source else 0
                    value = bytes(machine.mem_read(source, count * (2 if wide else 1))).decode('utf-16le' if wide else 'ascii') if source else ''
                    write_u32(machine.reg_read(UC_X86_REG_EAX), string(value, not wide))
                    return_from_stub()
                elif address == 0x407b80:
                    machine.mem_write(machine.reg_read(UC_X86_REG_EAX), bytes([machine.reg_read(UC_X86_REG_ECX) & 255]) * machine.reg_read(UC_X86_REG_EDX))
                    return_from_stub()
                elif address == 0x718c01:
                    captured['eax_before_mov_al'] = machine.reg_read(UC_X86_REG_EAX)
                elif address == thunk_address:
                    position = machine.reg_read(UC_X86_REG_ESP)
                    captured['mode_dword'] = read_u32(position + 16)
                    captured['mode_byte'] = captured['mode_dword'] & 255
                    captured['opaque_argument_preserved'] = read_u32(position + 12) != 0
                elif address == 0xc9b1670:
                    captured['selected_port'] = read_u32(machine.reg_read(UC_X86_REG_ESP) + 8)
                elif address in (0xc9b28a0, 0xc9b2a40):
                    captured['native_branch'] = 'mode0-start' if address == 0xc9b28a0 else 'mode1-reconnect'
                    machine.emu_stop()
                elif address == 0x3000f000:
                    return_from_stub(4)

            machine.hook_add(U.UC_HOOK_CODE, hook)
            write_u32(0xc9b3008, 0x3000f000)
            write_u32(0xc9b3004, 0x3000f000)
            machine.mem_write(obj + 0x12e, bytes([mode]))
            machine.mem_write(stack, struct.pack('<5I', stop, host, 28512, key, mode))
            machine.reg_write(UC_X86_REG_ESP, stack)
            machine.emu_start(0x71c1b8, stop, count=50000)
            assert captured['mode_byte'] == mode and captured['mode_dword'] > 255
            assert captured['selected_port'] == (41001 if fixed and mode == 0 else 41002)
            assert captured['native_branch'] == ('mode0-start' if mode == 0 else 'mode1-reconnect')
            cases.append(dict(requested_mode=mode, byte_compare=fixed, **captured))
    return dict(passed=True, ti_sha256=TI_SHA, original_fixture_sha256=ORIGINAL_SHA,
                method='Original71c1b8->718b94->67e5c8/40af54->route->ORANGE1670/1a90 in isolated x86',
                stubs=['Unicode/ANSI allocation/conversion', 'FillChar', 'EnterCriticalSection'],
                game_processes_started=0, network_requests=0, credentials_used=False, cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ti', type=Path, default=Path(r'C:\Program Files (x86)\TIOnline\ti.exe'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = run_cases(args.ti)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
