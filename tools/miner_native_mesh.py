"""Read legacy miner legs with inert out-of-range zero-weight joints sanitized."""
import struct
from pathlib import Path
from tools.mdjx_mesh import read
ROOT=Path(__file__).resolve().parents[1]

def compatible(path):
 path=Path(path);raw=bytearray(path.read_bytes());nv,ni,nb,flag=struct.unpack_from('<4I',raw);at=16;fixed=[]
 assert 0<nv<100000 and 0<nb<128 and flag==1
 for i in range(nv):
  count=struct.unpack_from('<I',raw,at)[0];assert 0<count<=8
  joints=struct.unpack_from('<'+str(count)+'I',raw,at+40);weights=struct.unpack_from('<'+str(count)+'f',raw,at+40+4*count)
  for j,(bone,weight) in enumerate(zip(joints,weights)):
   if bone>=nb:
    assert weight==0.,'Nonzero influence references missing bone'
    struct.pack_into('<I',raw,at+40+j*4,0);fixed.append((i,j,bone))
  at+=40+8*count
 if not fixed:return read(path)
 normalized=ROOT/'reports/miner-model-20261021/normalized-source'/path.name;normalized.parent.mkdir(parents=True,exist_ok=True);normalized.write_bytes(raw)
 mesh=read(normalized);assert len(fixed)==3 and path.name=='freakminer_legs.mdjx'
 return mesh
