"""Inspect the editable rig and sample demonstration deformations in Blender."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];FOLDER=ROOT/'assets/fighter-model-v1'
bpy.ops.wm.open_mainfile(filepath=str(FOLDER/'veteran.blend'))
arm=bpy.data.objects['Veteran_Rig'];parts=[bpy.data.objects['Veteran_'+p] for p in ('head','torso','legs','hands')]
assert len(arm.data.bones)==52
assert all(any(m.type=='ARMATURE' and m.object==arm for m in o.modifiers) for o in parts)
assert all(abs(sum(g.weight for g in v.groups)-1)<.002 for o in parts for v in o.data.vertices)
assert all(len(v.groups)<=4 for o in parts for v in o.data.vertices)
cases=[]
for name in ('Preview_Idle','Preview_Walk'):
    action=bpy.data.actions[name];arm.animation_data.action=action
    for frame in (1,5,9,13,17,21,25,29,33):
        bpy.context.scene.frame_set(frame);deps=bpy.context.evaluated_depsgraph_get();coords=[]
        for obj in parts:
            evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh()
            coords.extend(tuple(evaluated.matrix_world@v.co) for v in mesh.vertices)
            evaluated.to_mesh_clear()
        assert all(math.isfinite(c) for v in coords for c in v)
        bounds=[(min(v[i] for v in coords),max(v[i] for v in coords)) for i in range(3)]
        assert bounds[2][1]-bounds[2][0]<2.3 and bounds[0][1]-bounds[0][0]<2.5
        cases.append(dict(clip=name,frame=frame,bounds=bounds))
arm.animation_data.action=None
for bone in arm.pose.bones:bone.rotation_euler=(0,0,0)
bpy.context.scene.frame_set(1)
scene=bpy.context.scene;scene.cycles.samples=24
camera=scene.camera;camera.data.ortho_scale=2.05
scene.render.resolution_x=720;scene.render.resolution_y=960
for name,location in [('front',(0,5,1.2)),('side',(5,0,1.2)),('back',(0,-5,1.2))]:
    camera.location=location;camera.rotation_euler=(Vector((0,0,.94))-camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(FOLDER/'preview'/f'{name}.png');bpy.ops.render.render(write_still=True)
report=dict(passed=True,rig_bones=52,parts=4,maximum_influences=4,weight_sums_normalized=True,sampled_deformations=cases,
            limitation='Preview clips only. Native pistol idle and rotation checked separately in hosted graphical client; no complete graphical battle animation regression.')
(FOLDER/'rig-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(passed=True,sampled_poses=len(cases))))
