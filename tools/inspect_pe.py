"""Read-only PE strings, exports, xrefs and x86 disassembly (preferred VAs)."""
import argparse
import json
import re
from pathlib import Path
import capstone
import pefile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('binary', type=Path)
    ap.add_argument('--match', default='LSLogin|LSServer|LSAuth|NET3|PacketHandler|HandlePacket')
    ap.add_argument('--va', type=lambda x: int(x, 0))
    ap.add_argument('--size', type=lambda x: int(x, 0), default=512)
    ap.add_argument('--mapped', action='store_true', help='VA reads use mapped image offsets; requires --base and --va')
    ap.add_argument('--base', type=lambda x: int(x, 0))
    args = ap.parse_args()
    if args.mapped:
        if args.base is None or args.va is None:
            ap.error('--mapped requires --base and --va')
        raw = args.binary.read_bytes()
        start = args.va-args.base
        if start < 0 or start+args.size > len(raw):
            ap.error('Requested range outside mapped image')
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        for i in md.disasm(raw[start:start+args.size], args.va):
            print(f'{i.address:08x}  {i.bytes.hex():24} {i.mnemonic:8} {i.op_str}')
        return
    pe = pefile.PE(str(args.binary))
    base = pe.OPTIONAL_HEADER.ImageBase
    raw = args.binary.read_bytes()
    if args.va is not None:
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        for i in md.disasm(pe.get_data(args.va-base, args.size), args.va):
            print(f'{i.address:08x}  {i.bytes.hex():24} {i.mnemonic:8} {i.op_str}')
        return
    pattern = re.compile(args.match, re.I)
    for exp in getattr(getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', []):
        name = (exp.name or b'').decode('ascii', errors='replace')
        if pattern.search(name):
            print('EXPORT', hex(base+exp.address), name)
    found = [(m, enc) for pat, enc in [(rb'[\x20-\x7e]{5,}', 'ascii'), (rb'(?:[\x20-\x7e]\x00){5,}', 'utf-16le')] for m in re.finditer(pat, raw)]
    for m, encoding in found:
        s = m.group().decode(encoding)
        if not pattern.search(s):
            continue
        try:
            va = base+pe.get_rva_from_offset(m.start())
        except (pefile.PEFormatError, TypeError):
            continue
        needle = va.to_bytes(4, 'little')
        refs = []
        start = 0
        while (off := raw.find(needle, start)) >= 0:
            rva = pe.get_rva_from_offset(off)
            if rva is not None:
                refs.append(hex(base+rva))
            start = off+1
        print(json.dumps({'va': hex(va), 'offset': hex(m.start()), 'encoding': encoding, 'string': s, 'absolute_refs': refs}))


if __name__ == '__main__':
    main()
