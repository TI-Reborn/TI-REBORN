"""Author three distinct canine adaptations and import real native animations."""
import bpy,json,math,sys,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read,encode,Mesh,Vertex
from tools.dog_native_animation import skeleton,animation
ASSET=ROOT/'assets/dog-mercenaries-v1';SOURCE=ROOT/'reports/dog-models-20261021/source/base/models'
BREEDS={'doberman':'Доберман','huski':'Хаски','alsatian':'Немецкая овчарка'}
CLIPS=('dog_idle','dog_run','dog_attack','dog_sit','dog_sit_idle','dog_death_v01')
OFFSET=1.01
G=Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,OFFSET),(0,0,0,1)))
def xyz(p):return Vector((p[0],-p[2],p[1]+OFFSET))
def native(p):return (p[0],p[2]-OFFSET,-p[1])
def native_normal(p):return (p[0],p[2],-p[1])
sha=lambda raw:hashlib.sha256(raw).hexdigest()
bones=skeleton(SOURCE/'dog_skeleton.mdjx')
clips={name:animation(SOURCE/'anim'/(name+'.adjx')) for name in CLIPS}

def export_native(obj,original,path):
 mesh=obj.data;uv=mesh.uv_layers.active;ids={b['name']:i for i,b in enumerate(original.bones)};vertices=[];indices=[];lookup={}
 for poly in mesh.polygons:
  assert len(poly.vertices)==3
  for li in poly.loop_indices:
   loop=mesh.loops[li];v=mesh.vertices[loop.vertex_index];tex=uv.data[li].uv;key=(v.index,round(tex.x,7),round(tex.y,7))
   if key not in lookup:
    weights=[(ids[obj.vertex_groups[g.group].name],g.weight) for g in v.groups if g.weight>1e-7]
    weights=sorted(weights,key=lambda x:-x[1])[:4];total=sum(w for j,w in weights);assert total>.99
    n=v.normal.normalized();assert n.length>.99
    vertices.append(Vertex(native(v.co),native_normal(n),(float(tex.x),float(-tex.y)),0,tuple(j for j,w in weights),tuple(w/total for j,w in weights)))
    lookup[key]=len(vertices)-1
   indices.append(lookup[key])
 candidate=Mesh(vertices,tuple(indices),original.bones,original.flag,original.tail);path.parent.mkdir(parents=True,exist_ok=True);raw=encode(candidate);path.write_bytes(raw)
 check=read(path);assert check.tail==original.tail and encode(check)==raw
 return dict(file=path.name,vertices=len(vertices),triangles=len(indices)//3,bones=len(original.bones),sha256=sha(raw),bone_tail_sha256=sha(original.tail))

def make_rig():
 data=bpy.data.armatures.new('TIO_Canine_31');arm=bpy.data.objects.new('Dog_Rig',data);bpy.context.collection.objects.link(arm)
 bpy.context.view_layer.objects.active=arm;arm.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
 for b in bones:
  bone=data.edit_bones.new(b['name']);bone.head=xyz(b['head']);bone.tail=xyz(b['tip'])
  if (bone.tail-bone.head).length<1e-5:bone.tail=bone.head+Vector((0,0,.03))
 for i,b in enumerate(bones):
  if i!=b['parent']:data.edit_bones[b['name']].parent=data.edit_bones[bones[b['parent']]['name']]
 bpy.ops.object.mode_set(mode='OBJECT');arm.select_set(False);arm.show_in_front=True
 return arm

def import_animations(arm):
 arm.animation_data_create();rest={b.name:b.matrix_local.copy() for b in arm.data.bones}
 for name,clip in clips.items():
  assert set(clip['names'])==set(rest)
  action=bpy.data.actions.new(name);action.use_fake_user=True;arm.animation_data.action=action
  for frame,matrices in enumerate(clip['matrices'],1):
   desired={name:G@Matrix(m)@G.inverted()@rest[name] for name,m in zip(clip['names'],matrices)}
   for bone in arm.pose.bones:
    if bone.parent:
     basis=rest[bone.name].inverted()@rest[bone.parent.name]@desired[bone.parent.name].inverted()@desired[bone.name]
    else:basis=rest[bone.name].inverted()@desired[bone.name]
    bone.location,bone.rotation_quaternion,bone.scale=basis.decompose();bone.rotation_mode='QUATERNION'
    for prop in ('location','rotation_quaternion','scale'):bone.keyframe_insert(data_path=prop,frame=frame,group=bone.name)
  for curve in action.fcurves:
   for point in curve.keyframe_points:point.interpolation='LINEAR'
 arm.animation_data.action=None
 for bone in arm.pose.bones:bone.matrix_basis=Matrix.Identity(4)

def build(breed):
 folder=ASSET/breed
 for n in ('textures','native','lod1','preview'): (folder/n).mkdir(parents=True,exist_ok=True)
 bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
 for action in list(bpy.data.actions):bpy.data.actions.remove(action)
 original=read(SOURCE/f'dog_{breed}.mdjx');arm=make_rig()
 mesh=bpy.data.meshes.new('Dog_Breed_Surface');faces=[]
 for at in range(0,len(original.indices),3):
  tri=original.indices[at:at+3];a,b,c=(xyz(original.vertices[i].position) for i in tri)
  if (b-a).cross(c-a).length_squared>1e-16:faces.append(tri)
 mesh.from_pydata([xyz(v.position) for v in original.vertices],[],faces);mesh.update()
 obj=bpy.data.objects.new('Dog_'+breed,mesh);bpy.context.collection.objects.link(obj)
 for b in original.bones:obj.vertex_groups.new(name=b['name'])
 for index,v in enumerate(original.vertices):
  for j,w in zip(v.joints,v.weights):obj.vertex_groups[original.bones[j]['name']].add([index],w,'REPLACE')
 uv=mesh.uv_layers.new(name='Coat_UV')
 for poly in mesh.polygons:
  poly.use_smooth=True
  for li in poly.loop_indices:
   u,v=original.vertices[mesh.loops[li].vertex_index].uv;uv.data[li].uv=(u,-v)
 for vertex,v in zip(mesh.vertices,original.vertices):
  x,y,z=v.position;weights={original.bones[j]['name']:w for j,w in zip(v.joints,v.weights)}
  head=sum(weights.get(n,0) for n in ('Dog_head','Dog_mouth01','Dog_mouth02'))
  tail=sum(weights.get(n,0) for n in ('Bone18','Bone19'))
  body=math.exp(-((z-.04)/.32)**2-((y+.42)/.20)**2)*(1-head)*(1-tail)
  neck=math.exp(-((z+.32)/.16)**2-((y+.24)/.17)**2)
  if breed=='doberman':
   waist=math.exp(-((z-.17)/.13)**2-((y+.48)/.15)**2);x*=1-.10*waist+.025*body
   if head>.5:x*=.96;z-=.012*head*max(0,min(1,(-z-.43)/.20))
   if y>-.12 and z<-.30:y+=.012*head
  elif breed=='huski':
   x*=1+.085*body+.11*neck
   if head>.5:x*=1.045
   if tail>.2:
    x*=1.20;y+=.055*tail
   if y>-.12 and z<-.30:y-=.006*head
  else:
   x*=1+.045*body+.055*neck
   if head>.5: z-=.018*head*max(0,min(1,(-z-.42)/.18));x*=1.015
   if y>-.14 and z<-.30:y+=.017*head
   if tail>.2:x*=1.22
  vertex.co=xyz((x,y,z))
 mesh.update();bpy.context.view_layer.objects.active=obj;obj.select_set(True)
 # Weld positional seams while retaining their per-loop UVs, before smoothing.
 bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.mesh.remove_doubles(threshold=.000001);bpy.ops.object.mode_set(mode='OBJECT')
 low=export_native(obj,original,folder/'lod1'/f'dog_{breed}.mdjx')
 mod=obj.modifiers.new('Breed_Surface_Smoothing','SUBSURF');mod.subdivision_type='CATMULL_CLARK';mod.levels=1;bpy.ops.object.modifier_apply(modifier=mod.name)
 mod=obj.modifiers.new('Native_Triangles','TRIANGULATE');bpy.ops.object.modifier_apply(modifier=mod.name)
 for vertex in obj.data.vertices:
  groups=sorted(((g.group,g.weight) for g in vertex.groups),key=lambda x:-x[1]);total=sum(w for _,w in groups[:4])
  for i,(group,weight) in enumerate(groups):
   if i<4:obj.vertex_groups[group].add([vertex.index],weight/total,'REPLACE')
   else:obj.vertex_groups[group].remove([vertex.index])
 high=export_native(obj,original,folder/'native'/f'dog_{breed}.mdjx')
 mod=obj.modifiers.new('Canine_Armature','ARMATURE');mod.object=arm;obj.parent=arm
 tex=bpy.data.images.load(str(folder/'generated/coat-master.png'),check_existing=False);tex.name=breed+'_Coat_2048';tex.scale(2048,2048);tex.file_format='JPEG';tex.filepath_raw=str(folder/'textures'/f'dog_{breed}.jpg');tex.save();tex.pack()
 mat=bpy.data.materials.new(breed+'_Fur');mat.use_nodes=True
 node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=tex;shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Roughness'].default_value=.87
 mat.node_tree.links.new(node.outputs['Color'],shader.inputs['Base Color']);obj.data.materials.append(mat)
 import_animations(arm)
 scene=bpy.context.scene;scene.render.fps=30;scene.frame_start=1;scene.frame_end=max(c['frames'] for c in clips.values());scene.world.use_nodes=True
 scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.055,.065,.075,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.5
 bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.013));floor=bpy.context.object;floor.name='Preview_Floor';fm=bpy.data.materials.new('Preview_Backdrop');fm.diffuse_color=(.055,.065,.075,1);floor.data.materials.append(fm)
 def area(name,location,energy,color,size):
  data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.color=color;data.shape='DISK';data.size=size
  light=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(light);light.location=location;light.rotation_euler=(Vector((0,0,.5))-light.location).to_track_quat('-Z','Y').to_euler()
 area('Key',(-3,4,4),450,(1,.94,.86),3);area('Fill',(3,1,2),300,(.79,.87,1),3);area('Rim',(0,-3,3),450,(1,.85,.69),3)
 camdata=bpy.data.cameras.new('Preview_Camera');cam=bpy.data.objects.new('Preview_Camera',camdata);bpy.context.collection.objects.link(cam);scene.camera=cam
 camdata.type='ORTHO';camdata.ortho_scale=1.8;cam.location=(2.5,4,1.9);cam.rotation_euler=(Vector((0,0,.52))-cam.location).to_track_quat('-Z','Y').to_euler()
 scene.render.engine='CYCLES';scene.cycles.samples=28;scene.cycles.use_denoising=True;scene.view_settings.view_transform='AgX'
 scene.render.resolution_x=1000;scene.render.resolution_y=850;scene.render.resolution_percentage=100
 arm.animation_data.action=bpy.data.actions['dog_idle'];scene.frame_set(1)
 scene.render.filepath=str(folder/'preview/three-quarter.png');bpy.ops.render.render(write_still=True)
 arm.animation_data.action=None
 for bone in arm.pose.bones:bone.matrix_basis=Matrix.Identity(4)
 scene.frame_set(1);bpy.context.view_layer.update()
 bpy.ops.object.select_all(action='DESELECT');arm.select_set(True);obj.select_set(True);bpy.context.view_layer.objects.active=arm
 bpy.ops.wm.save_as_mainfile(filepath=str(folder/f'{breed}.blend'))
 bpy.ops.export_scene.gltf(filepath=str(folder/f'{breed}.glb'),export_format='GLB',use_selection=True,export_animations=True,export_animation_mode='ACTIONS',export_skins=True,export_yup=True)
 result=dict(passed=True,breed=breed,name=BREEDS[breed],authored_in='Blender 4.5.0',rig_bones=len(bones),deform_bones=len(original.bones),
  method='Breed-specific geometry remodel and smoothing of compatible legacy topology in Blender; new imagegen UV albedo; original bind data preserved',
  native=high,lod1=low,source_sha256=sha((SOURCE/f'dog_{breed}.mdjx').read_bytes()),texture_sha256=sha((folder/'textures'/f'dog_{breed}.jpg').read_bytes()),
  animations={n:dict(frames=c['frames'],fps=c['fps'],source_sha256=sha((SOURCE/'anim'/(n+'.adjx')).read_bytes())) for n,c in clips.items()},
  animation_source_files_modified=False)
 (folder/'model.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
 return result

results=[build(breed) for breed in BREEDS]
(ASSET/'catalog.json').write_text(json.dumps(dict(passed=True,breeds=results),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
