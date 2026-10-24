"""Author the female adaptation in Blender, then export compatible native MDJX."""
import bpy,json,math,sys
from dataclasses import replace
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read,encode,Vertex,Mesh
FOLDER=ROOT/'assets/female-fighter-v1';SOURCE=ROOT/'reports/female-fighter-20261021/source/base/models'
PARTS={'head':'chr_woman_head','torso':'woman_cloth_sc01_chest','legs':'woman_cloth_sc01_legs','hands':'chr_woman_hands','hair':'hair_woman_03'}
def xyz(p):return Vector((p[0],-p[2],p[1]))
def native(p):return (p[0],p[2],-p[1])
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
for name in ('native','lod1','preview'): (FOLDER/name).mkdir(parents=True,exist_ok=True)
source={k:read(SOURCE/(v+'.mdjx')) for k,v in PARTS.items()}
definitions={};parents={}
for m in source.values():
 for i,b in enumerate(m.bones):
  definitions.setdefault(b['name'],b)
  if i!=b['parent']:parents.setdefault(b['name'],m.bones[b['parent']]['name'])
arm_data=bpy.data.armatures.new('TIO_Female_Compatible');arm=bpy.data.objects.new('Scout_Rig',arm_data);bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active=arm;arm.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
for name,b in definitions.items():
 bone=arm_data.edit_bones.new(name);bone.head=xyz(b['head']);bone.tail=xyz(b['tip'])
 if (bone.tail-bone.head).length<.0001:bone.tail=bone.head+Vector((0,0,.05))
for name,parent in parents.items():
 if parent in arm_data.edit_bones and name!=parent:arm_data.edit_bones[name].parent=arm_data.edit_bones[parent]
bpy.ops.object.mode_set(mode='OBJECT');arm.select_set(False)
materials={}
for key in ('head','body','hair'):
 mat=bpy.data.materials.new('Scout_'+key);mat.use_nodes=True
 node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=bpy.data.images.load(str(FOLDER/'textures'/f'tio_scout_{key}.jpg'));node.image.pack()
 shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Roughness'].default_value=.83
 mat.node_tree.links.new(node.outputs['Color'],shader.inputs['Base Color']);materials[key]=mat
objects=[];report=[]

