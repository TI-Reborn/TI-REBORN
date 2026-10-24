"""Read-only disassembly of the pinned original game economic windows."""
from pathlib import Path
import hashlib,json,re,struct,sys
import capstone,pefile

ROOT=Path(__file__).resolve().parents[1]
BINARY=Path('C:/Program Files (x86)/TIOnline/silver.dll')
EXPECTED='a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11'
raw=BINARY.read_bytes()
assert hashlib.sha256(raw).hexdigest()==EXPECTED
pe=pefile.PE(data=raw);image=pe.get_memory_mapped_image();base=pe.OPTIONAL_HEADER.ImageBase
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
md.skipdata=True

def disasm(start,size):
    return '\n'.join(f'{i.address:08x} {i.mnemonic:8} {i.op_str}' for i in md.disasm(image[start-base:start-base+size],start))

def refs(address):
    needle=struct.pack('<I',address)
    return [base+i for i in range(len(image)) if image.startswith(needle,i)]

if __name__=='__main__':
    if sys.argv[1]=='disasm': print(disasm(int(sys.argv[2],0),int(sys.argv[3],0)))
    elif sys.argv[1]=='refs': print([hex(i) for i in refs(int(sys.argv[2],0))])
    elif sys.argv[1]=='calls':
        a=int(sys.argv[2],0);print([hex(base+i) for i in range(len(image)-5) if image[i]==0xe8 and base+i+5+struct.unpack_from('<i',image,i+1)[0]==a])
    elif sys.argv[1]=='func':
        a=int(sys.argv[2],0)
        for i in md.disasm(image[a-base:a-base+0x2000],a):
            print(f'{i.address:08x} {i.mnemonic:8} {i.op_str}')
            if i.mnemonic=='ret':break
    elif sys.argv[1]=='strings':
        for r in json.loads((ROOT/'evidence/TI.silver.dll.strings.json').read_text()):
            if re.search(sys.argv[2],r['string'],re.I):print(r['va'],r['string'])
