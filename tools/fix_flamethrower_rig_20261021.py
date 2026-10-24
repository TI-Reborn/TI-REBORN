"""Rebind the legacy two-part flame weapon to the published human skeleton.

The legacy mesh uses unrelated Spine_C/R_Hand bones and ground-level bind
coordinates. Preserve its art, UVs, weights and topology; rebase each rigid
part to a real human bone. No player files or installed clients are touched.
"""
from dataclasses import replace
from pathlib import Path
import hashlib,json,math,struct,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read,encode
from tools.dog_native_animation import animation
OUT=ROOT/'reports/flamethrower-rig-20261021'
SOURCE=OUT/'source';NAME='base/models/weapon_flametrower.mdjx'
sha=lambda b:hashlib.sha256(b).hexdigest()

def mul(a,b):return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
def mv(a,v):return tuple(sum(a[i][j]*v[j] for j in range(3)) for i in range(3))
def add(a,b):return tuple(x+y for x,y in zip(a,b))
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def transpose(a):return tuple(zip(*a))
def transform(m,p):return tuple(sum(m[i][j]*(*p,1)[j] for j in range(4)) for i in range(3))
def bounds(points):return [[f(p[i] for p in points) for i in range(3)] for f in (min,max)]

def fetch():
 manifest=(OUT/'manifest-before.json').read_bytes();rows={r['path']:r for r in json.loads(manifest)['files']}
 names=[NAME,'base/models/weapons_pak2.jpg','base/animation.xml']
 names += ['base/models/tio_vet_'+p+'.mdjx' for p in ('head','torso','hands','legs')]
 names += ['base/models/tio_vet_'+p+'.jpg' for p in ('head','body')]
 names += ['base/models/chr_woman_'+p+'.mdjx' for p in ('head','body','hands','legs')]
 names += ['base/models/chr_woman_'+p+'.jpg' for p in ('head','body')]
 names += [n for n in rows if n.startswith('base/models/anim/') and any(k in n for k in ('human_auto_idle','human_auto_run','human_auto_relax','woman_auto_idle','woman_auto_run','human_heavy_fire','human_heavy_death'))]
 for n in names:
  row=rows[n];path=SOURCE/n
  if path.exists() and sha(path.read_bytes())==row['sha256']:continue
  raw=urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+row['sha256'],timeout=30).read()
  assert sha(raw)==row['sha256'] and len(raw)==row['size']
  path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)

def build():
 original=read(SOURCE/NAME);assert [b['name'] for b in original.bones]==['Spine_C','R_Hand']
 assert all(len(v.joints)==1 and v.weights==(1.,) for v in original.vertices)
 human=read(SOURCE/'base/models/tio_vet_torso.mdjx');bones={b['name']:b for b in human.bones}
 clip=animation(SOURCE/'base/models/anim/human_auto_idle.adjx')
 hand=bones['Bip01 R Hand'];spine=bones['Bip01 Spine1']
 hm=clip['matrices'][0][clip['names'].index(hand['name'])]
 wm=clip['matrices'][0][clip['names'].index('weapon')]
 # The cannon's original forward axis is -X. Native rigid weapons aim -Z.
 # Express that orientation in the right hand's bind space. Its grip remains
 # on the palm through all animation frames rather than following the ground.
 axis=((0.,0.,-1.),(0.,1.,0.),(1.,0.,0.))
 rotation=mul(mul(transpose([r[:3] for r in hm[:3]]),[r[:3] for r in wm[:3]]),axis)
 tank_offset=sub(spine['head'],original.bones[0]['head'])
 vertices=[]
 for v in original.vertices:
  if v.joints==(0,):p=add(v.position,tank_offset);n=v.normal
  else:p=add(hand['head'],mv(rotation,sub(v.position,original.bones[1]['head'])));n=mv(rotation,v.normal)
  vertices.append(replace(v,position=p,normal=n))
 newbones=[dict(spine,parent=0,children=()),dict(hand,parent=1,children=())]
 tail=bytearray()
 for b in newbones:
  name=b['name'].encode();tail+=struct.pack('<II',0,len(name))+name+b'\0'+struct.pack('<6fI',*b['head'],*b['tip'],b['parent'])
 tail+=struct.pack('<24f',*((1,0,0,0,1,0,0,0,1,0,0,0)*2))
 fixed=replace(original,vertices=vertices,bones=newbones,tail=bytes(tail));raw=encode(fixed)
 target=OUT/'candidate'/NAME;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 check=read(target);assert encode(check)==raw
 assert check.indices==original.indices and len(check.vertices)==len(original.vertices)
 assert all((a.uv,a.extra,a.joints,a.weights)==(b.uv,b.extra,b.joints,b.weights) for a,b in zip(original.vertices,check.vertices))
 results=[]
 for path in sorted((SOURCE/'base/models/anim').glob('*.adjx')):
  if not any(n in path.stem for n in ('auto_','heavy_')):continue
  a=animation(path);ids=[a['names'].index(b['name']) for b in check.bones]
  for frame in range(a['frames']):
   matrices=[a['matrices'][frame][i] for i in ids]
   points=[transform(matrices[v.joints[0]],v.position) for v in check.vertices]
   assert all(math.isfinite(x) for p in points for x in p)
   # Each rigid piece must keep its shape and its anchor at the real bone.
   for j,b in enumerate(check.bones):
    old=[v.position for v in check.vertices if v.joints==(j,)];new=[p for p,v in zip(points,check.vertices) if v.joints==(j,)]
    for k in (1,len(old)//2,len(old)-1):
     d=lambda p,q:math.dist(p,q)
     assert abs(d(old[0],old[k])-d(new[0],new[k]))<.00001
   if frame in (0,a['frames']//2,a['frames']-1):results.append(dict(clip=path.stem,frame=frame,bounds=bounds(points)))
 report=dict(passed=True,source_sha256=sha((SOURCE/NAME).read_bytes()),candidate_sha256=sha(raw),
  bones=[b['name'] for b in check.bones],vertices=len(check.vertices),triangles=len(check.indices)//3,
  geometry_rebased=True,uv_weights_topology_preserved=True,tank_offset=tank_offset,barrel_rotation=rotation,
  animation_frames_checked=sum(animation(p)['frames'] for p in (SOURCE/'base/models/anim').glob('*.adjx') if any(n in p.stem for n in ('auto_','heavy_'))),samples=results,
  graphical_validation=False)
 (OUT/'rig-validation.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k!='samples'}))

if __name__=='__main__':fetch();build()
