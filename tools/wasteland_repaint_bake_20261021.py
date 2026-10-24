"""Bake registered painted UV masters through Blender without changing layout."""
from pathlib import Path
import bpy,json,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'assets/wasteland-materials-v1'
tasks=json.loads((OUT/'tasks.json').read_text(encoding='utf-8'))
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.samples=1;s.cycles.use_denoising=False
s.view_settings.view_transform='Standard';s.view_settings.look='None';s.render.filter_size=.6
s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGBA';s.render.resolution_percentage=100
bpy.ops.mesh.primitive_plane_add(size=2);plane=bpy.context.object
bpy.ops.object.camera_add(location=(0,0,2));s.camera=bpy.context.object;s.camera.data.type='ORTHO';s.camera.data.ortho_scale=2
for name,file in (('armor_raider.jpg','raider-repaint.png'),('mob_sickminer.jpg','sickminer-repaint.png')):
    t=next(t for t in tasks if Path(t['path']).name==name)
    m=bpy.data.materials.new('Painted_'+Path(name).stem);m.use_nodes=True;m.use_fake_user=True;n=m.node_tree.nodes;n.clear();l=m.node_tree.links
    tex=n.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(OUT/'source'/file));tex.interpolation='Cubic';tex.extension='EXTEND';tex.image.pack()
    em=n.new('ShaderNodeEmission');l.new(tex.outputs['Color'],em.inputs[0]);out=n.new('ShaderNodeOutputMaterial');l.new(em.outputs[0],out.inputs[0])
    plane.data.materials.clear();plane.data.materials.append(m);s.render.resolution_x,s.render.resolution_y=t['render_size']
    s.render.filepath=str(OUT/'masters'/(t['id']+'.png'))
    if '--library-only' not in sys.argv:bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'source/painted-UV-masters.blend'))
