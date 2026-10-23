"""Compare imported Blender skinning against original ADJX matrices."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Matrix,Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.dog_native_animation import animation
ASSET=ROOT/'assets/dog-mercenaries-v1';SOURCE=ROOT/'reports/dog-models-20261021/source/base/models'
CLIPS=('dog_idle','dog_run','dog_attack','dog_sit','dog_sit_idle','dog_death_v01')
G=Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,1.01),(0,0,0,1)))
for breed in ('doberman','huski','alsatian'):
 folder=ASSET/breed;bpy.ops.wm.open_mainfile(filepath=str(folder/(breed+'.blend')))
 arm=bpy.data.objects['Dog_Rig'];obj=bpy.data.objects['Dog_'+breed]
 assert len(arm.data.bones)==31 and obj.parent==arm and obj.data.uv_layers.active
 assert any(m.type=='ARMATURE' and m.object==arm for m in obj.modifiers)
 assert all(0<len(v.groups)<=4 and abs(sum(g.weight for g in v.groups)-1)<.002 for v in obj.data.vertices)
 assert all(image.packed_file for image in bpy.data.images if image.name.endswith('_Coat_2048'))
 sample=list(range(0,len(obj.data.vertices),max(1,len(obj.data.vertices)//250)))
 cases=[];error_max=0
 for name in CLIPS:
  clip=animation(SOURCE/'anim'/(name+'.adjx'));arm.animation_data.action=bpy.data.actions[name]
  frames=sorted({1,clip['frames'],*range(1,clip['frames']+1,max(1,(clip['frames']-1)//6))})
  for frame in frames:
   bpy.context.scene.frame_set(frame);deps=bpy.context.evaluated_depsgraph_get();evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh()
   coords=[evaluated.matrix_world@v.co for v in mesh.vertices]
   assert len(coords)==len(obj.data.vertices) and all(math.isfinite(c) for v in coords for c in v)
   delta={n:G@Matrix(m)@G.inverted() for n,m in zip(clip['names'],clip['matrices'][frame-1])}
   error=0
   for i in sample:
    vertex=obj.data.vertices[i];expected=Vector((0,0,0))
    for group in vertex.groups:expected+=(delta[obj.vertex_groups[group.group].name]@vertex.co)*group.weight
    error=max(error,(expected-coords[i]).length)
   assert error<.0003,(breed,name,frame,error)
   error_max=max(error_max,error)
   bounds=[(min(v[i] for v in coords),max(v[i] for v in coords)) for i in range(3)]
   assert all(b-a<3.5 for a,b in bounds)
   cases.append(dict(clip=name,frame=frame,skinning_error_m=error,bounds=bounds));evaluated.to_mesh_clear()
 scene=bpy.context.scene;scene.cycles.samples=24;scene.render.resolution_x=1000;scene.render.resolution_y=850
 for name,clip,frame,location in [('run','dog_run',8,(3.5,1,1.4)),('bite','dog_attack',26,(3.2,2.5,1.5)),('sit','dog_sit',41,(2.5,4,1.9))]:
  arm.animation_data.action=bpy.data.actions[clip];scene.frame_set(frame)
  cam=scene.camera;cam.location=location;cam.rotation_euler=(Vector((0,0,.52))-cam.location).to_track_quat('-Z','Y').to_euler()
  scene.render.filepath=str(folder/'preview'/(name+'.png'));bpy.ops.render.render(write_still=True)
 report=dict(passed=True,rig_bones=31,deform_bones=26,maximum_influences=4,weight_sums_normalized=True,
  original_native_clips_imported=list(CLIPS),sampled_poses=len(cases),maximum_native_skinning_error_m=error_max,comparison_vertices=len(sample),cases=cases,
  limitation='Six original animation clips compared in Blender; separate native graphical verification is required. Other native clips unchanged.')
 (folder/'rig-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(breed=breed,passed=True,poses=len(cases),max_error=error_max)))
