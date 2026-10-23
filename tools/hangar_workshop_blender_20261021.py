"""Author an original, modular hangar in Blender; no installed/live assets change.

Run with Blender 4.5 --background --factory-startup --python this_file.
Native TILE coordinates are mapped to Blender (y,x,z), one cell = one metre.
Textures are authored as Blender node materials and baked in Blender, not copied
from original artwork. All geometry is authored here from primitives/mesh data.
"""
import bpy
import json
import math
import sys
from pathlib import Path
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets/hangar-workshop-v1'
REPORT = ROOT / 'reports/hangar-workshop-20261021'
for folder in ('textures', 'preview', 'isometric', 'modules', 'source'):
    (OUT / folder).mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.use_denoising = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.fps = 30
scene.frame_start, scene.frame_end = 1, 91
scene.view_settings.view_transform = 'AgX'
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.32, .40, .48, 1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .45
collections = {}
for name in ('01_Foundation', '02_Wall_A', '03_Wall_B', '04_Wall_Left',
             '05_Wall_Right', '06_Roof', '07_Interior', '08_Doors',
             '09_Preview', '10_Collision'):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    collections[name] = c
CURRENT = collections['01_Foundation']
MODULE = []
MODULES = []
COLLIDERS = []


def p(x, y, z=0):
    return Vector((y, x, z))


def move_collection(obj, col=None):
    for c in tuple(obj.users_collection):
        c.objects.unlink(obj)
    (col or CURRENT).objects.link(obj)


def activate(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def uv_project(obj):
    """Metre-scale planar UVs for structural panels, with repeat sampling."""
    uv = obj.data.uv_layers.active or obj.data.uv_layers.new(name='UV_Metre')
    for f in obj.data.polygons:
        axis = max(range(3), key=lambda a: abs(f.normal[a]))
        axes = [a for a in range(3) if a != axis]
        for li in f.loop_indices:
            v = obj.data.vertices[obj.data.loops[li].vertex_index].co
            uv.data[li].uv = (v[axes[0]], v[axes[1]])


def finish(obj, name, mat, bevel=0):
    obj.name = name
    move_collection(obj)
    obj.data.materials.append(mat)
    activate(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    uv_project(obj)
    if bevel:
        mod = obj.modifiers.new('Manufactured_edges', 'BEVEL')
        mod.width, mod.segments = bevel, 1
        bpy.ops.object.modifier_apply(modifier=mod.name)
        normal = obj.modifiers.new('Weighted_corner_normals', 'WEIGHTED_NORMAL')
        bpy.ops.object.modifier_apply(modifier=normal.name)
    MODULE.append(obj)
    return obj


def box(name, xyz, dims, mat, bevel=.012):
    bpy.ops.mesh.primitive_cube_add(size=1, location=p(*xyz))
    obj = bpy.context.object
    obj.dimensions = (dims[1], dims[0], dims[2])
    return finish(obj, name, mat, bevel)


def cylinder(name, xyz, radius, depth, mat, axis='Z', vertices=20):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=p(*xyz))
    obj = bpy.context.object
    if axis == 'X':
        obj.rotation_euler.x = math.pi / 2
    elif axis == 'Y':
        obj.rotation_euler.y = math.pi / 2
    finish(obj, name, mat, .006)
    for f in obj.data.polygons:
        if len(f.vertices) == 4:
            f.use_smooth = True
    return obj


def torus(name, xyz, radius, tube, mat, axis='Z'):
    bpy.ops.mesh.primitive_torus_add(major_radius=radius, minor_radius=tube,
                                   major_segments=24, minor_segments=6, location=p(*xyz))
    obj = bpy.context.object
    if axis == 'X':
        obj.rotation_euler.x = math.pi / 2
    finish(obj, name, mat)
    for f in obj.data.polygons:
        f.use_smooth = True
    return obj


def beam(name, a, b, width, mat):
    a, b = p(*a), p(*b)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(a + b) / 2)
    obj = bpy.context.object
    obj.dimensions = (width, width, (b - a).length)
    obj.rotation_euler = (b - a).to_track_quat('Z', 'Y').to_euler()
    return finish(obj, name, mat, .007)


def wedge(name, x, yz, depth, mat):
    verts = [p(xx, y, z) for xx in (x - depth / 2, x + depth / 2) for y, z in yz]
    n = len(yz)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    # Native->Blender swaps two axes, hence reverse the face winding.
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], [tuple(reversed(f)) for f in faces])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    CURRENT.objects.link(obj)
    return finish(obj, name, mat, .005)


def label(text, xyz, size, mat, face='X'):
    bpy.ops.object.text_add(location=p(*xyz))
    obj = bpy.context.object
    obj.data.body, obj.data.size = text, size
    obj.data.align_x = 'CENTER'
    obj.data.extrude = .001
    # Text local +Z normal points toward the selected exterior.
    normal = p(1 if face == 'X' else 0, 1 if face == 'Y' else 0, 0)
    obj.rotation_euler = normal.to_track_quat('Z', 'Y').to_euler()
    bpy.ops.object.convert(target='MESH')
    return finish(bpy.context.object, 'Sign_' + text, mat)


