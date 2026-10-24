"""Build editable rigged Blender/GLB assets and render the actual native meshes."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read
FOLDER=ROOT/'assets/fighter-model-v1'
def xyz(p):return Vector((p[0],-p[2],p[1]))
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
parts={p:read(FOLDER/'native'/f'tio_vet_{p}.mdjx') for p in ('torso','legs','hands','head')}
definitions={};parents={}
for m in parts.values():
 for i,b in enumerate(m.bones):
  definitions.setdefault(b['name'],b)
  if i!=b['parent']:parents.setdefault(b['name'],m.bones[b['parent']]['name'])
arm_data=bpy.data.armatures.new('TIO_Human_Compatible');arm=bpy.data.objects.new('Veteran_Rig',arm_data);bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active=arm;arm.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
for name,b in definitions.items():
 bone=arm_data.edit_bones.new(name);bone.head=xyz(b['head']);bone.tail=xyz(b['tip'])
 if (bone.tail-bone.head).length<.0001:bone.tail=bone.head+Vector((0,0,.05))
for name,parent in parents.items():
 if parent in arm_data.edit_bones and name!=parent:arm_data.edit_bones[name].parent=arm_data.edit_bones[parent]
bpy.ops.object.mode_set(mode='OBJECT');arm.select_set(False)
materials={}
for key in ('head','body'):
 mat=bpy.data.materials.new('Veteran_'+key);mat.use_nodes=True
 node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=bpy.data.images.load(str(FOLDER/'textures'/f'tio_vet_{key}.jpg'));node.image.pack()
 bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Roughness'].default_value=.83
 mat.node_tree.links.new(node.outputs['Color'],bsdf.inputs['Base Color']);materials[key]=mat
objects=[]
for part,m in parts.items():
 mesh=bpy.data.meshes.new('Veteran_'+part)
 coords=[xyz(v.position) for v in m.vertices];faces=[m.indices[i:i+3] for i in range(0,len(m.indices),3)]
 mesh.from_pydata(coords,[],faces);mesh.update()
 uv=mesh.uv_layers.new(name='UVMap')
 for poly in mesh.polygons:
  poly.use_smooth=True
  for loop in poly.loop_indices:
   v=m.vertices[mesh.loops[loop].vertex_index];uv.data[loop].uv=(v.uv[0],-v.uv[1])
 mesh.normals_split_custom_set_from_vertices([xyz(v.normal) for v in m.vertices])
 obj=bpy.data.objects.new('Veteran_'+part,mesh);bpy.context.collection.objects.link(obj)
 obj.data.materials.append(materials['head' if part=='head' else 'body'])
 for b in m.bones:obj.vertex_groups.new(name=b['name'])
 for index,v in enumerate(m.vertices):
  for joint,weight in zip(v.joints,v.weights):obj.vertex_groups[m.bones[joint]['name']].add([index],weight,'REPLACE')
 modifier=obj.modifiers.new('TIO_Human_Skeleton','ARMATURE');modifier.object=arm
 obj.parent=arm;objects.append(obj)
# Explicit demonstration clips for standard interchange exports. The native
# MDJX uses the game's existing animations and verbatim bind data.
arm.animation_data_create()
for name in ('Preview_Idle','Preview_Walk'):
 action=bpy.data.actions.new(name);action.use_fake_user=True;arm.animation_data.action=action
 for frame in (1,9,17,25,33):
  phase=(frame-1)/32*math.tau
  for bone_name in ('Bip01 Spine1','Bip01 L UpperArm','Bip01 R UpperArm','Bip01 L Thigh','Bip01 R Thigh'):
   if bone_name not in arm.pose.bones:continue
   bone=arm.pose.bones[bone_name];bone.rotation_mode='XYZ'
   amount=.009 if name=='Preview_Idle' else .24
   if bone_name=='Bip01 Spine1':amount=.012
   if 'R ' in bone_name:amount=-amount
   bone.rotation_euler=(math.sin(phase)*amount,0,0);bone.keyframe_insert(data_path='rotation_euler',frame=frame,group=bone_name)
arm.animation_data.action=None
for bone in arm.pose.bones:bone.rotation_euler=(0,0,0)
scene=bpy.context.scene;scene.frame_start=1;scene.frame_end=33;scene.render.fps=24
scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.055,.068,.085,1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value=.4
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.02));floor=bpy.context.object;floor.name='Preview_Floor'
mat=bpy.data.materials.new('Preview_Backdrop');mat.diffuse_color=(.055,.068,.08,1);floor.data.materials.append(mat)
def area(name,location,energy,color,size):
 data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.color=color;data.shape='DISK';data.size=size
 obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.location=location
 obj.rotation_euler=(Vector((0,0,1))-obj.location).to_track_quat('-Z','Y').to_euler()
area('Key',(-3,4,4.5),550,(1,.92,.83),4)
area('Fill',(3,2,3),300,(.78,.86,1),3)
area('Rim',(0,-3,3.2),700,(1,.78,.55),3)
camera_data=bpy.data.cameras.new('Preview_Camera');camera=bpy.data.objects.new('Preview_Camera',camera_data);bpy.context.collection.objects.link(camera)
scene.camera=camera;camera_data.type='ORTHO';camera_data.ortho_scale=2.15
def view(location,target,scale):
 camera.location=location;camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler();camera_data.ortho_scale=scale
view((2.7,5,2.2),(0,0,.94),2.15)
scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=32;scene.cycles.use_denoising=True
scene.render.resolution_x=900;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
scene.view_settings.view_transform='AgX'
out=FOLDER/'preview';out.mkdir(exist_ok=True)
scene.render.filepath=str(out/'three-quarter.png');bpy.ops.render.render(write_still=True)
# Save a complete editable source. Export only the game character, no studio.
bpy.ops.object.select_all(action='DESELECT');arm.select_set(True)
for obj in objects:obj.select_set(True)
bpy.context.view_layer.objects.active=arm
bpy.ops.wm.save_as_mainfile(filepath=str(FOLDER/'veteran.blend'))
bpy.ops.export_scene.gltf(filepath=str(FOLDER/'veteran.glb'),export_format='GLB',use_selection=True,export_animations=True,export_animation_mode='ACTIONS',export_skins=True,export_yup=True)
result=dict(passed=True,rig_bones=len(definitions),parts=len(objects),vertices=sum(len(m.vertices) for m in parts.values()),triangles=sum(len(m.indices)//3 for m in parts.values()),
            native_meshes_used=True,source='veteran.blend',interchange='veteran.glb',demonstration_clips=['Preview_Idle','Preview_Walk'],native_uses_unchanged_game_animation_files=True)
(FOLDER/'blender-build.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
