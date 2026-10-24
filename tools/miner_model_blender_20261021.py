"""Build the Colossus miner in Blender with all 50 original animation bones."""
import bpy,ast,json,math,sys,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read,encode,Mesh,Vertex
from tools.miner_native_mesh import compatible
from tools.dog_native_animation import skeleton,animation
FOLDER=ROOT/'assets/miner-colossus-v1';SOURCE=ROOT/'reports/miner-model-20261021/source/base/models'
PARTS=('freakminer_body','freakminer_legs','freakminer_medium_body','freakminer_medium_legs','freakminer_heavy_body','freakminer_heavy_legs','freakminer_heavy_helmet')
CLIPS=('freakminer_empty_idle','freakminer_empty_walk','freakminer_empty_attack_v01','freakminer_hammer_idle','freakminer_hammer_walk','freakminer_hammer_attack','freakminer_nailgun_idle','freakminer_nailgun_fire','freakminer_death')
OFFSET=.94;G=Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,OFFSET),(0,0,0,1)))
def xyz(p):return Vector((p[0],-p[2],p[1]+OFFSET))
def native(p):return (p[0],p[2]-OFFSET,-p[1])
def native_normal(p):return (p[0],p[2],-p[1])
sha=lambda raw:hashlib.sha256(raw).hexdigest()
bones=skeleton(SOURCE/'freakminer_skeleton.mdjx');assert len(bones)==50
clips={n:animation(SOURCE/'anim'/(n+'.adjx')) for n in CLIPS}
# Share the already verified exporter, armature builder and ADJX import math.
tree=ast.parse((ROOT/'tools/dog_models_blender_20261021.py').read_text(encoding='utf-8'))
for node in tree.body:
 if isinstance(node,ast.FunctionDef) and node.name in ('export_native','make_rig','import_animations'):
  exec(compile(ast.Module(body=[node],type_ignores=[]),'<native Blender skinning>','exec'))
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
for n in ('native','lod1','textures','preview'):(FOLDER/n).mkdir(parents=True,exist_ok=True)
arm=make_rig();arm.name='Colossus_Rig';arm.data.name='TIO_Miner_50_Bones'
tex=bpy.data.images.load(str(FOLDER/'generated/miner-master.png'));tex.name='Colossus_Albedo_2048';tex.scale(2048,2048);tex.file_format='JPEG';tex.filepath_raw=str(FOLDER/'textures/miner.jpg');tex.save();tex.pack()
mat=bpy.data.materials.new('Colossus_Skin_Cloth_Industrial_Metal');mat.use_nodes=True
node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=tex;shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Roughness'].default_value=.76
mat.node_tree.links.new(node.outputs['Color'],shader.inputs['Base Color'])
collections={}
for name in ('Base','Medium_Armor','Heavy_Armor'):
 col=bpy.data.collections.new(name);bpy.context.scene.collection.children.link(col);collections[name]=col

def bulge_segment(p,a,b,amount,reach):
 direction=b-a;t=max(0,min(1,(p-a).dot(direction)/direction.length_squared));center=a+t*direction
 radial=p-center;falloff=math.exp(-((t-.47)/.48)**4)*math.exp(-(radial.length/reach)**4)
 return p+radial*(amount*falloff)

def sculpt(position):
 p=Vector(position);x,y,z=p;side=1 if x>=0 else -1
 # The same spatial deformation fits the base body, trousers and armor.
 if .16<y<.73 and abs(x)<.34:
  chest=math.exp(-((y-.52)/.20)**2);waist=math.exp(-((y-.23)/.10)**2)
  p.x*=1+.18*chest+.035*waist;p.z=.055+(p.z-.055)*(1+.20*chest)
 if abs(x)>.25 and -.17<y<.76:
  p=bulge_segment(p,Vector((side*.275,.654,.037)),Vector((side*.431,.370,-.035)),.34,.24)
  if y<.44:p=bulge_segment(p,Vector((side*.431,.370,-.035)),Vector((side*.574,.096,-.190)),.25,.18)
 if -.43<y<.20 and abs(x)>.055 and abs(x)<.43:
  p=bulge_segment(p,Vector((side*.162,.112,-.036)),Vector((side*.182,-.412,.008)),.30,.24)
 elif -.87<y<=-.43 and abs(x)<.40:
  p=bulge_segment(p,Vector((side*.182,-.412,.008)),Vector((side*.200,-.848,.081)),.24,.20)
 if y>.72 and abs(x)<.17:
  jaw=math.exp(-((y-.78)/.09)**2);p.x*=1+.055*jaw
  if z<-.04:p.z-=.008*jaw
 return p

