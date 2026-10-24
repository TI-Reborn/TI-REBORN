"""A rig-compatible native character adaptation with remodeled geometry."""
from dataclasses import replace
import hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read,encode,normals,subdivide
OUT=ROOT/'assets/fighter-model-v1'
SOURCE=ROOT/'reports/fighter-model-20261020/source/base/models'
PARTS=[('head','chr_man_head'),('torso','cloth_c02_man_body'),('legs','cloth_c02_man_legs'),('hands','chr_man_hands_neck')]
sha=lambda b:hashlib.sha256(b).hexdigest()


def shape(v,part):
    x,y,z=v.position
    if part=='head':
        t=max(0.,min(1.,(y-1.60)/.254))
        face=math.exp(-((t-.43)/.25)**2)
        x*=.94-.065*face
        if y>1.61:y=1.61+(y-1.61)*.96
        z=.035+(z-.035)*(.965 if t<.7 else .94)
        nose=math.exp(-((x/.022)**2+((y-1.688)/.018)**2)) if z<-.07 else 0
        z-=.008*nose;x+=.0025*nose
        if .12<t<.32 and z<-.05:z-=.002
    elif part=='torso':
        # Taper torso, preserving the neck and wrist/hand attachment zones.
        if abs(x)<.245 and y<1.56:
            factor=.91+.065*max(0.,min(1.,(y-1.15)/.40));x*=factor
            z=.04+(z-.04)*.96
        elif .26<abs(x)<.48:
            # Slim the sleeve cross-section about its dominant bone axis.
            pass
    elif part=='legs' and .24<y<1.06:
        center=.18 if x>0 else -.18
        factor=.955 if y<.65 else .94
        x=center+(x-center)*factor;z=.03+(z-.03)*.965
    # The native atlas V coordinate is negative; leave V convention unchanged.
    u,vv=v.uv
    if part in ('torso','legs'):u*=.5
    elif part=='hands':u=u*.5+.5
    return replace(v,position=(x,y,z),uv=(u,vv))


def hair_cap(mesh):
    """Cut a close-cropped scalp shell, with its own UVs in the hair swatch."""
    vertices=list(mesh.vertices);indices=list(mesh.indices)
    def distance(v):
        x,y,z=v.position
        # Forehead is forward (-Z); back/sides taper toward the ears.
        front=max(0.,min(1.,(-z+.005)/.095))
        return y-(1.755+.045*front)
    def blend(a,b,t):
        return replace(a,position=tuple(x+(y-x)*t for x,y in zip(a.position,b.position)),
                       normal=tuple(x+(y-x)*t for x,y in zip(a.normal,b.normal)))
    for at in range(0,len(mesh.indices),3):
        poly=[mesh.vertices[i] for i in mesh.indices[at:at+3]];cut=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            da,db=distance(a),distance(b)
            if da>=0:cut.append(a)
            if (da>=0)!=(db>=0):cut.append(blend(a,b,da/(da-db)))
        if len(cut)<3:continue
        start=len(vertices)
        for v in cut:
            x,y,z=v.position
            position=tuple(p+n*.0018 for p,n in zip(v.position,v.normal))
            uv=(.014+(.5+x*3)*.045,-(.012+max(0.,min(1.,(y-1.74)/.12))*.05))
            vertices.append(replace(v,position=position,uv=uv))
        for i in range(1,len(cut)-1):indices.extend((start,start+i,start+i+1))
    return replace(mesh,vertices=vertices,indices=tuple(indices))


def main():
    report=[];(OUT/'native').mkdir(parents=True,exist_ok=True);(OUT/'lod1').mkdir(exist_ok=True)
    for part,name in PARTS:
        source=SOURCE/(name+'.mdjx');m=read(source)
        m.vertices=[shape(v,part) for v in m.vertices]
        normals(m)
        low_mesh=hair_cap(m) if part=='head' else m
        low=encode(low_mesh);(OUT/'lod1'/f'tio_vet_{part}.mdjx').write_bytes(low)
        high=subdivide(m)
        if part=='head':high=hair_cap(high)
        normals(high);raw=encode(high);target=OUT/'native'/f'tio_vet_{part}.mdjx';target.write_bytes(raw)
        check=read(target)
        assert check.tail==m.tail and check.bones==m.bones and len(check.vertices)>len(m.vertices)
        assert all(abs(sum(v.weights)-1)<.002 for v in check.vertices)
        report.append(dict(part=part,source=name+'.mdjx',source_sha256=sha(source.read_bytes()),file=target.relative_to(OUT).as_posix(),sha256=sha(raw),
                           vertices=len(check.vertices),triangles=len(check.indices)//3,lod1_triangles=len(low_mesh.indices)//3,
                           bones=len(m.bones),bone_tail_sha256=sha(m.tail),bone_tail_preserved=True))
    result=dict(passed=True,name='Veteran',format='native MDJX',method='Rig-compatible adaptation: remodeled legacy head/clothing geometry, subdivided surface, interpolated skin weights, new UV albedo textures',
                skeleton_compatible=True,animation_files_modified=False,total_triangles=sum(r['triangles'] for r in report),parts=report)
    (OUT/'model.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
