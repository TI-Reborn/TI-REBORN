import pefile,capstone,struct,sys
from pathlib import Path
p=pefile.PE(r'C:\Program Files (x86)\TIOnline\silver.dll'); image=p.get_memory_mapped_image(); md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
md.skipdata=True
if sys.argv[1]=='xref':
 for arg in sys.argv[2:]:
  addr=int(arg,16); pat=struct.pack('<I',addr); at=0; hits=[]
  while (at:=image.find(pat,at))>=0:
   hits.append(hex(at+0x400000));at+=1
  print(arg, hits)
else:
 start=int(sys.argv[1],16);size=int(sys.argv[2],16) if len(sys.argv)>2 else 512
 for i in md.disasm(image[start-0x400000:start-0x400000+size],start):print(f'{i.address:x}: {i.mnemonic} {i.op_str}')