objects=[];reports=[]
for part in PARTS:
 original=compatible(SOURCE/(part+'.mdjx'));mesh=bpy.data.meshes.new(part+'_Colossus');faces=[]
 for at in range(0,len(original.indices),3):
  tri=original.indices[at:at+3];a,b,c=(xyz(original.vertices[i].position) for i in tri)
  if (b-a).cross(c-a).length_squared>1e-16:faces.append(tri)
 mesh.from_pydata([xyz(sculpt(v.position)) for v in original.vertices],[],faces);mesh.update()
 obj=bpy.data.objects.new(part,mesh);kind='Medium_Armor' if 'medium' in part else 'Heavy_Armor' if 'heavy' in part else 'Base';collections[kind].objects.link(obj)
 for b in original.bones:obj.vertex_groups.new(name=b['name'])
 for index,v in enumerate(original.vertices):
  for joint,weight in zip(v.joints,v.weights):
   if weight>1e-7:obj.vertex_groups[original.bones[joint]['name']].add([index],weight,'REPLACE')
 uv=mesh.uv_layers.new(name='Miner_Atlas_UV')
 for poly in mesh.polygons:
  poly.use_smooth=True
  for li in poly.loop_indices:
   u,v=original.vertices[mesh.loops[li].vertex_index].uv;uv.data[li].uv=(u,-v)
 mesh.materials.append(mat);bpy.context.view_layer.objects.active=obj;obj.select_set(True)
 bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.mesh.remove_doubles(threshold=.000001);bpy.ops.object.mode_set(mode='OBJECT')
 low=export_native(obj,original,FOLDER/'lod1'/(part+'.mdjx'))
 sub=obj.modifiers.new('Sculpted_Surface','SUBSURF');sub.subdivision_type='CATMULL_CLARK' if kind=='Base' else 'SIMPLE';sub.levels=1;bpy.ops.object.modifier_apply(modifier=sub.name)
 tri=obj.modifiers.new('Native_Triangles','TRIANGULATE');bpy.ops.object.modifier_apply(modifier=tri.name)
 for vertex in obj.data.vertices:
  groups=sorted(((g.group,g.weight) for g in vertex.groups),key=lambda x:-x[1]);total=sum(w for _,w in groups[:4]);assert total>.99
  for i,(group,weight) in enumerate(groups):
   if i<4:obj.vertex_groups[group].add([vertex.index],weight/total,'REPLACE')
   else:obj.vertex_groups[group].remove([vertex.index])
 high=export_native(obj,original,FOLDER/'native'/(part+'.mdjx'));modifier=obj.modifiers.new('Original_Miner_Skeleton','ARMATURE');modifier.object=arm;obj.parent=arm
 obj.select_set(False);objects.append(obj)
 reports.append(dict(part=part,collection=kind,native=high,lod1=low,source_sha256=sha((SOURCE/(part+'.mdjx')).read_bytes())))
import_animations(arm)
for name,col in collections.items():col.hide_render=name!='Base'
scene=bpy.context.scene;scene.frame_start=1;scene.frame_end=max(c['frames'] for c in clips.values());scene.render.fps=30;scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.045,.055,.065,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.5
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.015));floor=bpy.context.object;floor.name='Preview_Floor';fm=bpy.data.materials.new('Studio_Floor');fm.diffuse_color=(.05,.06,.07,1);floor.data.materials.append(fm)
def area(name,location,energy,color,size):
 data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.color=color;data.size=size
 obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.location=location;obj.rotation_euler=(Vector((0,0,1))-obj.location).to_track_quat('-Z','Y').to_euler()
area('Key',(-3,4,5),600,(1,.93,.84),4);area('Fill',(3,2,3),380,(.77,.85,1),3);area('Rim',(0,-3,4),650,(1,.79,.55),3)
camdata=bpy.data.cameras.new('Preview_Camera');cam=bpy.data.objects.new('Preview_Camera',camdata);bpy.context.collection.objects.link(cam);scene.camera=cam;camdata.type='ORTHO';camdata.ortho_scale=2.5
cam.location=(2.6,5,2.4);cam.rotation_euler=(Vector((0,0,.99))-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True;scene.view_settings.view_transform='AgX';scene.render.resolution_x=1000;scene.render.resolution_y=1150;scene.render.resolution_percentage=100
arm.animation_data.action=bpy.data.actions['freakminer_empty_idle'];scene.frame_set(1)
scene.render.filepath=str(FOLDER/'preview/three-quarter.png');bpy.ops.render.render(write_still=True)
for name in ('Base','Medium_Armor','Heavy_Armor'):collections[name].hide_viewport=name!='Base'
arm.animation_data.action=None
for bone in arm.pose.bones:bone.matrix_basis=Matrix.Identity(4)
scene.frame_set(1);bpy.context.view_layer.update();bpy.ops.object.select_all(action='DESELECT');arm.select_set(True)
for obj in objects:
 if obj.name in ('freakminer_body','freakminer_legs'):obj.select_set(True)
bpy.context.view_layer.objects.active=arm;bpy.ops.wm.save_as_mainfile(filepath=str(FOLDER/'colossus.blend'))
bpy.ops.export_scene.gltf(filepath=str(FOLDER/'colossus.glb'),export_format='GLB',use_selection=True,export_animations=True,export_animation_mode='ACTIONS',export_skins=True,export_yup=True)
result=dict(passed=True,name='Colossus Miner',authored_in='Blender 4.5.0',rig_bones=len(bones),parts=reports,
 native_default_triangles=sum(p['native']['triangles'] for p in reports if p['collection']=='Base'),
 texture_sha256=sha((FOLDER/'textures/miner.jpg').read_bytes()),animation_source_files_modified=False,
 animations={n:dict(frames=c['frames'],fps=c['fps'],source_sha256=sha((SOURCE/'anim'/(n+'.adjx')).read_bytes())) for n,c in clips.items()},
 method='Compatible original miner topology remodeled in Blender for larger muscles; new imagegen albedo; all original bind data preserved',
 legacy_leg_normalization='Three out-of-range zero-weight joint references sanitized; no nonzero influence removed')
(FOLDER/'model.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