def module_start():
    global MODULE
    MODULE = []


def module_end(name, anchor=None, kind='static', collider=None):
    objs = list(MODULE)
    assert objs
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    if anchor is not None:
        # Make the module origin useful for placement in Blender and GLB.
        world = obj.matrix_world.copy()
        target = p(*anchor)
        transform = Matrix.Translation(-target) @ world
        obj.data.transform(transform)
        obj.matrix_world = Matrix.Translation(target)
    obj['module_type'] = kind
    obj['native_anchor_xy'] = list(anchor[:2]) if anchor else [0., 0.]
    MODULES.append(obj)
    if collider:
        COLLIDERS.append({'module': name, 'native_bounds': collider, 'kind': 'solid_prop'})
    return obj


def solid(name, color, rough=.6, metal=0, emission=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bs = mat.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value = (*color, 1)
    bs.inputs['Roughness'].default_value = rough
    bs.inputs['Metallic'].default_value = metal
    if emission:
        bs.inputs['Emission Color'].default_value = (*color, 1)
        bs.inputs['Emission Strength'].default_value = emission
    return mat


def baked_material(name, dark, light, roughness, metal=0, grain=False):
    """Blender procedural source retained; RGB, roughness and tangent normal baked."""
    mat = solid(name + '_PROCEDURAL', light, roughness, metal)
    mat.use_fake_user = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    shader, output = nodes.get('Principled BSDF'), nodes.get('Material Output')
    uv = nodes.new('ShaderNodeTexCoord')
    # A toroidal 4D domain makes the noise periodic on both UV axes.
    scale = nodes.new('ShaderNodeVectorMath'); scale.operation = 'SCALE'
    scale.inputs[3].default_value = 2 * math.pi
    links.new(uv.outputs['UV'], scale.inputs[0])
    sep = nodes.new('ShaderNodeSeparateXYZ'); links.new(scale.outputs['Vector'], sep.inputs[0])
    trig = []
    for component, operation in (('X', 'COSINE'), ('X', 'SINE'), ('Y', 'COSINE'), ('Y', 'SINE')):
        node = nodes.new('ShaderNodeMath'); node.operation = operation
        links.new(sep.outputs[component], node.inputs[0]); trig.append(node)
    vec = nodes.new('ShaderNodeCombineXYZ')
    for i in range(3): links.new(trig[i].outputs[0], vec.inputs[i])
    noise = nodes.new('ShaderNodeTexNoise'); noise.noise_dimensions = '4D'
    noise.inputs['Scale'].default_value = 5
    noise.inputs['Detail'].default_value = 3
    links.new(vec.outputs[0], noise.inputs['Vector']); links.new(trig[3].outputs[0], noise.inputs['W'])
    fac = noise.outputs['Fac']
    if grain:
        wave = nodes.new('ShaderNodeTexWave'); wave.wave_type = 'BANDS'; wave.bands_direction = 'Y'
        wave.inputs['Scale'].default_value = 5
        wave.inputs['Distortion'].default_value = 3
        wave.inputs['Detail Scale'].default_value = 2
        links.new(uv.outputs['UV'], wave.inputs['Vector'])
        fac = wave.outputs['Fac']
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = .25
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].position = .8
    ramp.color_ramp.elements[1].color = (*light, 1)
    links.new(fac, ramp.inputs[0]); links.new(ramp.outputs['Color'], shader.inputs['Base Color'])
    r = nodes.new('ShaderNodeMapRange')
    r.inputs['To Min'].default_value = max(.1, roughness - .13)
    r.inputs['To Max'].default_value = min(1, roughness + .13)
    links.new(noise.outputs['Fac'], r.inputs['Value']); links.new(r.outputs[0], shader.inputs['Roughness'])
    bump = nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = .22
    bump.inputs['Distance'].default_value = .012 if name == 'concrete' else .004
    links.new(fac, bump.inputs['Height']); links.new(bump.outputs[0], shader.inputs['Normal'])
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, -50))
    plane = bpy.context.object; plane.name = 'Temporary_Bake_Surface'
    plane.data.materials.append(mat)
    # Blender primitive plane UV is precisely [0,1]^2.
    emission = nodes.new('ShaderNodeEmission')
    images = {}
    for channel, source in (('albedo', ramp.outputs['Color']), ('roughness', r.outputs[0]), ('normal', None)):
        img = bpy.data.images.new(name + '_' + channel, width=1024, height=1024, alpha=False)
        img.colorspace_settings.name = 'sRGB' if channel == 'albedo' else 'Non-Color'
        target = nodes.new('ShaderNodeTexImage'); target.image = img; nodes.active = target
        if source is not None:
            links.new(source, emission.inputs['Color']); links.new(emission.outputs[0], output.inputs['Surface'])
        else:
            links.new(shader.outputs[0], output.inputs['Surface'])
        scene.cycles.samples = 1
        bpy.ops.object.bake(type='NORMAL' if source is None else 'EMIT', margin=2)
        img.filepath_raw = str(OUT / 'textures' / (name + '_' + channel + '.png'))
        img.file_format = 'PNG'; img.save(); img.pack()
        images[channel] = img
    links.new(shader.outputs[0], output.inputs['Surface'])
    bpy.data.objects.remove(plane, do_unlink=True)
    runtime = solid(name, light, roughness, metal)
    nodes, links = runtime.node_tree.nodes, runtime.node_tree.links
    shader = nodes.get('Principled BSDF')
    for channel, image in images.items():
        node = nodes.new('ShaderNodeTexImage'); node.image = image; node.extension = 'REPEAT'
        if channel == 'normal':
            normal = nodes.new('ShaderNodeNormalMap')
            links.new(node.outputs['Color'], normal.inputs['Color'])
            links.new(normal.outputs['Normal'], shader.inputs['Normal'])
        else:
            links.new(node.outputs['Color'], shader.inputs['Base Color' if channel == 'albedo' else 'Roughness'])
    print('TEXTURE_COMPLETE', name, flush=True)
    return runtime


