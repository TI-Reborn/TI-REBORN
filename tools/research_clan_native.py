"""Read-only original clan protocol investigation."""
from pathlib import Path
import json,struct,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32

ROOT=Path(__file__).resolve().parents[1]
PE=pefile.PE(r'C:\Program Files (x86)\TIOnline\silver.dll')
DATA=PE.get_memory_mapped_image();BASE=PE.OPTIONAL_HEADER.ImageBase
MD=Cs(CS_ARCH_X86,CS_MODE_32)

def disasm(address,size=160):
    for i in MD.disasm(DATA[address-BASE:address-BASE+size],address):print(f'{i.address:x} {i.mnemonic} {i.op_str}')

def strings():
    source=json.loads((ROOT/'evidence/TI.silver.dll.strings.json').read_text())
    for row in source:
        text=row['string']
        if 'clan' not in text.lower():continue
        if len(text)>150:continue
        address=BASE+PE.get_rva_from_offset(row['offset'])
        needle=struct.pack('<I',address);pos=0;refs=[]
        while True:
            pos=DATA.find(needle,pos)
            if pos<0:break
            refs.append(hex(BASE+pos));pos+=1
        print(hex(address),repr(text),'refs',','.join(refs[:15]))

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='calls':
        target=int(sys.argv[2],16)
        for p in range(len(DATA)-5):
            if DATA[p]==0xe8 and BASE+p+5+struct.unpack_from('<i',DATA,p+1)[0]==target:print(hex(BASE+p))
    elif len(sys.argv)>1:disasm(int(sys.argv[1],16),int(sys.argv[2]) if len(sys.argv)>2 else 160)
    else:strings()
