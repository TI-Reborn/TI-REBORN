"""Execute the launcher's actual x86 destination thunk in Unicorn.

The launcher emits the exact BuildThunk bytes used by the native secure route.
This verifies register/flag/opaque preservation and loopback routing for both
native connection modes, without launching a game or sending credentials.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import subprocess
import tempfile

import unicorn
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
    UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP,
    UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', type=Path, default=ROOT/'launcher/bin/Release/net10.0-windows/TIO Launcher.exe')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/game-tls/native-route-proof.json')
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix='tio-tls-native-route-') as directory:
        proof_path = Path(directory)/'thunk.json'
        subprocess.run([str(args.launcher.resolve()), '--tls-route-proof', str(proof_path)],
                       check=True, timeout=15, capture_output=True)
        proof = json.loads(proof_path.read_text())
    registers = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                 UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
    results = []
    for mode_byte in (0, 1, 2, 255):
      for upper_bits in (0, 0x100, 0x12345600, 0x7fffff00, 0xffffff00):
        mode = upper_bits | mode_byte
        for flags in (0x202, 0x246, 0x293):
            machine = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
            thunk, host, target = (proof[key] for key in ('thunk_address', 'host_address', 'original_target'))
            machine.mem_map(thunk, 0x1000)
            machine.mem_map(target & ~0xfff, 0x1000)
            machine.mem_map(0x10000000, 0x2000)
            machine.mem_write(thunk, bytes.fromhex(proof['thunk_hex']))
            machine.mem_write(host, bytes.fromhex(proof['loopback_hex']))
            stack = 0x10001000
            before = [0x31415926, 0x0badcafe, 28512, 0x12345678, mode, 0x98765432]
            machine.mem_write(stack, struct.pack('<6I', *before))
            original = {register: 0x11111111*(index+1) for index, register in enumerate(registers)}
            for register, value in original.items():
                machine.reg_write(register, value)
            machine.reg_write(UC_X86_REG_ESP, stack)
            machine.reg_write(UC_X86_REG_EFLAGS, flags)
            machine.emu_start(thunk, target, count=100)
            after = list(struct.unpack('<6I', machine.mem_read(stack, 24)))
            expected_port = proof['login_port'] if mode_byte == 0 else proof['session_port']
            assert machine.reg_read(UC_X86_REG_EIP) == target
            assert after == [before[0], host, expected_port, *before[3:]]
            assert machine.reg_read(UC_X86_REG_ESP) == stack
            assert machine.reg_read(UC_X86_REG_EFLAGS) == flags
            assert all(machine.reg_read(register) == value for register, value in original.items())
            assert bytes(machine.mem_read(host, 10)) == b'127.0.0.1\0'
            results.append({'native_mode_dword': hex(mode), 'native_mode_byte': mode_byte,
                            'flags': hex(flags), 'destination': '127.0.0.1',
                            'port': expected_port, 'registers_flags_and_opaque_preserved': True})
    report = {'passed': True, 'launcher_sha256': hashlib.sha256(args.launcher.read_bytes()).hexdigest(),
              'method': 'Exact C# BuildThunk bytes executed as x86 in Unicorn; stops at original native target',
              'cases': results, 'graphical_clients_started': 0, 'network_requests': 0,
              'native_client_files_changed': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'cases': len(results), 'report': str(args.report)}))


if __name__ == '__main__':
    main()