teal = baked_material('petrol_painted_steel', (.026, .125, .15), (.09, .29, .32), .62, .45)
yellow = baked_material('ochre_painted_steel', (.38, .16, .025), (.83, .48, .10), .63, .3)
concrete = baked_material('concrete', (.25, .29, .28), (.54, .56, .51), .9)
metal = baked_material('graphite_steel', (.045, .06, .065), (.12, .15, .16), .48, .8)
wood = baked_material('pallet_wood', (.19, .105, .055), (.46, .31, .16), .86, grain=True)
rubber = baked_material('rubber', (.011, .015, .017), (.047, .052, .055), .9)
cream = solid('ivory_enamel', (.70, .72, .65), .65, .18)
red = solid('oxide_red', (.36, .07, .035), .7, .3)
glass = solid('blue_glass_panels', (.09, .27, .32), .24, .35)
light = solid('warm_lamp', (.95, .72, .35), .25, .0, 2.5)
black = solid('safety_graphite', (.025, .029, .026), .78)

# 12x9-cell map fragment. Native hangar.t itself is placed at (0,-1).
CURRENT = collections['01_Foundation']; module_start()
box('Concrete_apron', (5.5, 4, -.1), (11.6, 8.6, .2), concrete, .035)
box('Workshop_floor', (5.5, 4, .035), (8.8, 5.8, .07), concrete)
for x in (2, 4, 6, 8): box('Floor_expansion_joint', (x, 4, .073), (.012, 5.65, .004), metal, 0)
for y in (3.25, 4.75): box('Pedestrian_lane', (5.5, y, .079), (8.65, .045, .008), yellow, 0)
for x in (1.4, 9.6):
    for i in range(6):
        obj = box('Threshold_safety_mark', (x, 3.55 + i * .18, .08), (.24, .075, .008), yellow, 0)
        obj.rotation_euler.z = .4
for x in (1, 10):
    box('Door_step', (x, 4, .045), (.52, 1.25, .09), metal)
    for yy in (3.55, 3.7, 3.85, 4, 4.15, 4.3, 4.45):
        box('Step_grip', (x, yy, .094), (.48, .025, .01), cream, 0)
floor = module_end('Foundation_and_lane', (0, 0, 0), 'foundation')

# Four wall modules; door portals are real mesh openings, never black decals.
for x, col, suffix in ((1., '02_Wall_A', 'A'), (10., '03_Wall_B', 'B')):
    CURRENT = collections[col]; module_start()
    for y0, y1 in ((1, 3.43), (4.57, 7)):
        box('Concrete_plinth', (x, (y0 + y1) / 2, .38), (.18, y1-y0, .62), concrete)
        box('End_panel', (x, (y0 + y1) / 2, 1.93), (.15, y1-y0, 2.48), teal)
        for y in [y0 + .15 + i * .38 for i in range(int((y1-y0-.2)/.38)+1)]:
            box('Panel_seam', (x + (.095 if x > 5 else -.095), y, 1.94), (.025, .024, 2.42), metal, .003)
    box('Portal_lintel', (x, 4, 2.89), (.20, 1.18, .62), teal)
    wedge('High_gable', x, [(1,3.2), (1,3.4), (4.4,4.25), (4.4,3.65), (7,3.2)], .16, teal)
    for y in (1, 3.4, 4.6, 7): box('Portal_upright', (x, y, 1.62), (.24, .10, 3.12), cream)
    for y in (3.4, 4.6):
        for z in (.35, .6, .85, 1.1):
            box('Jamb_caution', (x + (.135 if x>5 else -.135), y, z), (.014, .105, .10), yellow, 0)
    box('Door_header', (x, 4, 2.58), (.26, 1.3, .12), cream)
    box('Canopy', (x + (.22 if x>5 else -.22), 4, 2.82), (.65, 1.52, .08), metal)
    box('Door_light', (x + (.14 if x>5 else -.14), 4, 2.70), (.09, .45, .08), light)
    if x > 5:
        box('Workshop_number_board', (x+.105, 5.65, 2.2), (.035, 1.4, .62), metal)
        label('H / 07', (x+.13, 5.65, 2.10), .28, cream)
    module_end('End_wall_' + suffix, (x, 4, 0), 'wall')

