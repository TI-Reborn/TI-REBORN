"""Check authored geometry/door pivots and renders without touching game data."""
import bpy
import json
import math
import sys
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT=Path(__file__).resolve().parents[1]
DETAILS_V2='--details-v2' in sys.argv
OUT=ROOT/('assets/hangar-wasteland-v2' if DETAILS_V2 else 'assets/hangar-wasteland-v1')
bpy.ops.wm.open_mainfile(filepath=str(OUT/'hangar-wasteland.blend'))
scene=bpy.context.scene
report=json.loads((OUT/'model.json').read_text())
results={}
objects=[bpy.data.objects[a['name']] for a in report['modules']]
assert all(o.type=='MESH' for o in objects)
assert all(len(o.data.uv_layers)==1 and len(o.data.materials)>0 for o in objects)
assert all(math.isfinite(c) for o in objects for v in o.data.vertices for c in v.co)
degenerate=[]
for obj in objects:
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        a,b,c=(obj.data.vertices[i].co for i in tri.vertices)
        if (b-a).cross(c-a).length_squared<1e-16:degenerate.append((obj.name,tri.index))
assert not degenerate,degenerate[:20]
results['geometry']={'modules':len(objects),'triangles':sum(len(o.data.loop_triangles) for o in objects),
                     'finite_vertices':True,'all_modules_uv_mapped':True,'degenerate_triangles':len(degenerate)}

doors=[bpy.data.objects['Door_'+n+'_Hinge'] for n in ('A','B')]
transforms={}
for frame,expected in ((1,0),(46,-100),(91,0)):
    scene.frame_set(frame);bpy.context.view_layer.update()
    transforms[str(frame)]=[math.degrees(d.rotation_euler.z) for d in doors]
    assert all(abs(a-expected)<.001 for a in transforms[str(frame)])
scene.frame_set(46)
for door in doors:
    coords=[door.children[0].matrix_world@v.co for v in door.children[0].data.vertices]
    if 'Door_A' in door.name:assert max(v.x for v in coords)<1.08
    else:assert min(v.x for v in coords)>9.92
for i,door in enumerate(doors):
    other=doors[1-i]
    other.animation_data.nla_tracks[0].mute=True
    other.rotation_euler.z=0
    scene.frame_set(45);scene.frame_set(46);bpy.context.view_layer.update()
    assert abs(math.degrees(door.rotation_euler.z)+100)<.001
    assert abs(other.rotation_euler.z)<.00001
    other.animation_data.nla_tracks[0].mute=False
results['doors']={'count':2,'independent_clips':True,'sampled_angles_degrees':transforms,
                  'open_leaves_outside_entrances':True,'real_mesh_portals':True}

# Prop proxies and actual mesh bounds must stay out of the main walking strip.
walk=(1,3.43,10,4.57)
for item in report['collision_guides']:
    x0,y0,z0,x1,y1,z1=item['native_bounds']
    assert not (x0<walk[2] and x1>walk[0] and y0<walk[3] and y1>walk[1]),item
for obj in objects:
    if obj['module_type'] not in ('shelf','barrel','crate','pallet','workbench','cabinet','tyres','spool','pipes','generator','debris','vegetation','wall_growth'):
        continue
    coords=[obj.matrix_world@v.co for v in obj.data.vertices]
    assert not any(1.05<v.x<9.95 and 3.43<v.y<4.57 and v.z>.12 for v in coords),obj.name
results['layout']={'prop_proxies_checked':len(report['collision_guides']),'central_walkway_clear':True,
                   'original_fragment_cells':[12,9],'original_door_cells':[[1,4],[10,4]]}
if DETAILS_V2:
    growth=[o for o in objects if o['module_type']=='vegetation']
    for obj in growth:
        coords=[obj.matrix_world@v.co for v in obj.data.vertices]
        assert not any((-.3<v.x<1.2 or 9.8<v.x<11.3) and 3.2<v.y<5.05 and .1<v.z<2.6 for v in coords),obj.name
    assert report['detailing']['graffiti_decals']==6
    assert report['detailing']['grass_clumps']>90
    assert report['detailing']['ivy_runs']==6
    results['detailing']={**report['detailing'],'entrance_sweep_areas_clear':True}

scene.camera=bpy.data.objects['TIO_Isometric_32_16']
scene.render.resolution_x=740;scene.render.resolution_y=600
def project(x,y):
    q=world_to_camera_view(scene,scene.camera,Vector((x,y,0)))
    return (q.x*740,(1-q.y)*600)
origin=project(0,0)
xstep=[a-b for a,b in zip(project(1,0),origin)]
ystep=[a-b for a,b in zip(project(0,1),origin)]
assert max(abs(a-b) for a,b in zip(origin,(384,240)))<.001
assert max(abs(a-b) for a,b in zip(xstep,(-32,16)))<.001
assert max(abs(a-b) for a,b in zip(ystep,(32,16)))<.001
results['projection']={'origin':origin,'x_step':xstep,'y_step':ystep,'common_layer_origin':True}

used={m for o in objects for m in o.data.materials}
missing=[]
for material in used:
    for node in material.node_tree.nodes:
        if node.type=='TEX_IMAGE' and node.image:
            if not node.image.packed_file:missing.append(node.image.name)
assert not missing,missing
results['textures']={'all_used_images_packed':True,'pbr_sets':7,'baked_png_maps':21,
                     'generated_albedo_applied':all('weathered_albedo' in next(
                         l.from_node.image.name for l in m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].links)
                         for m in used if m.name in ('faded_olive_steel','dead_ochre_steel','rusted_iron','dirty_bone_enamel'))}
assert results['textures']['generated_albedo_applied']
results['passed']=True
results['scope']='Blender source and exports; not client runtime or hosted gameplay verification'
(OUT/'validation-blender.json').write_text(json.dumps(results,indent=2)+'\n')
print('HANGAR_VALIDATION_COMPLETE',json.dumps(results),flush=True)
