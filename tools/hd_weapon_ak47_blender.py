"""Model the HD AK-47 in the game's own weapon frame and paint its side texture (Blender).

blender -b --factory-startup --python-exit-code 1 -P tools/hd_weapon_ak47_blender.py -- OUT_DIR

Geometry is built directly in native MDJX coordinates (x across, y up, -z to
the muzzle, origin at the trigger where the hand bone holds the weapon) and
follows the landmarks of the original weapon_ak47: butt at z=+0.33, receiver
top y~0.105, bore axis y=0.056, curved magazine down to (-0.16, -0.18),
front sight at z=-0.58, muzzle at -0.60. The game proportions (chunkier than
a real AKM) are kept so the hands and animations still meet the weapon.

Texturing is a side projection: an orthographic render from +x of the
albedo with ambient occlusion fills the AK rectangle of weapons_pak1, and
every vertex gets the UV of its own projected position. Parts that exist on
the right side only (charging handle, selector) are hidden in that render,
so they are painted with the receiver steel behind them and the left side
does not show their print.

Outputs: ak47_mesh.json (vertices, corner normals, UVs, triangles) and
ak47_side.png (the rectangle, supersampled).
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

OUT = Path(sys.argv[sys.argv.index('--') + 1])
XC = 0.004  # the original's centre line across the weapon
# Texture rectangle in weapons_pak1.jpg (1024 px), free of every other weapon.
RECT = dict(x=365, y=528, w=370, h=152)
SPAN_Z = (0.345, -0.630)  # left edge (butt) and right edge (muzzle) of the rectangle
SUPERSAMPLE = 4


def scale_px_per_m():
    return RECT['w'] / (SPAN_Z[0] - SPAN_Z[1])


def rect_centre():
    k = scale_px_per_m()
    return (SPAN_Z[0] + SPAN_Z[1]) / 2, -0.040, RECT['h'] / k


# ---------------------------------------------------------------- geometry

def new_object(name, mesh, material, asymmetric=False):
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    obj['asymmetric'] = asymmetric
    return obj


def profile(name, points, half_width, material, bevel=0.0025, segments=2, x=XC, asymmetric=False):
    """A side-profile polygon (z, y) extruded across x and bevelled."""
    bm = bmesh.new()
    left = [bm.verts.new((x - half_width, y, z)) for z, y in points]
    right = [bm.verts.new((x + half_width, y, z)) for z, y in points]
    bm.faces.new(left[::-1])
    bm.faces.new(right)
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((left[i], left[j], right[j], right[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = new_object(name, mesh, material, asymmetric)
    if bevel:
        mod = obj.modifiers.new('bevel', 'BEVEL')
        mod.width = bevel
        mod.segments = segments
        mod.limit_method = 'ANGLE'
        mod.angle_limit = math.radians(35)
    return obj


def box(name, z0, z1, y0, y1, half_width, material, bevel=0.0015, x=XC, asymmetric=False):
    return profile(name, [(z0, y0), (z1, y0), (z1, y1), (z0, y1)], half_width, material, bevel, 1, x, asymmetric)


def cylinder(name, z0, z1, y, radius, material, sides=14, x=XC, bevel=0.0012):
    """A cylinder along z from z0 to z1 around (x, y)."""
    bm = bmesh.new()
    rings = []
    for z in (z0, z1):
        rings.append([bm.verts.new((x + radius * math.cos(2 * math.pi * i / sides),
                                    y + radius * math.sin(2 * math.pi * i / sides), z)) for i in range(sides)])
    bm.faces.new(rings[0])
    bm.faces.new(rings[1][::-1])
    for i in range(sides):
        j = (i + 1) % sides
        bm.faces.new((rings[0][i], rings[0][j], rings[1][j], rings[1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = new_object(name, mesh, material)
    if bevel:
        mod = obj.modifiers.new('bevel', 'BEVEL')
        mod.width = bevel
        mod.segments = 1
        mod.limit_method = 'ANGLE'
        mod.angle_limit = math.radians(60)
    return obj


def stud(name, z, y, radius, length, material, side=1, sides=10):
    """A short cylinder sticking out of the receiver side along x (rivets, charging handle)."""
    bm = bmesh.new()
    x0 = XC + side * 0.0158
    rings = []
    for x in (x0, x0 + side * length):
        rings.append([bm.verts.new((x, y + radius * math.cos(2 * math.pi * i / sides),
                                    z + radius * math.sin(2 * math.pi * i / sides))) for i in range(sides)])
    bm.faces.new(rings[0])
    bm.faces.new(rings[1][::-1])
    for i in range(sides):
        j = (i + 1) % sides
        bm.faces.new((rings[0][i], rings[0][j], rings[1][j], rings[1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return new_object(name, mesh, material, asymmetric=side > 0 and length > 0.004)


def bezier(p0, p1, p2, steps):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
            for t in (i / steps for i in range(steps + 1))]


def tube(name, points, half_width, thickness, material):
    """A flat bar following a (z, y) polyline (trigger guard)."""
    outline_a, outline_b = [], []
    for i, (z, y) in enumerate(points):
        a = points[max(i - 1, 0)]
        b = points[min(i + 1, len(points) - 1)]
        dz, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dz, dy)
        nz, ny = -dy / length, dz / length
        outline_a.append((z + nz * thickness / 2, y + ny * thickness / 2))
        outline_b.append((z - nz * thickness / 2, y - ny * thickness / 2))
    return profile(name, outline_a + outline_b[::-1], half_width, material, bevel=0.0012, segments=1)


# ---------------------------------------------------------------- materials

def material_steel(name, base, wear):
    """Dark steel with sparse worn speckles; depth comes from the occlusion in the render.

    (Pointiness is not usable here: on large flat faces it is interpolated
    from the corners and paints the whole face as worn.)
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes['Principled BSDF']
    coarse = nodes.new('ShaderNodeTexNoise')
    coarse.inputs['Scale'].default_value = 22
    coarse.inputs['Detail'].default_value = 6
    coarse.inputs['Roughness'].default_value = 0.65
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (*base, 1)
    ramp.color_ramp.elements[1].position = 0.85
    ramp.color_ramp.elements[1].color = (*wear, 1)
    grime = nodes.new('ShaderNodeTexNoise')
    grime.inputs['Scale'].default_value = 8
    rust = nodes.new('ShaderNodeValToRGB')  # warm worn patches, as on the icon
    rust.color_ramp.elements[0].color = (0.75, 0.75, 0.78, 1)
    rust.color_ramp.elements[1].color = (1.35, 1.05, 0.80, 1)
    links.new(grime.outputs['Fac'], rust.inputs['Fac'])
    mix = nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.inputs['Factor'].default_value = 0.6
    links.new(coarse.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], mix.inputs[6])
    links.new(rust.outputs['Color'], mix.inputs[7])
    links.new(mix.outputs[2], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
    return mat


def material_wood(name, dark, light, grain_scale=7):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes['Principled BSDF']
    coords = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeMapping')
    mapping.inputs['Scale'].default_value = (1, 6, 0.35)  # grain runs along the weapon (z)
    wave = nodes.new('ShaderNodeTexWave')
    wave.wave_type = 'BANDS'
    wave.bands_direction = 'Y'
    wave.inputs['Scale'].default_value = grain_scale
    wave.inputs['Distortion'].default_value = 14
    wave.inputs['Detail'].default_value = 4
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    links.new(coords.outputs['Object'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], wave.inputs['Vector'])
    links.new(wave.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
    return mat


def material_checkered(name, base):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes['Principled BSDF']
    checker = nodes.new('ShaderNodeTexChecker')
    checker.inputs['Scale'].default_value = 60
    checker.inputs['Color1'].default_value = (*base, 1)
    checker.inputs['Color2'].default_value = tuple(c * 0.6 for c in base) + (1,)
    links.new(checker.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
    return mat


# ---------------------------------------------------------------- the rifle

def build():
    steel = material_steel('steel', (0.065, 0.060, 0.053), (0.16, 0.15, 0.135))
    blued = material_steel('blued', (0.042, 0.041, 0.043), (0.10, 0.097, 0.095))
    wood = material_wood('wood', (0.030, 0.006, 0.002), (0.42, 0.105, 0.028))
    grip = material_checkered('grip', (0.14, 0.035, 0.012))

    parts = []
    # Butt stock with steel butt plate.
    parts.append(profile('stock', [(0.335, 0.041), (0.335, -0.050), (0.25, -0.036), (0.16, -0.014),
                                   (0.105, -0.002), (0.074, 0.010), (0.074, 0.066), (0.10, 0.070),
                                   (0.19, 0.051), (0.26, 0.047)],
                         0.0155, wood, bevel=0.004, segments=3))
    parts.append(box('butt_plate', 0.343, 0.335, -0.052, 0.043, 0.0165, steel, bevel=0.002))
    # Receiver, dust cover with ribs, rear sight block and leaf.
    parts.append(profile('receiver', [(0.078, 0.004), (0.078, 0.090), (0.060, 0.100), (-0.150, 0.100),
                                      (-0.205, 0.096), (-0.205, 0.020), (-0.150, -0.010), (-0.062, -0.010),
                                      (0.040, -0.002)], 0.0160, steel, bevel=0.0025))
    parts.append(profile('dust_cover', [(0.070, 0.098), (-0.150, 0.098), (-0.150, 0.106), (0.030, 0.109),
                                        (0.064, 0.106)], 0.0135, blued, bevel=0.004, segments=3))
    for k, z in enumerate((0.040, 0.000, -0.040, -0.080)):
        parts.append(box(f'cover_rib_{k}', z + 0.004, z - 0.004, 0.103, 0.110, 0.0125, blued, bevel=0.0015))
    parts.append(box('sight_block', -0.150, -0.207, 0.098, 0.112, 0.0140, steel, bevel=0.002))
    parts.append(profile('sight_leaf', [(-0.150, 0.110), (-0.188, 0.110), (-0.188, 0.117), (-0.160, 0.114)],
                         0.0060, blued, bevel=0.001, segments=1))
    # Front trunnion ring and magazine well lip.
    parts.append(box('trunnion', -0.205, -0.214, 0.016, 0.100, 0.0172, steel, bevel=0.002))
    parts.append(box('mag_well', -0.064, -0.150, -0.016, -0.004, 0.0168, steel, bevel=0.0015))
    # Stamped dimple above the magazine and the side rail line of the receiver.
    parts.append(box('dimple', -0.085, -0.120, 0.032, 0.046, 0.0163, blued, bevel=0.0012))
    parts.append(box('receiver_rail', 0.070, -0.200, 0.086, 0.090, 0.0164, blued, bevel=0.0006))
    # Pistol grip, trigger guard, trigger.
    parts.append(profile('pistol_grip', [(0.030, -0.004), (0.072, 0.000), (0.118, -0.078), (0.113, -0.090),
                                         (0.068, -0.093), (0.060, -0.085)], 0.0140, grip, bevel=0.004, segments=3))
    parts.append(tube('trigger_guard', [(0.032, -0.008), (0.020, -0.036), (0.000, -0.044), (-0.050, -0.042),
                                        (-0.062, -0.012)], 0.0060, 0.0050, steel))
    parts.append(tube('trigger', [(0.002, -0.008), (-0.002, -0.022), (0.004, -0.034)], 0.0035, 0.0045, blued))
    # Curved magazine with ribs and a floor plate.
    rear = bezier((-0.070, -0.010), (-0.080, -0.112), (-0.163, -0.186), 10)
    front = bezier((-0.142, -0.010), (-0.150, -0.088), (-0.207, -0.137), 10)
    parts.append(profile('magazine', rear + front[::-1], 0.0130, blued, bevel=0.003, segments=2))
    for k, (a, b) in enumerate(((0.30, 0.42), (0.55, 0.67))):
        lo = [(r[0] + (f[0] - r[0]) * a, r[1] + (f[1] - r[1]) * a) for r, f in zip(rear[1:-1], front[1:-1])]
        hi = [(r[0] + (f[0] - r[0]) * b, r[1] + (f[1] - r[1]) * b) for r, f in zip(rear[1:-1], front[1:-1])]
        parts.append(profile(f'mag_rib_{k}', lo + hi[::-1], 0.0142, blued, bevel=0.0012, segments=1))
    parts.append(profile('mag_floor', [(rear[-1][0] + 0.004, rear[-1][1] - 0.004), (front[-1][0] - 0.004, front[-1][1] - 0.004),
                                       (front[-1][0] + 0.004, front[-1][1] + 0.010), (rear[-1][0] + 0.010, rear[-1][1] + 0.010)],
                         0.0140, steel, bevel=0.0015, segments=1))
    # Handguards, retaining ring, gas tube, gas block.
    parts.append(profile('lower_handguard', [(-0.212, 0.018), (-0.365, 0.024), (-0.368, 0.066), (-0.212, 0.068)],
                         0.0190, wood, bevel=0.009, segments=4))
    for k, z in enumerate((-0.250, -0.300)):
        parts.append(box(f'vent_{k}', z, z - 0.028, 0.050, 0.058, 0.0196, blued, bevel=0.001))
    parts.append(cylinder('upper_handguard', -0.214, -0.330, 0.089, 0.0155, wood, sides=16))
    parts.append(cylinder('handguard_ring', -0.366, -0.378, 0.058, 0.0215, steel, sides=18))
    parts.append(cylinder('gas_tube', -0.330, -0.440, 0.089, 0.0095, steel, sides=14))
    parts.append(box('gas_block', -0.428, -0.452, 0.046, 0.098, 0.0120, steel, bevel=0.003))
    # Barrel, cleaning rod, front sight, muzzle nut.
    parts.append(cylinder('barrel', -0.205, -0.580, 0.056, 0.0090, blued, sides=16))
    parts.append(cylinder('cleaning_rod', -0.378, -0.575, 0.039, 0.0028, steel, sides=8, bevel=0))
    parts.append(box('front_sight_base', -0.562, -0.590, 0.044, 0.084, 0.0110, steel, bevel=0.003))
    for side in (-1, 1):
        parts.append(box(f'sight_ear_{side}', -0.568, -0.586, 0.080, 0.112, 0.0018, steel, bevel=0.0008,
                         x=XC + side * 0.0085))
    parts.append(box('sight_post', -0.574, -0.580, 0.080, 0.106, 0.0012, blued, bevel=0.0005))
    parts.append(cylinder('muzzle_nut', -0.580, -0.605, 0.056, 0.0105, steel, sides=12))
    # Rivets (both sides), charging handle and selector (right side only).
    for side in (-1, 1):
        for z, y in ((0.050, 0.020), (0.010, 0.020), (-0.030, 0.012), (-0.120, 0.012), (-0.180, 0.030),
                     (0.050, 0.078), (-0.180, 0.078)):
            parts.append(stud(f'rivet_{side}_{z}_{y}', z, y, 0.0026, 0.0012, steel, side=side, sides=8))
    parts.append(stud('charging_handle', -0.125, 0.084, 0.0050, 0.016, steel, side=1))
    parts.append(profile('selector', [(0.062, 0.080), (-0.050, 0.064), (-0.054, 0.056), (0.058, 0.068)], 0.0012,
                         blued, bevel=0.0006, segments=1, x=XC + 0.0172, asymmetric=True))
    return parts


# ---------------------------------------------------------------- texture and export

def render_side(parts):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'
    scene.render.resolution_x = RECT['w'] * SUPERSAMPLE
    scene.render.resolution_y = RECT['h'] * SUPERSAMPLE
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    world = bpy.data.worlds.new('ambient')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    # Mostly uniform white light on matte materials renders albedo x ambient
    # occlusion; a soft light from above paints gentle highlights on upper
    # bevels, as the original game textures do. The game adds its own light.
    world.node_tree.nodes['Background'].inputs[1].default_value = 0.8
    scene.world = world
    light = bpy.data.lights.new('top', 'AREA')
    light.energy = 6
    light.size = 2.0
    top = bpy.data.objects.new('top', light)
    bpy.context.collection.objects.link(top)
    top.matrix_world = Matrix(((1, 0, 0, XC + 0.5), (0, 0, 1, 1.0), (0, -1, 0, -0.14), (0, 0, 0, 1)))
    zc, yc, height = rect_centre()
    camera_data = bpy.data.cameras.new('side')
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = SPAN_Z[0] - SPAN_Z[1]
    camera = bpy.data.objects.new('side', camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (1.0, yc, zc)
    # Look along -x with +y up: image right is -z (muzzle on the right).
    camera.matrix_world = Matrix(((0, 0, 1, 1.0), (0, 1, 0, yc), (-1, 0, 0, zc), (0, 0, 0, 1)))
    scene.camera = camera
    for obj in parts:
        obj.hide_render = bool(obj['asymmetric'])
    scene.render.filepath = str(OUT / 'ak47_side.png')
    bpy.ops.render.render(write_still=True)
    for obj in parts:
        obj.hide_render = False
    return zc, yc


def export(parts, zc, yc):
    k = scale_px_per_m()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    vertices, index, triangles = [], {}, []
    for obj in parts:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        try:
            corner_normals = [tuple(n.vector) for n in mesh.corner_normals]
        except AttributeError:
            mesh.calc_normals_split()
            corner_normals = [tuple(loop.normal) for loop in mesh.loops]
        for tri in mesh.loop_triangles:
            corners = []
            for loop_index in tri.loops:
                p = tuple(round(c, 6) for c in mesh.vertices[mesh.loops[loop_index].vertex_index].co)
                n = tuple(round(c, 4) for c in corner_normals[loop_index])
                col = RECT['x'] + RECT['w'] / 2 + (zc - p[2]) * k
                row = RECT['y'] + RECT['h'] / 2 + (yc - p[1]) * k
                uv = (round(col / 1024, 6), round(row / 1024 - 1, 6))
                key = (p, n, uv)
                if key not in index:
                    index[key] = len(vertices)
                    vertices.append(dict(position=p, normal=n, uv=uv))
                corners.append(index[key])
            triangles.append(corners)
        evaluated.to_mesh_clear()
    (OUT / 'ak47_mesh.json').write_text(json.dumps(dict(vertices=vertices, triangles=triangles, rect=RECT,
                                                        span_z=SPAN_Z, centre=[zc, yc], px_per_m=k)))
    print('AK47_EXPORT', len(vertices), len(triangles))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    parts = build()
    for obj in parts:
        obj.data.shade_smooth()
        if hasattr(obj.data, 'use_auto_smooth'):
            obj.data.use_auto_smooth = True
            obj.data.auto_smooth_angle = math.radians(35)
        else:
            mod = obj.modifiers.new('smooth', 'SMOOTH_BY_ANGLE') if 'SMOOTH_BY_ANGLE' in dir(bpy.types) else None
            if mod is None:
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
                obj.select_set(False)
    zc, yc = render_side(parts)
    export(parts, zc, yc)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'ak47.blend'))


main()