for y, col in ((1, '04_Wall_Left'), (7, '05_Wall_Right')):
    CURRENT = collections[col]; module_start()
    box('Long_plinth', (5.5, y, .38), (9, .20, .62), concrete)
    box('Long_wall_lower', (5.5, y, 1.32), (9, .15, 1.28), teal)
    box('Long_wall_upper', (5.5, y, 3.02), (9, .15, .34), teal)
    box('High_window_strip', (5.5, y, 2.42), (8.9, .055, .83), glass)
    box('Window_sill', (5.5, y, 1.98), (9, .25, .09), cream)
    for x in (1, 2.5, 4, 5.5, 7, 8.5, 10):
        box('Steel_column', (x, y, 1.64), (.13, .24, 3.15), metal)
        box('Window_mullion', (x, y, 2.42), (.06, .17, .90), cream)
    for x in [1.2 + i*.36 for i in range(25)]:
        box('Cladding_joint', (x, y + (.09 if y>4 else -.09), 1.32), (.022, .018, 1.25), metal, .002)
    module_end('Long_wall_' + ('Left' if y==1 else 'Right'), (5.5, y, 0), 'wall')

CURRENT = collections['06_Roof']; module_start()
for yy0, yy1, z0, z1 in ((.76, 4.4, 3.34, 4.25), (4.4, 7.24, 3.65, 3.16)):
    slope = math.atan2(z1-z0, yy1-yy0)
    for i in range(15):
        x = .82 + (i+.5)*9.36/15
        obj = box('Roof_folded_panel', (x, (yy0+yy1)/2, (z0+z1)/2), (9.36/15-.012, math.hypot(yy1-yy0,z1-z0), .085), metal)
        obj.rotation_euler.y = -slope
        beam('Raised_standing_seam', (x-.29,yy0,z0+.055), (x-.29,yy1,z1+.055), .025, teal)
    for x in (1.1, 4, 7, 9.9):
        beam('Roof_truss_top', (x, yy0, z0-.10), (x, yy1, z1-.10), .10, cream)
        beam('Roof_truss_tie', (x, yy0+.15, 3.02), (x, yy1-.15, 3.02), .08, metal)
        mid=(yy0+yy1)/2
        beam('Truss_web', (x, yy0+.2, 3.02), (x, mid, (z0+z1)/2-.14), .065, metal)
        beam('Truss_web', (x, yy1-.2, 3.02), (x, mid, (z0+z1)/2-.14), .065, metal)
box('Clerestory_glass', (5.5,4.4,3.94), (9,.07,.53), glass)
for x in (1,2.5,4,5.5,7,8.5,10): box('Clerestory_mullion', (x,4.4,3.94), (.055,.12,.6), cream)
for z in (3.64,4.26):box('Clerestory_flashing', (5.5,4.4,z), (9.4,.18,.06), teal)
for x in (3,7.7):
    box('Roof_vent_plinth', (x,2.55,3.99), (.72,.72,.24), metal)
    box('Roof_vent_hood', (x,2.55,4.15), (.95,.9,.10), teal)
    for i in range(5):box('Vent_louvre', (x,2.22,4.02+i*.025), (.63,.05,.014), cream, 0)
for y in (.79,7.21):box('Rain_gutter', (5.5,y,3.25 if y>4 else 3.43), (9.7,.12,.14), metal)
roof = module_end('Asymmetric_clerestory_roof', (5.5,4,0), 'roof')

