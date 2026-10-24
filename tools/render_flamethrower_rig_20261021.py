"""Reference renders from actual native animation matrices, not game screenshots."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.fix_flamethrower_rig_20261021 import OUT,SOURCE,NAME
from tools.mdjx_mesh import read
from tools.dog_native_animation import animation
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=12;scene.cycles.use_denoising=True
scene.render.resolution_x=640;scene.render.resolution_y=800;scene.render.resolution_percentage=100
scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.11,.13,.16,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.6
materials={}
def material(name):
 if name not in materials:
  m=bpy.data.materials.new(name);m.use_nodes=True;n=m.node_tree.nodes;t=n.new('ShaderNodeTexImage');t.image=bpy.data.images.load(str(SOURCE/'base/models'/name));m.node_tree.links.new(t.outputs['Color'],n.get('Principled BSDF').inputs['Base Color']);materials[name]=m
 return materials[name]
def addmesh(name,tex,clip,frame,fixed=False):
 m=read(OUT/'candidate'/NAME if fixed else SOURCE/'base/models'/(name+'.mdjx'))
 matrices={n:Matrix(x) for n,x in zip(clip['names'],clip['matrices'][frame])}
 points=[]
 for v in m.vertices:
  q=sum((matrices[m.bones[j]['name']]@Vector(v.position)*w for j,w in zip(v.joints,v.weights)),Vector((0,0,0)))
  points.append((q.x,-q.z,q.y))
 data=bpy.data.meshes.new(name);data.from_pydata(points,[],[m.indices[i:i+3] for i in range(0,len(m.indices),3)]);data.update()
 o=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(o);o.data.materials.append(material(tex));uv=data.uv_layers.new(name='Native_UV')
 for poly in data.polygons:
  poly.use_smooth=True
  for li in poly.loop_indices:
   v=m.vertices[data.loops[li].vertex_index];uv.data[li].uv=(v.uv[0],-v.uv[1])
 return o
for name,pos,energy in [('Key',(3,4,5),600),('Fill',(-3,-3,4),400)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=energy;d.size=4;o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=pos;o.rotation_euler=(Vector((0,0,1))-o.location).to_track_quat('-Z','Y').to_euler()
d=bpy.data.cameras.new('Camera');cam=bpy.data.objects.new('Camera',d);bpy.context.collection.objects.link(cam);scene.camera=cam;d.type='ORTHO';d.ortho_scale=2.25
dest=OUT/'reference';dest.mkdir(exist_ok=True)
for gender in ('man','woman'):
 for pose,clipname,frame in [('idle','human_auto_idle' if gender=='man' else 'woman_auto_idle',0),('fire','human_heavy_fire_01',26),('run','human_auto_run',8)]:
  clip=animation(SOURCE/'base/models/anim'/(clipname+'.adjx'));frame=min(frame,clip['frames']-1);objects=[]
  for part in ('head','torso','hands','legs'):
   name='tio_vet_'+part if gender=='man' else 'chr_woman_'+('body' if part=='torso' else part)
   tex=('tio_vet_' if gender=='man' else 'chr_woman_')+('head' if part=='head' else 'body')+'.jpg'
   objects.append(addmesh(name,tex,clip,frame))
  objects.append(addmesh('weapon_flametrower','weapons_pak2.jpg',clip,frame,True))
  for view,location in [('front',(3,5,2.5)),('back',(-3,-5,2.5))]:
   target=Vector((0,0,.95));cam.location=target+Vector(location);cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
   scene.render.filepath=str(dest/(gender+'-'+pose+'-'+view+'.png'));bpy.ops.render.render(write_still=True)
  for o in objects:
   mesh=o.data;bpy.data.objects.remove(o,do_unlink=True);bpy.data.meshes.remove(mesh)
