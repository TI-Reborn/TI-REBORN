"""Read-only disassembly helper for the original loot protocol."""
import sys,struct,re
from pathlib import Path
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
binary='ti.exe' if '--exe' in sys.argv else 'silver.dll'
if '--exe' in sys.argv:sys.argv.remove('--exe')
p=pefile.PE(str(Path(r'C:\Program Files (x86)\TIOnline')/binary))
d=p.get_memory_mapped_image();base=0x400000
cs=Cs(CS_ARCH_X86,CS_MODE_32)
def dump(a,n):
    for i in cs.disasm(d[a-base:a-base+n],a):print(f'{i.address:08x} {i.mnemonic} {i.op_str}')
if sys.argv[1]=='dis':
    for i in range(2,len(sys.argv),2):dump(int(sys.argv[i],16),int(sys.argv[i+1],16))
elif sys.argv[1]=='rtti':
    a,n=int(sys.argv[2],16),int(sys.argv[3],16)
    for m in re.finditer(rb'[\x08\x09\x18](.{4})([\x03-\x60])([A-Za-z_][A-Za-z_0-9]*)',d[a-base:a-base+n],re.S):
        print(hex(struct.unpack('<I',m[1])[0]),m[3][:m[2][0]].decode())
elif sys.argv[1]=='ref':
    target=int(sys.argv[2],16)
    for m in re.finditer(re.escape(struct.pack('<I',target)),d):print('absolute',hex(base+m.start()))
    for m in re.finditer(b'\xe8',d):
        pos=m.start()
        if pos+5<len(d) and base+pos+5+struct.unpack_from('<i',d,pos+1)[0]==target:print('call',hex(base+pos))