# Independently keyed, outward-swinging rigid doors (no deforming skeleton).
CURRENT = collections['08_Doors']
DOORS = []
for name, x, hinge_y, direction in (('A',.94,4.54,-1), ('B',10.06,3.46,1)):
    module_start()
    yc = hinge_y + direction*.54
    box('Armoured_door_leaf', (x,yc,1.30), (.075,1.08,2.40), yellow)
    for z in (.18,2.42): box('Door_edge_rail', (x,yc,z), (.11,1.06,.075), metal)
    for yy in (hinge_y+direction*.04,hinge_y+direction*1.04):
        box('Door_edge_stile', (x,yy,1.3), (.11,.065,2.37), metal)
    for z in (.48,.84,1.2,1.56,1.92):
        box('Door_recess', (x + (.045 if name=='B' else -.045),yc,z), (.018,.86,.02), metal, .003)
    for z in (.35,1.25,2.2):
        cylinder('Heavy_hinge', (x,hinge_y,z), .055,.19,metal)
    for dx in (-.08,.08):box('Door_handle', (x+dx,hinge_y+direction*.9,1.16), (.04,.16,.045), cream)
    leaf = module_end('Door_'+name+'_Leaf', (x,hinge_y,0), 'door')
    pivot = bpy.data.objects.new('Door_'+name+'_Hinge', None)
    CURRENT.objects.link(pivot); pivot.location = p(x,hinge_y,0)
    bpy.context.view_layer.update()
    leaf.parent=pivot; leaf.matrix_parent_inverse=pivot.matrix_world.inverted()
    pivot['native_door_cell'] = [1 if name=='A' else 10,4]
    pivot['closed_angle_degrees'] = 0.; pivot['open_angle_degrees'] = 100.
    for frame, degrees in ((1,0),(36,100),(60,100),(91,0)):
        pivot.rotation_euler.z=math.radians(degrees)
        pivot.keyframe_insert(data_path='rotation_euler',index=2,frame=frame)
    action=pivot.animation_data.action; action.name='Door_'+name+'_Open_Close'
    track=pivot.animation_data.nla_tracks.new(); track.name=action.name
    track.strips.new(action.name,1,action)
    pivot.animation_data.action=None
    DOORS.append(pivot)

CURRENT = collections['07_Interior']


def crate(name,x,y,z=0,size=.65):
    module_start()
    box('Shipping_case', (x,y,z+size/2+.1), (size,size*.8,size), wood)
    for xx in (x-size*.38,x+size*.38):box('Case_steel_band',(xx,y,z+size/2+.1),(.045,size*.82,size+.02),metal)
    for zz in (z+.14,z+size+.08):box('Case_batten',(x,y-size*.415,zz),(size,.045,.07),wood)
    return module_end(name,(x,y,z),'crate',[x-size/2,y-size*.4,z,x+size/2,y+size*.4,z+size+.12])


def shelf(name,x,y):
    module_start()
    for dx in (-.78,.78):
        for dy in (-.25,.25):
            box('Perforated_upright',(x+dx,y+dy,1.12),(.055,.055,2.10),metal)
            box('Foot_plate',(x+dx,y+dy,.11),(.13,.13,.06),metal)
    for z in (.22,.85,1.48,2.10):
        box('Shelf_tray',(x,y,z),(1.62,.57,.055),cream)
        box('Shelf_safety_edge',(x,y-.28,z+.03),(1.64,.04,.09),yellow)
    beam('Rack_cross_brace',(x-.78,y+.26,.25),(x+.78,y+.26,2.08),.035,metal)
    beam('Rack_cross_brace',(x+.78,y+.26,.25),(x-.78,y+.26,2.08),.035,metal)
    for level,z in enumerate((.27,.90,1.53)):
        for i in range(3):
            xx=x-.52+i*.49
            box('Stored_case',(xx,y,z+.16),(.36,.37,.32),wood if (i+level)%2 else teal)
            box('Inventory_label',(xx,y-.191,z+.19),(.12,.008,.09),cream,0)
            box('Case_strap',(xx+.1,y,z+.16),(.035,.382,.33),metal,.002)
    return module_end(name,(x,y,0),'shelf',[x-.84,y-.3,.1,x+.84,y+.3,2.2])


for name,x,y in (('Shelf_01',3.3,1.58),('Shelf_02',5.4,1.58),('Shelf_03',3.1,6.40),('Shelf_04',5.3,6.40)):
    shelf(name,x,y)


def barrel(name,x,y,mat):
    module_start()
    cylinder('Drum_body',(x,y,.57),.31,.94,mat,vertices=24)
    for z in (.12,.37,.77,1.04):torus('Rolled_drum_rib',(x,y,z),.312,.014,metal)
    cylinder('Inset_lid',(x,y,1.045),.285,.018,metal,vertices=24)
    cylinder('Bung_cap',(x+.12,y+.08,1.066),.042,.027,cream,vertices=12)
    box('Drum_label',(x,y-.311,.62),(.21,.008,.23),cream,.002)
    return module_end(name,(x,y,0),'barrel',[x-.33,y-.33,.1,x+.33,y+.33,1.09])

for name,x,y,mat in (('Barrel_01',8.3,6.30,teal),('Barrel_02',9.05,6.3,yellow),('Barrel_03',8.65,5.55,red)):
    barrel(name,x,y,mat)

for name,x,y,z,size in (('Crate_01',7.45,6.25,0,.75),('Crate_02',7.45,6.25,.84,.53),
                       ('Crate_03',8.55,1.9,0,.85),('Crate_04',9.15,2.7,0,.55)):
    crate(name,x,y,z,size)

module_start()
for x in (7.95,8.55,9.15):box('Pallet_runner',(x,1.95,.13),(.12,1.0,.12),wood)
for i in range(6):box('Pallet_deck',(8.55,1.48+i*.18,.23),(1.4,.135,.075),wood)
module_end('Wooden_pallet',(8.55,1.95,0),'pallet',[7.85,1.45,.07,9.25,2.45,.28])

