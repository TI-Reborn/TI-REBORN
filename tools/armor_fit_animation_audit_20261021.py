"""Numerical native-skinning checks. These do not certify absence of clipping."""
import sys,json,math
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read
from tools.dog_native_animation import animation
OUT=ROOT/'reports/armor-fit-20261021';SOURCE=OUT/'source/base/models';CAT=json.loads((OUT/'catalog.json').read_text(encoding='utf-8'));results=[]
for resource in range(1,7):
 names={b['model'] for c in CAT['cases'] if c['resource']==resource for b in c['bindings']}
 names.update(p[0] for p in CAT['base_parts'][str(resource)])
 clipnames=['woman_gun_idle','human_gun_run'] if resource==2 else ['dog_idle','dog_run'] if resource in (3,4,5) else ['freakminer_hammer_idle'] if resource==6 else ['human_gun_idle','human_gun_run']
 clips={n:animation(SOURCE/'anim'/(n+'.adjx')) for n in clipnames}
 for name in sorted(names):
  m=read(SOURCE/(name+'.mdjx'));p=np.array([(*v.position,1) for v in m.vertices]);weights=np.zeros((len(p),8));joints=np.zeros((len(p),8),dtype=int)
  for i,v in enumerate(m.vertices):weights[i,:len(v.weights)]=v.weights;joints[i,:len(v.joints)]=v.joints
  assert np.isfinite(p).all() and np.isfinite(weights).all();assert np.abs(weights.sum(axis=1)-1).max()<.002
  checks=[]
  for clipname,c in clips.items():
   boneids={n:i for i,n in enumerate(c['names'])};assert all(b['name'] in boneids for b in m.bones),(name,clipname)
   ids=np.array([boneids[b['name']] for b in m.bones]);sample=sorted({0,c['frames']//4,c['frames']//2,c['frames']*3//4,c['frames']-1});maximum=0
   for frame in sample:
    matrices=np.array(c['matrices'][frame])[ids];q=np.zeros((len(p),4))
    for influence in range(8):q+=np.einsum('nij,nj->ni',matrices[joints[:,influence]],p)*weights[:,influence,None]
    assert np.isfinite(q).all() and np.abs(q[:,3]-1).max()<.002
    span=float(np.ptp(q[:,:3],axis=0).max());assert span<5,(name,clipname,frame,span);maximum=max(maximum,span)
   checks.append(dict(clip=clipname,sampled_frames=sample,max_mesh_span_m=maximum,missing_bones=0,finite_positions=True))
  results.append(dict(resource=resource,model=name,bones=len(m.bones),vertices=len(p),clips=checks))
report=dict(passed=True,release=CAT['version'],class_mesh_bindings=len(results),sampled_mesh_poses=sum(len(c['sampled_frames']) for r in results for c in r['clips']),checks=results,limitations='Finite skinning and matching bones do not prove absence of mesh intersection. Female running uses the shared human clip for compatibility probing; actual battle rendering is not certified.')
(OUT/'animation-structure-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='checks'}))
