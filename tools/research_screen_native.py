"""Read-only disassembly of the pinned TI rendering and screen settings paths."""
import argparse
from pathlib import Path
import struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

parser = argparse.ArgumentParser()
parser.add_argument('--binary', type=Path, default=Path(r'C:\Users\jundu\AppData\Local\TIO-Online\ti.exe'))
parser.add_argument('--address', type=lambda s: int(s, 0))
parser.add_argument('--bytes', type=int, default=512)
parser.add_argument('--refs', type=lambda s: int(s, 0))
parser.add_argument('--calls', type=lambda s: int(s, 0))
parser.add_argument('--name')
args = parser.parse_args()
pe = pefile.PE(str(args.binary))
data = pe.get_memory_mapped_image()
base = pe.OPTIONAL_HEADER.ImageBase
if args.address is not None:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.skipdata = True
    offset = args.address-base
    assert 0 <= offset < len(data) and 0 < args.bytes <= 32768
    print('\n'.join(f'{i.address:08x} {i.bytes.hex():24} {i.mnemonic:8} {i.op_str}'
                    for i in md.disasm(data[offset:offset+args.bytes], args.address)))
if args.refs is not None:
    needle = struct.pack('<I',args.refs)
    start = 0
    while (offset := data.find(needle,start)) >= 0:
        print(hex(base+offset)); start=offset+1
if args.calls is not None:
    for offset in range(len(data)-5):
        if data[offset] in (0xe8,0xe9) and base+offset+5+struct.unpack_from('<i',data,offset+1)[0] == args.calls:
            print(hex(base+offset))
if args.name:
    for needle in (args.name.encode(),args.name.encode('utf-16le')):
        start=0
        while (offset := data.find(needle,start)) >= 0:
            before=data[max(0,offset-4):offset]
            print(hex(base+offset), 'preceding_u32', hex(struct.unpack('<I',before)[0]), data[max(0,offset-10):offset+len(needle)+10].hex())
            start=offset+len(needle)