def export_native(obj,original,part,subfolder):
 mesh=obj.data;uv=mesh.uv_layers.active;ids={b['name']:i for i,b in enumerate(original.bones)}
 vertices=[];indices=[];lookup={}
 # Preserve UV seams explicitly; shared Blender vertices can have per-loop UV.
 for poly in mesh.polygons:
  assert len(poly.vertices)==3
  for li in poly.loop_indices:
   loop=mesh.loops[li];v=mesh.vertices[loop.vertex_index];tex=uv.data[li].uv
   key=(v.index,round(tex.x,7),round(tex.y,7))
   if key not in lookup:
    weights=[(ids[obj.vertex_groups[g.group].name],g.weight) for g in v.groups if g.weight>1e-7]
    weights=sorted(weights,key=lambda x:-x[1])[:4];total=sum(w for j,w in weights);assert total>.99
    # Blender V=-native V; retain native repeat coordinates for hair.
    vertices.append(Vertex(native(v.co),native(v.normal),(float(tex.x),float(-tex.y)),0,tuple(j for j,w in weights),tuple(w/total for j,w in weights)))
    lookup[key]=len(vertices)-1
   indices.append(lookup[key])
 candidate=Mesh(vertices,tuple(indices),original.bones,original.flag,original.tail)
 path=FOLDER/subfolder/f'tio_scout_{part}.mdjx';path.write_bytes(encode(candidate));check=read(path)
 assert check.tail==original.tail and len(check.indices)//3==len(mesh.polygons)
 return dict(part=part,file=path.relative_to(FOLDER).as_posix(),vertices=len(check.vertices),triangles=len(check.indices)//3,bones=len(check.bones),bind_tail_preserved=True)

for part,m in source.items():
 mesh=bpy.data.meshes.new('Scout_'+part)
 faces=[]
 for at in range(0,len(m.indices),3):
  tri=m.indices[at:at+3]
  # Retain the original arms beneath sleeves so wrists stay connected in poses.
  a,b,c=(xyz(m.vertices[i].position) for i in tri)
  if (b-a).cross(c-a).length_squared<1e-16:continue
  faces.append(tri)
 mesh.from_pydata([xyz(v.position) for v in m.vertices],[],faces);mesh.update()
 obj=bpy.data.objects.new('Scout_'+part,mesh);bpy.context.collection.objects.link(obj)
 for b in m.bones:obj.vertex_groups.new(name=b['name'])
 for index,v in enumerate(m.vertices):
  for joint,weight in zip(v.joints,v.weights):obj.vertex_groups[m.bones[joint]['name']].add([index],weight,'REPLACE')
 uv=mesh.uv_layers.new(name='UVMap')
 for poly in mesh.polygons:
  poly.use_smooth=True
  for li in poly.loop_indices:
   v=m.vertices[mesh.loops[li].vertex_index];u,vv=v.uv
   if part in ('torso','legs'):u=min(.9995,max(.0005,u))*.5
   elif part=='hands':u=u*.5+.5
   uv.data[li].uv=(u,-vv)
 # Geometry changes are authored on actual Blender mesh data.
 for vertex in mesh.vertices:
  x,y,z=native(vertex.co)
  if part=='head':
   t=max(0.,min(1.,(y-1.55)/.256));jaw=math.exp(-((t-.27)/.21)**2)
   x*=.97-.055*jaw
   if z<-.025:
    cheek=math.exp(-((abs(x)-.055)/.025)**2-((y-1.69)/.035)**2)
    z-=.0035*cheek
   if y>1.57:y=1.57+(y-1.57)*.985
  elif part=='torso' and abs(x)<.20 and 1.1<y<1.46:
   # Practical slightly straighter jacket silhouette around the waist.
   waist=math.exp(-((y-1.19)/.12)**2);x*=1+.035*waist
  elif part=='legs' and .20<y<.90:
   center=.14 if x>=0 else -.14;x=center+(x-center)*.975
  elif part=='hair':
   x*=.97
   if y<1.60:y=1.60+(y-1.60)*.80
  vertex.co=xyz((x,y,z))
 mesh.update()
 obj.data.materials.append(materials['head' if part=='head' else 'hair' if part=='hair' else 'body'])
 bpy.context.view_layer.objects.active=obj;obj.select_set(True)
 # Triangulated native LOD before subdivision.
 low=export_native(obj,m,part,'lod1')
 modifier=obj.modifiers.new('Editable_Surface_Density','SUBSURF');modifier.subdivision_type='SIMPLE';modifier.levels=1
 bpy.ops.object.modifier_apply(modifier=modifier.name)
 tri=obj.modifiers.new('Native_Triangles','TRIANGULATE');bpy.ops.object.modifier_apply(modifier=tri.name)
 # Match the native four-influence skinning limit in the editable source too.
 for vertex in obj.data.vertices:
  groups=sorted(((g.group,g.weight) for g in vertex.groups),key=lambda x:-x[1])
  total=sum(w for _,w in groups[:4])
  for group,weight in groups:
   if (group,weight) in groups[:4]:obj.vertex_groups[group].add([vertex.index],weight/total,'REPLACE')
   else:obj.vertex_groups[group].remove([vertex.index])
 rec=export_native(obj,m,part,'native');rec.update(source=PARTS[part]+'.mdjx',lod1_triangles=low['triangles']);report.append(rec)
 modifier=obj.modifiers.new('TIO_Female_Skeleton','ARMATURE');modifier.object=arm
 obj.parent=arm;obj.select_set(False);objects.append(obj)
arm.animation_data_create()
for name in ('Scout_Preview_Idle','Scout_Preview_Walk'):
 action=bpy.data.actions.new(name);action.use_fake_user=True;arm.animation_data.action=action
 for frame in (1,9,17,25,33):
  phase=(frame-1)/32*math.tau
  for bone_name in ('Bip01 Spine1','Bip01 L UpperArm','Bip01 R UpperArm','Bip01 L Thigh','Bip01 R Thigh'):
   if bone_name not in arm.pose.bones:continue
   b=arm.pose.bones[bone_name];b.rotation_mode='XYZ';amount=.01 if name.endswith('Idle') else .23
   if bone_name=='Bip01 Spine1':amount=.012
   if 'R ' in bone_name:amount=-amount
   b.rotation_euler=(math.sin(phase)*amount,0,0);b.keyframe_insert(data_path='rotation_euler',frame=frame,group=bone_name)
arm.animation_data.action=None
for b in arm.pose.bones:b.rotation_euler=(0,0,0)
scene=bpy.context.scene;scene.frame_start=1;scene.frame_end=33;scene.render.fps=24
scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.055,.068,.085,1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value=.4
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.02));floor=bpy.context.object;floor.name='Preview_Floor'
mat=bpy.data.materials.new('Preview_Backdrop');mat.diffuse_color=(.055,.068,.08,1);floor.data.materials.append(mat)
def area(name,location,energy,color,size):
 data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.color=color;data.shape='DISK';data.size=size
 obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.location=location
 obj.rotation_euler=(Vector((0,0,1))-obj.location).to_track_quat('-Z','Y').to_euler()
area('Key',(-3,4,4.5),500,(1,.92,.83),4);area('Fill',(3,2,3),260,(.78,.86,1),3);area('Rim',(0,-3,3.2),550,(1,.78,.55),3)
camdata=bpy.data.cameras.new('Preview_Camera');cam=bpy.data.objects.new('Preview_Camera',camdata);bpy.context.collection.objects.link(cam)
scene.camera=cam;camdata.type='ORTHO';camdata.ortho_scale=2.1;cam.location=(2.4,5,2.2);cam.rotation_euler=(Vector((0,0,.92))-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.engine='CYCLES';scene.cycles.samples=28;scene.cycles.use_denoising=True
scene.render.resolution_x=900;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
scene.view_settings.view_transform='AgX';scene.render.filepath=str(FOLDER/'preview/three-quarter.png');bpy.ops.render.render(write_still=True)
bpy.ops.object.select_all(action='DESELECT');arm.select_set(True)
for o in objects:o.select_set(True)
bpy.context.view_layer.objects.active=arm
bpy.ops.wm.save_as_mainfile(filepath=str(FOLDER/'scout.blend'))
bpy.ops.export_scene.gltf(filepath=str(FOLDER/'scout.glb'),export_format='GLB',use_selection=True,export_animations=True,export_animation_mode='ACTIONS',export_skins=True,export_yup=True)
result=dict(passed=True,name='Scout',authored_in='Blender 4.5.0',method='Editable adaptation of compatible female topology; geometry, UV, subdivision, weights and native export authored in Blender',
            rig_bones=len(definitions),parts=report,total_triangles=sum(r['triangles'] for r in report),animation_files_modified=False,
            native_default_parts=['head','torso','legs','hands'],hair='Editable optional mesh; native game hairstyles/customization remain authoritative')
(FOLDER/'model.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
