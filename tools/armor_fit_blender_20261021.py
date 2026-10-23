"""Reconstruct published armor/body replacements and pose native skinning in Blender.

These are reference renders, not a replacement for observations in the native client.
No game resources are modified. Every one of 110 item/class bindings is rendered.
"""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Matrix,Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read
from tools.miner_native_mesh import compatible
from tools.dog_native_animation import animation
OUT=ROOT/'reports/armor-fit-20261021';SOURCE=OUT/'source/base/models';CAT=json.loads((OUT/'catalog.json').read_text(encoding='utf-8'))
FRONT='--front' in sys.argv
FIXED='--fixed' in sys.argv
VETERAN='--veteran' in sys.argv
if VETERAN:CAT['cases']=[c for c in CAT['cases'] if c['resource']==1]
if FIXED or VETERAN:
 if VETERAN:
  CAT['cases']=[{**c,'bindings':c['bindings']+[dict(model='chr_man_legs',texture='chr_man_body.jpg')]} if c['id']==206 else c for c in CAT['cases']]
 else:
  CAT['cases']=[{**c,'bindings':c['bindings']+[dict(model='chr_man_legs' if c['resource']==1 else 'chr_woman_legs',texture='chr_man_body.jpg' if c['resource']==1 else 'chr_woman_body.jpg')]} for c in CAT['cases'] if c['id']==206]
DEST=OUT/('renders-veteran' if VETERAN else 'renders-fixed' if FIXED else 'renders-front' if FRONT else 'renders');DEST.mkdir(exist_ok=True)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
cache={};materials={};clips={};results=[]
def mesh(name):
 if name not in cache:
  paths={'chr_man_head':'tio_vet_head','chr_man_body':'tio_vet_torso','chr_man_hands':'tio_vet_hands','chr_man_legs':'tio_vet_legs'}
  source=ROOT/'assets/fighter-model-v1/native'/(paths[name]+'.mdjx') if VETERAN and name in paths else SOURCE/(name+'.mdjx')
  try:cache[name]=read(source)
  except AssertionError:
   assert name=='freakminer_legs';cache[name]=compatible(SOURCE/(name+'.mdjx'))
 return cache[name]
def clip(name):
 if name not in clips:clips[name]=animation(SOURCE/'anim'/(name+'.adjx'))
 return clips[name]
def material(name):
 if name not in materials:
  mat=bpy.data.materials.new(name);mat.use_nodes=True;n=mat.node_tree.nodes;shader=n.get('Principled BSDF');shader.inputs['Roughness'].default_value=.85
  source=ROOT/'assets/fighter-model-v1/textures'/('tio_vet_head.jpg' if 'head' in name else 'tio_vet_body.jpg') if VETERAN and name in ('chr_man_head.jpg','chr_man_body.jpg') else SOURCE/name
  tex=n.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(source),check_existing=True);mat.node_tree.links.new(tex.outputs['Color'],shader.inputs['Base Color'])
  mat.node_tree.links.new(tex.outputs['Color'],shader.inputs['Emission Color']);shader.inputs['Emission Strength'].default_value=.3;materials[name]=mat
 return materials[name]
def posed_positions(m,c,frame,offset):
 mats={n:Matrix(mat) for n,mat in zip(c['names'],c['matrices'][frame])};assert {b['name'] for b in m.bones}<=set(mats)
 out=[]
 for v in m.vertices:
  p=Vector((0,0,0))
  for j,w in zip(v.joints,v.weights):
   if w:p+=(mats[m.bones[j]['name']]@Vector(v.position))*w
  assert all(math.isfinite(x) for x in p)
  out.append((p.x,-p.z,p.y+offset))
 return out
def object_(name,texture,c,frame,offset):
 original=mesh(name);data=bpy.data.meshes.new(name);data.from_pydata(posed_positions(original,c,frame,offset),[],[original.indices[i:i+3] for i in range(0,len(original.indices),3)]);data.update()
 obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.data.materials.append(material(texture));uv=data.uv_layers.new(name='Native_UV')
 for p in data.polygons:
  p.use_smooth=True
  for li in p.loop_indices:
   u,v=original.vertices[data.loops[li].vertex_index].uv;uv.data[li].uv=(u,-v)
 return obj
def composition(case):
 r=case['resource'];covers=set(case['covers']);base=[]
 # Native chest meshes include their own arms/hands. Original default hands are
 # retained only with the unarmored chest, as observed on the native exosuit.
 for model,texture,slot in CAT['base_parts'][str(r)]:
  if slot in covers or (slot=='hands' and 'chest' in covers):continue
  base.append((model,texture))
 return base+[(b['model'],b['texture']) for b in case['bindings']]
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.use_denoising=True
scene.render.resolution_x=280;scene.render.resolution_y=340;scene.render.resolution_percentage=100
scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.06,.075,.09,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.7
scene.view_settings.view_transform='AgX'
def area(name,pos,energy):
 d=bpy.data.lights.new(name,'AREA');d.energy=energy;d.size=4;o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=pos;o.rotation_euler=(Vector((0,0,1))-o.location).to_track_quat('-Z','Y').to_euler()
area('Key',(3,-4,5),400);area('Fill',(-3,-1,3),250)
camdata=bpy.data.cameras.new('Audit_Camera');cam=bpy.data.objects.new('Audit_Camera',camdata);bpy.context.collection.objects.link(cam);scene.camera=cam;camdata.type='ORTHO'
for index,case in enumerate(CAT['cases']):
 r=case['resource'];name='woman_gun_idle' if r==2 else 'dog_idle' if r in (3,4,5) else 'freakminer_hammer_idle' if r==6 else 'human_gun_idle';c=clip(name);offset=1.01 if r in (3,4,5) else .94 if r==6 else 0
 objs=[object_(m,t,c,0,offset) for m,t in composition(case)]
 bounds=[Vector(v.co) for o in objs for v in o.data.vertices];lo=Vector(tuple(min(p[a] for p in bounds) for a in range(3)));hi=Vector(tuple(max(p[a] for p in bounds) for a in range(3)));center=(lo+hi)/2
 camdata.ortho_scale=max(hi.z-lo.z,(hi.x-lo.x)*1.4,(hi.y-lo.y)*1.25)*1.18
 cam.location=center+Vector((3,5 if FRONT else -5,1.5));cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
 filename=f"r{r}-{case['id']}.png";scene.render.filepath=str(DEST/filename);bpy.ops.render.render(write_still=True)
 results.append(dict(resource=r,item=case['id'],name=case['name'],render=filename,parts=[o.name for o in objs],bounds=[list(lo),list(hi)]))
 for o in objs:
  d=o.data;bpy.data.objects.remove(o,do_unlink=True);bpy.data.meshes.remove(d)
 print('ARMOR_CASE',index+1,len(CAT['cases']),filename,flush=True)
(OUT/('blender-reference-veteran.json' if VETERAN else 'blender-reference-fixed.json' if FIXED else 'blender-reference-front.json' if FRONT else 'blender-reference-renders.json')).write_text(json.dumps(dict(passed=True,release='unpublished-veteran' if VETERAN else '2026.10.21.4' if FIXED else CAT['version'],cases=results,method='Native MDJX and UV textures, native ADJX matrices, Blender reference composition; not native-engine screenshot'),indent=2),encoding='utf-8')
