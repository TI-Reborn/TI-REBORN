"""Read-only verification of the unchanged legacy agreement loader and CRC32."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_legacy_project_agreement_client as release
from tools.publish_ui_modernization_remote import pe_at


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def native_crc32(image, raw):
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESP
    pe = pefile.PE(data=image)
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0x400000, (pe.OPTIONAL_HEADER.SizeOfImage + 4095) & ~4095)
    machine.mem_write(0x400000, pe.get_memory_mapped_image())
    machine.mem_map(0x100000, 0x10000)
    machine.mem_map(0x200000, 0x10000)
    machine.mem_map(0x300000, 0x1000)
    machine.mem_write(0x300000, b'\xcc')

    def call(address):
        machine.reg_write(UC_X86_REG_ESP, 0x10ffe0)
        machine.mem_write(0x10ffe0, struct.pack('<I', 0x300000))
        machine.emu_start(address, 0x300000, count=1000000)

    call(0x68abec)  # Actual published native CRC table initialisation.
    if len(raw) > 0x10000:
        raise ValueError('Agreement exceeds native chunk/test bound')
    machine.mem_write(0x200000, raw)
    machine.reg_write(UC_X86_REG_EAX, 0xffffffff)
    machine.reg_write(UC_X86_REG_EDX, 0x200000)
    machine.reg_write(UC_X86_REG_ECX, len(raw))
    call(0x68ab38)  # Actual published native CRC byte loop.
    return (~machine.reg_read(UC_X86_REG_EAX)) & 0xffffffff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or not release.regular(args.report) or not args.report.resolve().is_relative_to(release.FOLDER):
        raise ValueError('Use a new immutable agreement proof report')
    image = (release.CLIENT / 'source/silver.dll').read_bytes()
    source = (release.CLIENT / 'source/assets' / release.RULES_PATH).read_bytes()
    candidate = args.candidate.read_bytes()
    if (sha(image), len(image)) != (release.SILVER_SHA, release.SILVER_BYTES) or (sha(source), len(source)) != (release.RULES_SOURCE_SHA, release.RULES_SOURCE_BYTES):
        raise ValueError('Actual trusted HTTPS source images required')
    # Instructions were inspected at native entry points, not strings alone.
    guards = {
        'reads_saved_acceptance_key': (0x88834d, bytes.fromhex('b818848800')),
        'calculates_current_rules_crc': (0x8883a5, bytes.fromhex('e8b227e0ff')),
        'compares_saved_and_current_crc': (0x8883b2, bytes.fromhex('8b45fc8b55f8e8973fb8ff')),
        'requires_prompt_on_difference': (0x8883bd, bytes.fromhex('0f9505f848ac00')),
        'accept_handler_recalculates_crc': (0x888791, bytes.fromhex('e8c623e0ff')),
        'accept_handler_writes_acceptance_key': (0x8887ac, bytes.fromhex('b820888800e81aade1ff')),
        'popup_explicitly_reads_windows_1251': (0x888b8b, bytes.fromhex('b8e3040000')),
    }
    results = {}
    for name, (va, expected) in guards.items():
        actual = pe_at(image, va - 0x400000, len(expected))
        if actual != expected:
            raise ValueError('Unchanged native instruction guard differs: ' + name)
        results[name] = dict(va=hex(va), size=len(actual), sha256=sha(actual), passed=True)
    crc = {name: native_crc32(image, raw) for name, raw in [('source', source), ('candidate', candidate)]}
    if crc['source'] != zlib.crc32(source) & 0xffffffff or crc['candidate'] != zlib.crc32(candidate) & 0xffffffff or crc['source'] == crc['candidate']:
        raise ValueError('Native CRC must match independent implementation and change')
    report = dict(passed=True, source_sha256=sha(source), source_bytes=len(source), candidate_sha256=sha(candidate), candidate_bytes=len(candidate),
                  unchanged_silver_sha256=sha(image), native_instruction_guards=results, native_crc32_executed=crc,
                  independent_crc32_matches=True, original_reacceptance_required=True,
                  original_acceptance_handler_preserved=True, popup_codepage=1251,
                  stored_acceptance_modified=False, graphical_acceptance=False, hosted_mutations=0,
                  implementation_sha256=sha(Path(__file__).read_bytes()))
    release.immutable(args.report, (json.dumps(report, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(dict(passed=True, native_crc32=crc, stored_acceptance_modified=False), indent=2))


if __name__ == '__main__':
    main()
