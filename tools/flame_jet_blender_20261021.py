"""Render an editable, directional, dense flame atlas entirely in Blender.

Eight world directions x eight time frames, 64px square tiles. No simulation
cache or external image is needed: emission/transparent procedural ribbons.
"""
import bpy, json, math, numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets/flame-jet-v1';OUT.mkdir(exist_ok=True,parents=True)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=12
scene.cycles.use_denoising=False;scene.render.film_transparent=True
scene.render.resolution_x=64;scene.render.resolution_y=64;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
scene.world.color=(0,0,0)
bpy.ops.object.camera_add(location=(0,0,5));camera=bpy.context.object
camera.data.type='ORTHO';camera.data.ortho_scale=2;scene.camera=camera
bpy.ops.mesh.primitive_plane_add(size=2);plane=bpy.context.object;plane.name='Dense_advected_flame_ribbon'
plane.scale=(.92,.92,1)
mat=bpy.data.materials.new('Flame_ribbon_procedural');mat.use_nodes=True
plane.data.materials.append(mat);n=mat.node_tree.nodes;l=mat.node_tree.links;n.clear()
def node(kind,name):
 a=n.new(kind);a.label=name;return a
def mathnode(op,a,b=None):
 z=node('ShaderNodeMath',op);z.operation=op
 for i,v in enumerate((a,b)):
  if v is None:continue
  if isinstance(v,(int,float)):z.inputs[i].default_value=v
  else:l.new(v,z.inputs[i])
 return z.outputs[0]
uv=node('ShaderNodeTexCoord','UV');sep=node('ShaderNodeSeparateXYZ','Split UV');l.new(uv.outputs['UV'],sep.inputs[0])
x=sep.outputs['X'];y=sep.outputs['Y']
noise=node('ShaderNodeTexNoise','Flowing turbulence');noise.noise_dimensions='4D'
l.new(uv.outputs['UV'],noise.inputs['Vector']);noise.inputs['Scale'].default_value=5.5
noise.inputs['Detail'].default_value=4;noise.inputs['Roughness'].default_value=.72
time=node('ShaderNodeValue','Flow phase');l.new(time.outputs[0],noise.inputs['W'])
wave=mathnode('MULTIPLY',mathnode('SUBTRACT',noise.outputs['Fac'],.5),.12)
axis=mathnode('ABSOLUTE',mathnode('SUBTRACT',mathnode('SUBTRACT',y,.5),wave))
# Broad opaque spine, feathered ragged edges, only a short transparent rim.
cap=mathnode('MULTIPLY',mathnode('SUBTRACT',x,.5),2)
cap=mathnode('SQRT',mathnode('MAXIMUM',mathnode('SUBTRACT',1,mathnode('MULTIPLY',cap,cap)),0))
width=mathnode('MULTIPLY',mathnode('SUBTRACT',mathnode('ADD',.36,mathnode('MULTIPLY',noise.outputs['Fac'],.12)),mathnode('MULTIPLY',x,.07)),cap)
edge=mathnode('MULTIPLY',mathnode('SUBTRACT',width,axis),14)
alpha=mathnode('MAXIMUM',edge,0);alpha=mathnode('MULTIPLY',mathnode('MINIMUM',alpha,1),.88)
heat=mathnode('ADD',mathnode('MULTIPLY',mathnode('SUBTRACT',1,mathnode('DIVIDE',axis,mathnode('MAXIMUM',width,.001))),.38),mathnode('MULTIPLY',noise.outputs['Fac'],.62))
ramp=node('ShaderNodeValToRGB','Orange edge, yellow-white core');l.new(heat,ramp.inputs[0])
colors=[(0,(.42,.008,.001,1)),(.30,(1,.055,.002,1)),(.52,(1,.34,.008,1)),(.65,(1,.80,.12,1)),(.80,(1,.97,.67,1))]
cr=ramp.color_ramp;cr.elements.remove(cr.elements[1]);cr.elements[0].position=colors[0][0];cr.elements[0].color=colors[0][1]
for pos,color in colors[1:]:cr.elements.new(pos).color=color
em=node('ShaderNodeEmission','Hot fire');l.new(ramp.outputs['Color'],em.inputs['Color']);em.inputs['Strength'].default_value=1
transparent=node('ShaderNodeBsdfTransparent','Transparent background');mix=node('ShaderNodeMixShader','Dense body alpha')
l.new(alpha,mix.inputs[0]);l.new(transparent.outputs[0],mix.inputs[1]);l.new(em.outputs[0],mix.inputs[2])
output=node('ShaderNodeOutputMaterial','Output');l.new(mix.outputs[0],output.inputs[0])
directions=[(1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1)]
atlas=np.zeros((512,512,4),dtype=np.float32);frames=[]
for bank,(dx,dy) in enumerate(directions):
 # Native projection: screen X=world Y-X, screen Y=(world X+Y)/2.
 angle=math.atan2(-(dx+dy)/2,dy-dx);plane.rotation_euler.z=angle
 for frame in range(8):
  time.outputs[0].default_value=frame*.28
  scene.frame_set(bank*8+frame+1)
  path=OUT/f'frame-{bank:01}-{frame:01}.png';scene.render.filepath=str(path)
  bpy.ops.render.render(write_still=True)
  image=bpy.data.images.load(str(path),check_existing=False)
  pixels=np.empty(64*64*4,dtype=np.float32);image.pixels.foreach_get(pixels)
  index=bank*8+frame;col=index%8;row=index//8
  atlas[(7-row)*64:(8-row)*64,col*64:(col+1)*64]=pixels.reshape(64,64,4)
  bpy.data.images.remove(image);frames.append(dict(bank=bank,frame=frame,world=[dx,dy],screen_angle=math.degrees(angle)))
image=bpy.data.images.new('TIO directional flame jet 8x8',width=512,height=512,alpha=True)
image.pixels.foreach_set(atlas.ravel());image.filepath_raw=str(OUT/'tio-flame-jet.png');image.file_format='PNG';image.save()
image.use_fake_user=True;image.pack()
plane.rotation_euler.z=0;scene.render.resolution_x=512;scene.render.resolution_y=512
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'flame-jet.blend'))
(OUT/'build.json').write_text(json.dumps(dict(passed=True,blender=bpy.app.version_string,atlas=[512,512],tile=[64,64],directions=8,time_frames=8,frames=frames,method='Cycles rendered procedural emission/transparent ribbons'),indent=2))
print('DIRECTIONAL_FLAME_ATLAS_COMPLETE')