module_start()
for x in (1.95,3.05):
    for y in (2.25,2.85):box('Bench_leg',(x,y,.57),(.07,.07,1.0),metal)
box('Bench_lower_shelf',(2.5,2.55,.28),(1.25,.65,.06),teal)
box('Bench_top',(2.5,2.55,1.08),(1.45,.8,.11),wood)
box('Bench_backboard',(2.5,2.92,1.49),(1.42,.055,.66),teal)
for x in (2.02,2.22,2.42,2.62,2.82):
    box('Tool_hook',(x,2.87,1.57),(.035,.06,.055),metal)
    box('Hanging_wrench',(x,2.84,1.43),(.035,.027,.23),cream)
    torus('Spanner_head',(x,2.84,1.55),.043,.013,metal,axis='X')
box('Bench_vice',(2.0,2.25,1.22),(.26,.22,.18),metal)
box('Vice_jaws',(2.,2.25,1.35),(.31,.16,.06),cream)
cylinder('Vice_screw',(2,2.08,1.22),.025,.27,metal,axis='Y',vertices=12)
box('Toolbox',(2.8,2.55,1.25),(.48,.32,.23),red)
box('Toolbox_handle',(2.8,2.55,1.42),(.20,.05,.08),metal)
module_end('Repair_workbench',(2.5,2.55,0),'workbench',[1.75,2.12,.1,3.25,3.,1.85])

module_start()
box('Cabinet_case',(6.75,6.45,.68),(.75,.65,1.2),teal)
box('Cabinet_worktop',(6.75,6.45,1.31),(.82,.72,.08),metal)
for z in (.25,.48,.71,.94,1.17):
    box('Drawer_front',(6.75,6.11,z),(.67,.035,.19),teal)
    box('Drawer_pull',(6.75,6.075,z+.04),(.30,.045,.026),cream)
for x in (6.45,7.05):
    for y in (6.19,6.71):cylinder('Cabinet_caster',(x,y,.11),.08,.05,rubber,axis='X',vertices=12)
module_end('Rolling_tool_cabinet',(6.75,6.45,0),'cabinet',[6.34,6.07,.04,7.16,6.82,1.36])

module_start()
for z in (.24,.50,.76):
    torus('Truck_tyre',(7.,1.95,z),.28,.11,rubber)
    for i in range(16):
        a=i*math.tau/16
        tread=box('Tyre_tread',(7+.375*math.cos(a),1.95+.375*math.sin(a),z),(.06,.09,.14),rubber,.006)
        tread.rotation_euler.z=-a
module_end('Tyre_stack',(7,1.95,0),'tyres',[6.59,1.54,.12,7.41,2.36,.88])

module_start()
cylinder('Spool_core',(5.75,2.5,.41),.19,.52,wood)
for z in (.16,.68):cylinder('Spool_flange',(5.75,2.5,z),.36,.055,wood)
for z in (.25,.32,.39,.46,.53,.60):torus('Cable_winding',(5.75,2.5,z),.25,.045,rubber)
module_end('Cable_spool',(5.75,2.5,0),'spool',[5.37,2.12,.12,6.13,2.88,.74])

module_start()
for yy,zz in ((2.4,.25),(2.7,.25),(2.55,.48)):
    cylinder('Pipe_section',(4.4,yy,zz),.13,1.45,metal,axis='X')
    for xx in (3.72,5.08):torus('Pipe_flange',(xx,yy,zz),.14,.025,cream,axis='X')
for xx in (3.85,4.9):box('Pipe_support',(xx,2.55,.11),(.12,.75,.12),wood)
module_end('Pipe_rack',(4.4,2.55,0),'pipes',[3.63,2.15,.05,5.17,2.92,.65])

module_start()
box('Service_power_box',(1.18,2.55,1.45),(.22,.60,.84),cream)
for yy in (2.38,2.55,2.72):box('Electric_panel_vent',(1.304,yy,1.18),(.014,.025,.16),metal,0)
box('Power_warning',(1.305,2.55,1.55),(.014,.19,.20),yellow)
beam('Cable_conduit',(1.12,2.23,.12),(1.12,2.23,3.03),.038,metal)
module_end('Electrical_service',(1.15,2.55,0),'wall_fixture')

for x,y in ((1.17,5.1),(9.83,2.95)):
    module_start()
    cylinder('Extinguisher_cylinder',(x,y,.92),.10,.50,red,vertices=16)
    box('Extinguisher_valve',(x,y,1.22),(.08,.12,.07),metal)
    box('Extinguisher_notice',(x,y,1.62),(.04,.22,.27),red)
    box('Notice_cross_h',(x+.025,y,1.62),(.014,.15,.04),cream,0)
    box('Notice_cross_v',(x+.025,y,1.62),(.014,.04,.15),cream,0)
    module_end('Fire_station_'+str(len(MODULES)),(x,y,0),'wall_fixture')

