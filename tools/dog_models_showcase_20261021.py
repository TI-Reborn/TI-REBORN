"""Render the three actual rigged models together from their .blend sources."""
import bpy
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];ASSET=ROOT/'assets/dog-mercenaries-v1'
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
for index,breed in enumerate(('doberman','huski','alsatian')):
 with bpy.data.libraries.load(str(ASSET/breed/(breed+'.blend')),link=False) as (source,target):
  target.objects=[n for n in source.objects if n in ('Dog_Rig','Dog_'+breed)]
 for obj in target.objects:bpy.context.collection.objects.link(obj)
 arm=next(o for o in target.objects if o.type=='ARMATURE');arm.location.x=(index-1)*1.1
 # The rest pose also preserves the authored surface and editable rig.
 arm.animation_data.action=None
scene=bpy.context.scene;scene.frame_set(1);scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.04,.055,.07,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.5
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.015));floor=bpy.context.object
mat=bpy.data.materials.new('Studio_Floor');mat.diffuse_color=(.045,.055,.065,1);floor.data.materials.append(mat)
def area(name,loc,energy,color,size):
 data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.size=size;data.color=color
 o=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.5))-o.location).to_track_quat('-Z','Y').to_euler()
area('Key',(-3,4,5),700,(1,.94,.86),5);area('Fill',(3,3,3),500,(.80,.88,1),4);area('Rim',(0,-3,4),700,(1,.85,.7),4)
data=bpy.data.cameras.new('Showcase_Camera');cam=bpy.data.objects.new('Showcase_Camera',data);bpy.context.collection.objects.link(cam);scene.camera=cam
data.type='ORTHO';data.ortho_scale=4.1;cam.location=(2.2,6,2.5);cam.rotation_euler=(Vector((0,0,.52))-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.engine='CYCLES';scene.cycles.samples=40;scene.cycles.use_denoising=True;scene.view_settings.view_transform='AgX'
scene.render.resolution_x=1600;scene.render.resolution_y=850;scene.render.resolution_percentage=100
(ASSET/'preview').mkdir(exist_ok=True);scene.render.filepath=str(ASSET/'preview/three-breeds.png');bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(ASSET/'three-breeds-showcase.blend'))
