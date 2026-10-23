"""Bounded TICH ADJX animation and skeleton-only MDJX parsing.

ADJX has frame-major 3x3 row-vector skinning matrices and translations.
Return conventional column-vector 4x4 matrices for Blender and validation.
"""
import math,struct
from pathlib import Path

def skeleton(path):
 raw=Path(path).read_bytes();nv,ni,nb,flag=struct.unpack_from('<4I',raw)
 assert (nv,ni,flag)==(0,0,1) and 0<nb<128
 at=16;bones=[]
 for i in range(nb):
  nc,nl=struct.unpack_from('<2I',raw,at);at+=8;assert nc<nb and 0<nl<128
  name=raw[at:at+nl].decode('ascii');assert raw[at+nl]==0;at+=nl+1
  pose=struct.unpack_from('<6f',raw,at);at+=24
  parent=struct.unpack_from('<I',raw,at)[0];at+=4
  children=struct.unpack_from('<'+str(nc)+'I',raw,at);at+=nc*4
  assert parent<nb and all(c<nb for c in children)
  bones.append(dict(name=name,parent=parent,children=children,head=pose[:3],tip=pose[3:]))
 assert len(raw)-at==nb*48
 return bones

def animation(path):
 raw=Path(path).read_bytes();assert raw[:4]==b'TICH' and raw[4]==0
 version,fps,nb,frames=struct.unpack_from('<IfII',raw,5)
 assert version==1 and 0<fps<=120 and 0<frames<4000 and 0<nb<128
 names=[];positions=[];at=21
 for i in range(nb):
  nl=struct.unpack_from('<I',raw,at)[0];at+=4;assert 0<nl<128
  name=raw[at:at+nl].decode('ascii');assert raw[at+nl]==0;at+=nl+1
  positions.append(struct.unpack_from('<3f',raw,at));at+=12;names.append(name)
 assert len(raw)-at==frames*nb*48
 matrices=[]
 for frame in range(frames):
  row=[]
  for bone in range(nb):
   f=struct.unpack_from('<12f',raw,at);at+=48;assert all(math.isfinite(v) for v in f)
   row.append(((f[0],f[3],f[6],f[9]),(f[1],f[4],f[7],f[10]),(f[2],f[5],f[8],f[11]),(0.,0.,0.,1.)))
  matrices.append(row)
 return dict(fps=fps,frames=frames,names=names,positions=positions,matrices=matrices)
