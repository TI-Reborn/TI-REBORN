"""Bounded native MDJX mesh reader/writer; preserve rig tails verbatim.

Skinned meshes carry bones and per-vertex weights. Static meshes (most
weapons) have no bones; a few (minigun, RPG) carry one bone while their
vertices still have zero joint influences.
"""
from dataclasses import dataclass,replace
from pathlib import Path
import math,struct


@dataclass
class Vertex:
    position: tuple
    normal: tuple
    uv: tuple
    extra: int
    joints: tuple
    weights: tuple


@dataclass
class Mesh:
    vertices: list
    indices: tuple
    bones: list
    flag: int
    tail: bytes


def read(path):
    raw=Path(path).read_bytes();nv,ni,nb,flag=struct.unpack_from('<4I',raw)
    assert 0<nv<100000 and 0<ni<1000000 and ni%3==0 and 0<=nb<512 and flag==1
    at=16;vertices=[]
    for _ in range(nv):
        n=struct.unpack_from('<I',raw,at)[0];assert (0<=n<=8) if nb else n==0
        floats=struct.unpack_from('<8f',raw,at+4);extra=struct.unpack_from('<I',raw,at+36)[0]
        joints=struct.unpack_from('<'+str(n)+'I',raw,at+40)
        weights=struct.unpack_from('<'+str(n)+'f',raw,at+40+4*n)
        assert all(j<nb for j in joints) and all(math.isfinite(v) for v in (*floats,*weights))
        assert all(w>=0 for w in weights) and (abs(sum(weights)-1)<.002 if n else True)
        vertices.append(Vertex(floats[:3],floats[3:6],floats[6:],extra,joints,weights));at+=40+8*n
    indices=struct.unpack_from('<'+str(ni)+'I',raw,at);assert max(indices)<nv;at+=ni*4
    tail=raw[at:];bones=[]
    for i in range(nb):
        nc,nl=struct.unpack_from('<2I',raw,at);at+=8;assert nc<nb and 0<nl<128
        name=raw[at:at+nl].decode('ascii');assert raw[at+nl]==0;at+=nl+1
        pose=struct.unpack_from('<6f',raw,at);at+=24
        parent=struct.unpack_from('<I',raw,at)[0];at+=4
        children=struct.unpack_from('<'+str(nc)+'I',raw,at);at+=nc*4
        assert parent<nb and all(c<nb for c in children)
        bones.append(dict(name=name,parent=parent,children=children,head=pose[:3],tip=pose[3:]))
    assert len(raw)-at==nb*48
    matrices=struct.unpack_from('<'+str(nb*12)+'f',raw,at);assert all(math.isfinite(x) for x in matrices)
    return Mesh(vertices,indices,bones,flag,tail)


def encode(mesh):
    out=bytearray(struct.pack('<4I',len(mesh.vertices),len(mesh.indices),len(mesh.bones),mesh.flag))
    for v in mesh.vertices:
        n=len(v.joints);assert n==len(v.weights) and ((0<=n<=4) if mesh.bones else n==0)
        out+=struct.pack('<I8fI',n,*v.position,*v.normal,*v.uv,v.extra)
        out+=struct.pack('<'+str(n)+'I',*v.joints)+struct.pack('<'+str(n)+'f',*v.weights)
    out+=struct.pack('<'+str(len(mesh.indices))+'I',*mesh.indices)+mesh.tail
    return bytes(out)


def normalized(v):
    length=math.sqrt(sum(a*a for a in v));return tuple(a/length for a in v) if length>1e-12 else (0.,1.,0.)


def normals(mesh):
    # Weld exact duplicate positions for continuous shading across UV seams.
    summed={};keys=[tuple(round(v,6) for v in n.position) for n in mesh.vertices]
    for at in range(0,len(mesh.indices),3):
        a,b,c=mesh.indices[at:at+3];p,q,r=[mesh.vertices[i].position for i in (a,b,c)]
        u=[q[i]-p[i] for i in range(3)];v=[r[i]-p[i] for i in range(3)]
        n=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        for i in (a,b,c):
            old=summed.get(keys[i],(0.,0.,0.));summed[keys[i]]=tuple(old[k]+n[k] for k in range(3))
    # Face winding in the native format can be opposite the stored normals.
    dot=sum(sum(summed.get(keys[i],(0,0,0))[k]*v.normal[k] for k in range(3)) for i,v in enumerate(mesh.vertices))
    sign=1 if dot>=0 else -1
    mesh.vertices=[replace(v,normal=normalized(tuple(sign*x for x in summed.get(keys[i],v.normal)))) for i,v in enumerate(mesh.vertices)]


def subdivide(mesh):
    vertices=list(mesh.vertices);cache={};indices=[]
    def middle(a,b):
        key=tuple(sorted((a,b)))
        if key in cache:return cache[key]
        x,y=vertices[a],vertices[b];weights={}
        for v in (x,y):
            for j,w in zip(v.joints,v.weights):weights[j]=weights.get(j,0)+w*.5
        pairs=sorted(weights.items(),key=lambda p:-p[1])[:4];total=sum(w for _,w in pairs)
        v=Vertex(tuple((a+b)*.5 for a,b in zip(x.position,y.position)),normalized(tuple(a+b for a,b in zip(x.normal,y.normal))),
                 tuple((a+b)*.5 for a,b in zip(x.uv,y.uv)),x.extra,tuple(j for j,w in pairs),tuple(w/total for j,w in pairs))
        cache[key]=len(vertices);vertices.append(v);return len(vertices)-1
    for at in range(0,len(mesh.indices),3):
        a,b,c=mesh.indices[at:at+3];ab,bc,ca=middle(a,b),middle(b,c),middle(c,a)
        indices.extend((a,ab,ca,ab,b,bc,ca,bc,c,ab,bc,ca))
    return replace(mesh,vertices=vertices,indices=tuple(indices))