# Ceiling lamps stay with removable roof, to avoid hanging in a cutaway.
CURRENT=collections['06_Roof']; module_start()
for x in (2.5,5.5,8.5):
    box('Luminaire_case',(x,4.,3.13),(1.0,.16,.10),metal)
    box('Luminaire_diffuser',(x,4.,3.07),(.91,.13,.035),light)
module_end('Ceiling_luminaires',(5.5,4,0),'roof_fixture')

# Explicit collision proxies are editable guides; never included in beauty/GLB.
CURRENT=collections['10_Collision']; module_start()
for i,a in enumerate(COLLIDERS):
    x0,y0,z0,x1,y1,z1=a['native_bounds']
    obj=box('COL_'+a['module'],((x0+x1)/2,(y0+y1)/2,(z0+z1)/2),(x1-x0,y1-y0,z1-z0),red,0)
    obj.display_type='WIRE'; obj.hide_render=True
for c in ('10_Collision',):
    collections[c].hide_render=True
    collections[c].hide_viewport=True

# Lighting/cameras are independent of the exported model.
CURRENT=collections['09_Preview']
def area(name, xyz, target, energy, color, size):
    data=bpy.data.lights.new(name,'AREA'); data.energy=energy; data.color=color; data.shape='DISK'; data.size=size
    obj=bpy.data.objects.new(name,data); CURRENT.objects.link(obj); obj.location=p(*xyz)
    obj.rotation_euler=(p(*target)-obj.location).to_track_quat('-Z','Y').to_euler()
    return obj

area('Key_softbox',(1,-3,12),(5.5,4,0),1900,(1,.88,.70),8)
area('Sky_fill',(13,5,10),(5.5,4,1),1400,(.65,.82,1),8)
area('Back_rim',(2,10,9),(5.5,4,1),1700,(1,.80,.59),6)
data=bpy.data.lights.new('Daylight','SUN'); data.energy=1.5; data.angle=.15
sun=bpy.data.objects.new('Daylight',data); CURRENT.objects.link(sun); sun.rotation_euler=(.45,-.4,-.5)

def camera(name, xyz, target, ortho, resolution):
    data=bpy.data.cameras.new(name); data.type='ORTHO'; data.ortho_scale=ortho
    obj=bpy.data.objects.new(name,data); CURRENT.objects.link(obj); obj.location=p(*xyz)
    obj.rotation_euler=(p(*target)-obj.location).to_track_quat('-Z','Y').to_euler()
    scene.camera=obj; scene.render.resolution_x,scene.render.resolution_y=resolution
    return obj

def render(path, samples=24):
    scene.cycles.samples=samples; scene.render.filepath=str(OUT/path)
    bpy.context.view_layer.update(); bpy.ops.render.render(write_still=True)
    print('RENDER_COMPLETE',path,flush=True)

def visibility(names):
    for name,col in collections.items():
        col.hide_render=name not in names and name!='09_Preview'

asset_cols={n for n in collections if n not in ('09_Preview','10_Collision')}
visibility(asset_cols); scene.frame_set(1)
hero=camera('Exterior_Hero',(17,16,12.5),(5.5,4,1.25),15,(1440,1080))
render(Path('preview/exterior-closed.png'),32)
scene.frame_set(46); render(Path('preview/exterior-open.png'),32)
camera('Rear_Hero',(-7,-9,10),(5.5,4,1.25),15,(1440,1080))
render(Path('preview/rear-open.png'),24)
visibility({'01_Foundation','02_Wall_A','04_Wall_Left','07_Interior','08_Doors'})
camera('Interior_Cutaway',(14,16,15),(5.5,4,1.1),14,(1440,1080))
render(Path('preview/interior-cutaway.png'),40)

# Pixel-exact 2:1 ground projection, shared origin across ALL isometric layers.
visibility(asset_cols); scene.frame_set(1)
cam=camera('TIO_Isometric_32_16',(25.5,24.,20*math.sqrt(2/3)+1.3),(5.5,4,1.3),740/(32*math.sqrt(2)),(740,600))
bpy.context.view_layer.update()
q=world_to_camera_view(scene,cam,p(0,0,0))
right=cam.rotation_euler.to_matrix()@Vector((1,0,0))
up=cam.rotation_euler.to_matrix()@Vector((0,1,0))
cam.location += right*((q.x*740-384)/(32*math.sqrt(2))) + up*((q.y*600-(600-240))/(32*math.sqrt(2)))
bpy.context.view_layer.update()
def project(x,y,z=0):
    q=world_to_camera_view(scene,cam,p(x,y,z)); return [q.x*740,(1-q.y)*600]
projection={'origin_px':project(0,0),'x_step_px':[a-b for a,b in zip(project(1,0),project(0,0))],
            'y_step_px':[a-b for a,b in zip(project(0,1),project(0,0))],
            'image_size':[740,600],'top_left_native_screen':[-384,-240],
            'native_tile_placement_offset':[0,-1],
            'note':'Fragment-space anchors. Original hangar.t local door y=5 becomes fragment y=4.'}
