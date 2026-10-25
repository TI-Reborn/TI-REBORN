"""Render reference icons from native models. Run inside Blender 3.6+/4.x:

    blender -b -P tools/item_icons_hd/render_blender.py -- \
        --client "C:/Program Files (x86)/TIOnline" \
        --manifest assets/item-icons-hd-v1/manifest.json \
        --out work/item-icons-hd/render [--ids 210 211] [--textures DIR]

For every ``render`` item the first non-skin model is lit and shot with the
slot's fixed orthographic view (framing.py) on a transparent background.
``--textures`` may hold upscaled copies of client textures with the same file
names; they take precedence over ``base/models``. Outputs per item:
``<id>.png`` (colour, RGBA) and ``<id>.json`` (inputs, hashes, framing).
Nothing in the client folder is modified.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy  # noqa: E402  (Blender only)
from mathutils import Vector  # noqa: E402  (Blender only)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.item_icons_hd import framing, mesh  # noqa: E402
from tools.item_icons_hd.render_options import parse  # noqa: E402


def arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return parse(argv, base=Path.cwd())


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reset_scene(canvas, samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = canvas
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new('IconWorld')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.05, 0.055, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 0.35
    scene.world = world
    return scene


def texture_path(name, client, override):
    if not name:
        return None
    for folder in (override, client / 'base/models'):
        if folder and (folder / name).is_file():
            return folder / name
    raise FileNotFoundError(f'Texture {name} not found')


def material(name, texture):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = 0.62
    if texture is not None:
        image = nodes.new('ShaderNodeTexImage')
        image.image = bpy.data.images.load(str(texture))
        image.interpolation = 'Cubic'
        mat.node_tree.links.new(image.outputs['Color'], bsdf.inputs['Base Color'])
    else:
        bsdf.inputs['Base Color'].default_value = (0.35, 0.33, 0.3, 1)
    return mat


def add_mesh(name, geometry, center, yaw, mat):
    data = bpy.data.meshes.new(name)
    vertices = [tuple(c - o for c, o in zip(framing.to_blender(p), center)) for p in geometry.positions]
    data.from_pydata(vertices, [], geometry.triangles)
    data.update()
    uv = data.uv_layers.new(name='UVMap')
    for loop in data.loops:
        u, v = geometry.uvs[loop.vertex_index]
        uv.data[loop.index].uv = (u, 1 - v)  # native V grows downward
    for polygon in data.polygons:
        polygon.use_smooth = True
    data.materials.append(mat)
    obj = bpy.data.objects.new(name, data)
    obj.rotation_euler = (0, 0, -math.radians(yaw))
    bpy.context.collection.objects.link(obj)
    return obj


def add_camera(frame):
    cam_data = bpy.data.cameras.new('IconCamera')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = frame.ortho_scale
    cam = bpy.data.objects.new('IconCamera', cam_data)
    pitch = math.radians(frame.pitch)
    cam.location = (0, -frame.distance * math.cos(pitch), frame.distance * math.sin(pitch))
    cam.rotation_euler = (math.pi / 2 - pitch, 0, 0)
    cam_data.clip_end = frame.distance * 4
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam


def add_lights(radius):
    def area(name, location, energy, color, size):
        light = bpy.data.lights.new(name, 'AREA')
        light.energy, light.color, light.size = energy, color, size
        obj = bpy.data.objects.new(name, light)
        obj.location = location
        obj.rotation_euler = Vector([-c for c in location]).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.collection.objects.link(obj)
    d = max(radius, 0.2) * 4
    area('Key', (-d, -d, d), 900 * radius * radius, (1.0, 0.92, 0.82), d)
    area('Fill', (d, -d * 0.6, d * 0.3), 300 * radius * radius, (0.82, 0.9, 1.0), d)
    area('Rim', (0, d, d * 0.8), 700 * radius * radius, (1.0, 0.85, 0.65), d * 0.6)


def render(item, args):
    canvas = tuple(item['canvas'])
    model = item['models'][0]
    geometry = mesh.read(args.client / 'base/models' / f'{model}.mdjx')
    frame = framing.frame(geometry.positions, item['slot'], canvas)
    reset_scene(canvas, args.samples)
    texture = texture_path(item['textures'][0] if item['textures'] else '', args.client, args.textures)
    add_mesh(model, geometry, frame.center, frame.yaw, material(model, texture))
    add_camera(frame)
    add_lights(frame.distance / 4)
    out = args.out / f"{item['item_id']}.png"
    bpy.context.scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    record = dict(item_id=item['item_id'], model=model,
                  model_sha256=sha256(args.client / 'base/models' / f'{model}.mdjx'),
                  texture=str(texture) if texture else None,
                  texture_sha256=sha256(texture) if texture else None,
                  slot=item['slot'], canvas=list(canvas), yaw=frame.yaw, pitch=frame.pitch,
                  ortho_scale=frame.ortho_scale, output_sha256=sha256(out))
    (args.out / f"{item['item_id']}.json").write_text(json.dumps(record, indent=2), encoding='utf-8')
    return record


def main():
    args = arguments()
    args.out.mkdir(parents=True, exist_ok=True)
    items = json.loads(args.manifest.read_text(encoding='utf-8'))['items']
    chosen = [i for i in items if i['pipeline'] == 'render' and (not args.ids or i['item_id'] in args.ids)]
    if args.ids and len(chosen) != len(set(args.ids)):
        raise SystemExit('Some requested IDs are not render items')
    failures = []
    for item in chosen:
        try:
            print('rendered', render(item, args)['item_id'], flush=True)
        except (OSError, ValueError) as error:
            failures.append((item['item_id'], str(error)))
            print('failed', item['item_id'], error, flush=True)
    if failures:
        raise SystemExit(f'{len(failures)} renders failed: {failures}')


if __name__ == '__main__':
    main()
