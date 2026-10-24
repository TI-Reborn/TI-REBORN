"""Compare all miner surfaces with original ADJX skinning in 9 clips."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Matrix,Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.dog_native_animation import animation
FOLDER=ROOT/'assets/miner-colossus-v1';SOURCE=ROOT/'reports/miner-model-20261021/source/base/models'
model=json.loads((FOLDER/'model.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(FOLDER/'colossus.blend'))
G=Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,.94),(0,0,0,1)))
arm=bpy.data.objects['Colossus_Rig'];assert len(arm.data.bones)==50
for name in ('Base','Medium_Armor','Heavy_Armor'):bpy.data.collections[name].hide_viewport=False
objects=[bpy.data.objects[p['part']] for p in model['parts']]
for obj in objects:
 assert obj.parent==arm and obj.data.uv_layers.active and any(m.type=='ARMATURE' and m.object==arm for m in obj.modifiers)
 assert all(0<len(v.groups)<=4 and abs(sum(g.weight for g in v.groups)-1)<.002 for v in obj.data.vertices)
assert bpy.data.images['Colossus_Albedo_2048'].packed_file
samples={o.name:list(range(0,len(o.data.vertices),max(1,len(o.data.vertices)//150))) for o in objects}
cases=[];error_max=0
for name in model['animations']:
 clip=animation(SOURCE/'anim'/(name+'.adjx'));arm.animation_data.action=bpy.data.actions[name]
 frames=sorted({1,clip['frames'],*range(1,clip['frames']+1,max(1,(clip['frames']-1)//6))})
 for frame in frames:
  bpy.context.scene.frame_set(frame);deps=bpy.context.evaluated_depsgraph_get()
  delta={n:G@Matrix(m)@G.inverted() for n,m in zip(clip['names'],clip['matrices'][frame-1])};error=0;coords=[]
  for obj in objects:
   evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh();positions=[evaluated.matrix_world@v.co for v in mesh.vertices]
   assert len(positions)==len(obj.data.vertices) and all(math.isfinite(c) for v in positions for c in v)
   for i in samples[obj.name]:
    vertex=obj.data.vertices[i];expected=Vector((0,0,0))
    for group in vertex.groups:expected+=(delta[obj.vertex_groups[group.group].name]@vertex.co)*group.weight
    error=max(error,(expected-positions[i]).length)
   coords.extend(positions);evaluated.to_mesh_clear()
  assert error<.0003,(name,frame,error)
  bounds=[(min(v[i] for v in coords),max(v[i] for v in coords)) for i in range(3)];assert all(b-a<4 for a,b in bounds)
  error_max=max(error_max,error);cases.append(dict(clip=name,frame=frame,skinning_error_m=error,bounds=bounds))
scene=bpy.context.scene;scene.cycles.samples=28
for name,kind,clip,frame in [('base-walk','Base','freakminer_empty_walk',16),('medium-hammer','Medium_Armor','freakminer_hammer_idle',1),('heavy-nailgun','Heavy_Armor','freakminer_nailgun_idle',1)]:
 for col in ('Base','Medium_Armor','Heavy_Armor'):bpy.data.collections[col].hide_render=col!=kind
 arm.animation_data.action=bpy.data.actions[clip];scene.frame_set(frame);scene.render.filepath=str(FOLDER/'preview'/(name+'.png'));bpy.ops.render.render(write_still=True)
report=dict(passed=True,rig_bones=50,parts=7,maximum_influences=4,weight_sums_normalized=True,imported_original_clips=list(model['animations']),
 sampled_poses=len(cases),maximum_native_skinning_error_m=error_max,comparison_vertices=sum(map(len,samples.values())),cases=cases,
 limitation='Nine original clips compared in Blender for all seven surfaces. Native graphical loadout QA is recorded separately; not a full battle regression.')
(FOLDER/'rig-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(passed=True,poses=len(cases),max_error=error_max)))