assert max(abs(a-b) for a,b in zip(projection['origin_px'],[384,240]))<.001,projection
assert max(abs(a-b) for a,b in zip(projection['x_step_px'],[-32,16]))<.001,projection
assert max(abs(a-b) for a,b in zip(projection['y_step_px'],[32,16]))<.001,projection
render(Path('isometric/assembled-closed.png'),24)
scene.frame_set(46); render(Path('isometric/assembled-open.png'),24)
for name,cols in (
    ('floor',{'01_Foundation'}),('walls-far',{'02_Wall_A','04_Wall_Left'}),
    ('walls-near',{'03_Wall_B','05_Wall_Right'}),('roof',{'06_Roof'}),
    ('interior',{'07_Interior'}),('interior-cutaway',{'01_Foundation','02_Wall_A','04_Wall_Left','07_Interior'})):
    visibility(cols); render(Path('isometric/'+name+'.png'),16)
visibility({'08_Doors'})
for door in DOORS:
    for other in DOORS:
        for leaf in other.children: leaf.hide_render=other!=door
    for frame,state in ((1,'closed'),(46,'open')):
        scene.frame_set(frame);render(Path('isometric/'+door.name.replace('_Hinge','').lower()+'-'+state+'.png'),16)
for door in DOORS:
    for leaf in door.children:leaf.hide_render=False

# Export individual prop modules, at local origin, for future map variations.
visibility(asset_cols); scene.frame_set(1)
for obj in MODULES:
    if obj['module_type'] not in ('shelf','barrel','crate','pallet','workbench','cabinet','tyres','spool','pipes'):
        continue
    activate(obj); old=obj.matrix_world.copy(); obj.matrix_world=Matrix.Identity(4)
    bpy.ops.export_scene.gltf(filepath=str(OUT/'modules'/(obj.name+'.glb')),export_format='GLB',use_selection=True,
                              export_animations=False,export_yup=True,export_extras=True)
    obj.matrix_world=old

bpy.ops.object.select_all(action='DESELECT')
for obj in MODULES+DOORS:obj.select_set(True)
bpy.context.view_layer.objects.active=DOORS[0]
bpy.ops.export_scene.gltf(filepath=str(OUT/'hangar-workshop.glb'),export_format='GLB',use_selection=True,
                          export_animations=True,export_animation_mode='NLA_TRACKS',export_force_sampling=True,
                          export_frame_range=True,export_yup=True,export_extras=True)
scene.camera=hero;scene.render.resolution_x=1440;scene.render.resolution_y=1080
scene.frame_set(1);visibility(asset_cols)
for screen in bpy.data.screens:
    for area_ui in screen.areas:
        if area_ui.type=='VIEW_3D':
            area_ui.spaces.active.region_3d.view_distance=17
            area_ui.spaces.active.region_3d.view_location=p(5.5,4,1.5)
            area_ui.spaces.active.clip_end=1000
for img in bpy.data.images:
    if img.source=='FILE' and img.filepath:
        img.filepath='//textures/'+Path(img.filepath).name
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'hangar-workshop.blend'))

stats=[]
for obj in MODULES:
    obj.data.calc_loop_triangles()
    stats.append({'name':obj.name,'kind':obj['module_type'],'triangles':len(obj.data.loop_triangles),
                  'vertices':len(obj.data.vertices),'uv_layers':len(obj.data.uv_layers),
                  'materials':len(obj.data.materials),'native_anchor_xy':list(obj['native_anchor_xy'])})
report={'authoring':'Blender 4.5 procedural geometry and baked node materials; no original artwork reused',
        'name':'Workshop H / 07','status':'authored; NOT installed in game or published',
        'footprint_cells':[12,9],'metres_per_cell':1,'shell_native_bounds':[1,1,10,7],
        'wall_height_m':3.2,'max_roof_height_m':4.30,'door_cells':[[1,4],[10,4]],
        'door_animation':{'clips':['Door_A_Open_Close','Door_B_Open_Close'],'fps':30,'frames':[1,91],
                          'closed_frame':1,'open_frame':46,'swing_degrees':100,'independent_rigid_pivots':True},
        'clear_walkway_native_aabb':[1,3.43,10,4.57],
        'native_projection':projection,'modules':stats,'total_triangles':sum(a['triangles'] for a in stats),
        'texture_resolution':[1024,1024],'pbr_sets':6,'maps_per_set':['albedo','roughness','normal'],
        'collision_guides':COLLIDERS,
        'integration_required':['Generate and verify TILE wall strips/roof visibility and door state frames',
                                'Map each existing fragment prop/container to a compatible new module',
                                'Verify original client depth sorting, interaction cells and roof fade',
                                'Stage with hosted authoritative doors, back up hosted assets before publication'],
        'verification_scope':'Source/export checks and rendered previews; no real game client integration yet'}
(OUT/'model.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print('HANGAR_BUILD_COMPLETE',json.dumps({'triangles':report['total_triangles'],'modules':len(stats),'doors':2}),flush=True)
