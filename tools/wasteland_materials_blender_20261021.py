"""Registered, material-aware surface painting in Blender 4.5.

The original is a UV/color/lighting guide. New multiscale material response is
authored with nodes, rendered with supersampling and encoded separately into
native codecs. These are texture restorations, not new object silhouettes.
"""
import bpy, json, math, sys, hashlib, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ASSET=ROOT/'assets/wasteland-materials-v1'
tasks=json.loads((ASSET/'tasks.json').read_text(encoding='utf-8'))
args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
sample='--sample' in args
terrain_only='--terrain' in args
if terrain_only:tasks=[t for t in tasks if 'terrain_linear_rgb' in t]
active_only='--active' in args
if active_only:
    names={t['path'] for t in json.loads((ROOT/'reports/remaining-textures-20261021/active-materials.json').read_text(encoding='utf-8'))}
    tasks=[t for t in tasks if t['path'] in names]
last_pair='--last-pair' in args
if last_pair:tasks=[t for t in tasks if t['path'] in ('base/models/armor_masks.jpg','base/models/target_diffuse.jpg')]
library_only='--library-only' in args
if sample:
    selected=[]
    for material in ('masonry','metal','wood','ground','foliage','skin_cloth','cloth_metal','hair','mixed'):
        choices=[t for t in tasks if t['material']==material]
        if choices:selected.append(max(choices,key=lambda t:math.prod(t['source_size']) if max(t['source_size'])<=1024 else 0))
    tasks=selected

bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=1
scene.cycles.use_denoising=False;scene.cycles.use_light_tree=False
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
scene.render.image_settings.color_depth='8';scene.render.resolution_percentage=100
scene.render.filter_size=.6
scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
scene.view_settings.exposure=0;scene.view_settings.gamma=1
scene.render.film_transparent=False
scene.world.color=(0,0,0)
bpy.ops.mesh.primitive_plane_add(size=2)
plane=bpy.context.object;plane.name='Registered_UV_Atlas'
bpy.ops.object.camera_add(location=(0,0,2))
camera=bpy.context.object;camera.name='Atlas_Orthographic';camera.rotation_euler=(0,0,0)
camera.data.type='ORTHO';camera.data.ortho_scale=2;scene.camera=camera
library={}

def terrain_material():
    m=bpy.data.materials.new('New_temperate_zone_soil');m.use_nodes=True;n=m.node_tree.nodes;n.clear();l=m.node_tree.links
    uv=n.new('ShaderNodeTexCoord');offset=n.new('ShaderNodeVectorMath');offset.operation='ADD';l.new(uv.outputs['UV'],offset.inputs[0])
    scale=n.new('ShaderNodeVectorMath');scale.operation='MULTIPLY';scale.inputs[1].default_value=(3.5,7,1);l.new(offset.outputs[0],scale.inputs[0])
    tile=n.new('ShaderNodeTexImage');tile.image=bpy.data.images.load(str(ASSET/'source/material-earth.png'));tile.extension='REPEAT';l.new(scale.outputs[0],tile.inputs[0])
    normalize=n.new('ShaderNodeVectorMath');normalize.operation='MULTIPLY';normalize.inputs[1].default_value=tuple(json.loads((ASSET/'source/material-normalization.json').read_text())['earth']);l.new(tile.outputs['Color'],normalize.inputs[0])
    low=n.new('ShaderNodeVectorMath');low.operation='MAXIMUM';low.inputs[1].default_value=(.45,.45,.45);l.new(normalize.outputs[0],low.inputs[0])
    high=n.new('ShaderNodeVectorMath');high.operation='MINIMUM';high.inputs[1].default_value=(1.75,1.75,1.75);l.new(low.outputs[0],high.inputs[0])
    tone=n.new('ShaderNodeRGB');tone.name='Biome diffuse tint'
    mult=n.new('ShaderNodeMixRGB');mult.blend_type='MULTIPLY';mult.inputs[0].default_value=1;l.new(tone.outputs[0],mult.inputs[1]);l.new(high.outputs[0],mult.inputs[2])
    em=n.new('ShaderNodeEmission');l.new(mult.outputs[0],em.inputs[0]);out=n.new('ShaderNodeOutputMaterial');l.new(em.outputs[0],out.inputs[0])
    for i,o in enumerate(n):o.location=(i*230,0)
    return m,tone,offset

def material(kind):
    mat=bpy.data.materials.new('Wasteland_'+kind);mat.use_nodes=True;mat.use_fake_user=True
    n=mat.node_tree.nodes;n.clear();links=mat.node_tree.links
    def node(typ,name):
        o=n.new(typ);o.label=name;o.name=name;return o
    def link(out,inp):links.new(out,inp)
    def val(x):
        if hasattr(x,'node'):return x
        if isinstance(x,(tuple,list)):
            q=node('ShaderNodeRGB','Color');q.outputs[0].default_value=(*x[:3],1);return q.outputs[0]
        q=node('ShaderNodeValue','Value');q.outputs[0].default_value=x;return q.outputs[0]
    def math_(op,a,b=0):
        q=node('ShaderNodeMath',op);q.operation=op;link(val(a),q.inputs[0]);link(val(b),q.inputs[1]);return q.outputs[0]
    def mix(a,b,fac,mode='MIX',label='Layer'):
        q=node('ShaderNodeMixRGB',label);q.blend_type=mode;link(val(fac),q.inputs[0]);link(val(a),q.inputs[1]);link(val(b),q.inputs[2]);return q.outputs[0]
    def ramp(a,stops,label):
        q=node('ShaderNodeValToRGB',label);link(val(a),q.inputs[0]);r=q.color_ramp
        while len(r.elements)>2:r.elements.remove(r.elements[-1])
        for e,(position,color) in zip(r.elements,(stops[0],stops[-1])):e.position=position;e.color=(*color[:3],1)
        for position,color in stops[1:-1]:r.elements.new(position).color=(*color[:3],1)
        return q.outputs[0]
    uv=node('ShaderNodeTexCoord','Registered UV')
    seed=node('ShaderNodeVectorMath','Per-resource stable seed');seed.operation='ADD';link(uv.outputs['UV'],seed.inputs[0])
    def noise(scale,detail=3,rough=.65,stretch=None):
        q=node('ShaderNodeTexNoise','Material frequency '+str(scale));q.noise_dimensions='3D';q.inputs['Scale'].default_value=scale;q.inputs['Detail'].default_value=detail;q.inputs['Roughness'].default_value=rough
        v=seed.outputs[0]
        if stretch:
            s=node('ShaderNodeVectorMath','Directional manufacture');s.operation='MULTIPLY';s.inputs[1].default_value=stretch;link(v,s.inputs[0]);v=s.outputs[0]
        link(v,q.inputs['Vector']);return q.outputs['Fac']
    guide=node('ShaderNodeTexImage','Original UV color and lighting guide');guide.interpolation='Closest';guide.extension='EXTEND';link(uv.outputs['UV'],guide.inputs['Vector'])
    color=guide.outputs['Color'];bw=node('ShaderNodeRGBToBW','Original geometric shading');link(color,bw.inputs[0]);light=bw.outputs[0]
    split=node('ShaderNodeSeparateColor','Material color masks');split.mode='RGB';link(color,split.inputs[0]);r,g,b=[split.outputs[x] for x in ('Red','Green','Blue')]
    active=math_('MINIMUM',math_('MULTIPLY',light,7),1)
    # Manufactured materials retain their established material colors and
    # baked isometric shading, with new independently authored surface detail.
    fine=noise(270,2);broad=noise(8,4);mid=noise(42,3)
    strength={'masonry':.45,'metal':.36,'wood':.42,'ground':.38,'foliage':.18,'skin_cloth':.15,'cloth_metal':.30,'hair':.20,'mixed':.26}[kind]
    modulation=ramp(mid,[(0,(.60,.63,.60)),(.48,(.96,.96,.93)),(1,(1.2,1.17,1.10))],'New mesoscopic material')
    result=mix(color,modulation,strength,'MULTIPLY','Surface relief color')
    # Newly painted material library contributes actual surface color detail,
    # rather than relying on a generic noise pass on the original artwork.
    tile_name={'masonry':'plaster','metal':'steel','wood':'wood','ground':'earth','cloth_metal':'canvas','mixed':'steel','skin_cloth':'canvas'}.get(kind)
    if tile_name:
        detail_image=node('ShaderNodeTexImage','Newly painted '+tile_name+' albedo');detail_image.image=bpy.data.images.load(str(ASSET/'source'/('material-'+tile_name+'.png')),check_existing=True)
        detail_image.interpolation='Linear';detail_image.extension='REPEAT'
        detail_uv=node('ShaderNodeVectorMath','Real material detail density');detail_uv.operation='SCALE';detail_uv.inputs['Scale'].default_value=3.0 if kind in ('wood','ground','masonry') else 5.0;link(seed.outputs[0],detail_uv.inputs[0]);link(detail_uv.outputs[0],detail_image.inputs['Vector'])
        normalize=node('ShaderNodeVectorMath','Neutralize material average');normalize.operation='MULTIPLY';normalize.inputs[1].default_value=tuple(json.loads((ASSET/'source/material-normalization.json').read_text())[tile_name]);link(detail_image.outputs['Color'],normalize.inputs[0])
        amount=.48 if kind in ('wood','ground','masonry') else .36
        if kind=='skin_cloth':
            skinprotect=math_('MULTIPLY',math_('GREATER_THAN',r,math_('MULTIPLY',g,1.12)),math_('GREATER_THAN',g,math_('MULTIPLY',b,1.08)))
            amount=math_('MULTIPLY',math_('SUBTRACT',1,skinprotect),.35)
        result=mix(result,normalize.outputs[0],amount,'MULTIPLY','New authored material surface')
    micro=ramp(fine,[(0,(.62,.64,.65)),(1,(1.18,1.17,1.13))],'Microstructure')
    result=mix(result,micro,.12 if kind in ('metal','masonry','ground','wood') else .06,'MULTIPLY','Fine material pores')
    # Original dark crevices and silhouette backgrounds cannot be lifted by
    # procedural layers; alpha is restored exactly at native export.
    dust_factor=math_('MULTIPLY',math_('MAXIMUM',math_('SUBTRACT',broad,.56),0),active)
    dust_factor=math_('MULTIPLY',dust_factor,.13 if kind!='foliage' else .045)
    dust=mix(light,(.39,.34,.25),.25,'MULTIPLY','Dry mineral dust')
    result=mix(result,dust,dust_factor,label='Settled dust')
    if kind in ('masonry','ground'):
        vor=node('ShaderNodeTexVoronoi','Irregular mineral fissures');vor.feature='DISTANCE_TO_EDGE';vor.inputs['Scale'].default_value=26 if kind=='masonry' else 48;link(seed.outputs[0],vor.inputs['Vector'])
        crack=math_('LESS_THAN',vor.outputs['Distance'],.012)
        crack=math_('MULTIPLY',crack,math_('GREATER_THAN',broad,.6))
        crack=math_('MULTIPLY',crack,.16 if kind=='masonry' else .12)
        result=mix(result,(.36,.35,.32),crack,'MULTIPLY','Hairline mineral weathering')
    elif kind in ('metal','mixed','cloth_metal'):
        brushed=noise(58,2,stretch=(.13,7,1))
        scratch=math_('MULTIPLY',math_('GREATER_THAN',brushed,.73),math_('GREATER_THAN',broad,.53))
        result=mix(result,(1.24,1.25,1.24),math_('MULTIPLY',scratch,.20),'MULTIPLY','Sparse exposed metal scratches')
        rust=math_('MULTIPLY',math_('GREATER_THAN',r,math_('MULTIPLY',g,1.22)),math_('GREATER_THAN',g,math_('MULTIPLY',b,1.10)))
        rust=math_('MULTIPLY',rust,math_('MAXIMUM',math_('SUBTRACT',mid,.4),0))
        result=mix(result,(1.16,.78,.53),math_('MULTIPLY',rust,.28),'MULTIPLY','Layered oxide in existing worn metal')
    elif kind=='wood':
        grain=noise(45,3,stretch=(.18,8,1))
        wood=ramp(grain,[(0,(.52,.55,.55)),(.5,(1,1,.95)),(1,(1.22,1.16,1.03))],'Weathered wood fibres')
        result=mix(result,wood,.23,'MULTIPLY','Directional wood fibres')
        splitwood=math_('LESS_THAN',grain,.22)
        result=mix(result,(.4,.4,.35),math_('MULTIPLY',splitwood,.13),'MULTIPLY','Dry fibre splits')
    elif kind in ('cloth_metal','skin_cloth'):
        pass
    if kind in ('cloth_metal','skin_cloth'):
        wave=node('ShaderNodeTexWave','Woven fabric warp');wave.wave_type='BANDS';wave.bands_direction='X';wave.wave_profile='SIN';wave.inputs['Scale'].default_value=180;wave.inputs['Distortion'].default_value=1.2;link(seed.outputs[0],wave.inputs['Vector'])
        weave=ramp(wave.outputs['Fac'],[(0,(.82,.83,.80)),(1,(1.08,1.08,1.03))],'Thread weave')
        cloth_factor=.18
        if kind=='skin_cloth':
            skin=math_('MULTIPLY',math_('GREATER_THAN',r,math_('MULTIPLY',g,1.12)),math_('GREATER_THAN',g,math_('MULTIPLY',b,1.08)))
            skin=math_('MULTIPLY',skin,math_('GREATER_THAN',light,.10))
            cloth_factor=math_('MULTIPLY',math_('SUBTRACT',1,skin),.18)
            # Protect face/body coloration; no patina or scratches on skin.
            result=mix(result,color,skin,label='Protected skin coloration')
        result=mix(result,weave,cloth_factor,'MULTIPLY','Fabric thread relief')
    if kind=='foliage':
        leaf=math_('GREATER_THAN',g,math_('MULTIPLY',r,.95))
        variation=ramp(mid,[(0,(.73,.83,.58)),(.5,(1,1,1)),(1,(1.12,1.1,.94))],'Living and dry leaf variation')
        result=mix(result,variation,math_('MULTIPLY',leaf,.22),'MULTIPLY','Foliage material variation')
    if kind=='hair':
        strands=noise(85,2,stretch=(4,.12,1))
        variation=ramp(strands,[(0,(.53,.56,.56)),(1,(1.28,1.24,1.18))],'Individual hair fibres')
        result=mix(color,variation,.22,'MULTIPLY','Hair strands')
    emission=node('ShaderNodeEmission','Registered diffuse export');link(result,emission.inputs['Color']);emission.inputs['Strength'].default_value=1
    out=node('ShaderNodeOutputMaterial','Material export');link(emission.outputs[0],out.inputs['Surface'])
    # Arrange editable source graph into readable named columns.
    for i,o in enumerate(n):o.location=((i%9)*235,-(i//9)*190)
    mat['purpose']='Material-aware registered texture restoration; source silhouettes retained'
    library[kind]=(mat,guide,seed)
    return library[kind]

for kind in sorted({t['material'] for t in tasks}):material(kind)
terrain=terrain_material()
terrain[0].use_fake_user=True
if library_only:
    for kind,(mat,guide,seed) in library.items():
        t=max((t for t in tasks if t['material']==kind),key=lambda t:math.prod(t['source_size']))
        guide.image=bpy.data.images.load(str(ROOT/t['guide']),check_existing=True)
        guide.image.alpha_mode='STRAIGHT'
        h=int(t['id'][:8],16);seed.inputs[1].default_value=((h%137)/7,((h>>8)%131)/9,((h>>16)%127)/11)
    chosen=library.get('masonry',next(iter(library.values())))[0];plane.data.materials.append(chosen)
    for packed in bpy.data.images:
        if packed.source=='FILE' and not packed.packed_file:packed.pack()
    bpy.ops.wm.save_as_mainfile(filepath=str(ASSET/'source'/('target-and-masks-library.blend' if last_pair else 'wasteland-material-library.blend')))
    print(json.dumps(dict(passed=True,editable_materials=len(library)+1,packed_images=len(bpy.data.images),library_only=True)),flush=True)
    bpy.ops.wm.quit_blender()
records=[]
for index,t in enumerate([] if library_only else tasks):
    target=ASSET/'masters'/(t['id']+'.png')
    if target.exists() and '--force' not in args:
        print('SKIP',t['path'],flush=True);continue
    mat,guide,seed=library[t['material']]
    old=guide.image
    im=bpy.data.images.load(str(ROOT/t['guide']),check_existing=False);guide.image=im;im.alpha_mode='STRAIGHT'
    # Image node Color ignores alpha for procedural recoloring. Plane fills the
    # exact camera frame, including non-square texture canvases.
    h=int(t['id'][:8],16);seed.inputs[1].default_value=((h%137)/7,((h>>8)%131)/9,((h>>16)%127)/11)
    plane.data.materials.clear()
    if 'terrain_linear_rgb' in t:
        soil,tone,offset=terrain;tone.outputs[0].default_value=(*t['terrain_linear_rgb'],1);offset.inputs[1].default_value=seed.inputs[1].default_value;plane.data.materials.append(soil)
    else:plane.data.materials.append(mat)
    w,height=t['render_size'];plane.scale=(1,height/w,1);scene.render.resolution_x=w;scene.render.resolution_y=height
    camera.data.ortho_scale=2 if w>=height else 2*height/w
    scene.render.filepath=str(target);started=time.monotonic()
    bpy.ops.render.render(write_still=True)
    records.append(dict(path=t['path'],material=t['material'],render_size=t['render_size'],seconds=round(time.monotonic()-started,3)))
    print('TEXTURE',index+1,len(tasks),t['path'],flush=True)
    if old and old.users==0:bpy.data.images.remove(old)
    if index==0 or index==len(tasks)-1:
        for packed in bpy.data.images:
            if packed.source=='FILE' and not packed.packed_file:packed.pack()
        im.pack();bpy.ops.wm.save_as_mainfile(filepath=str(ASSET/'source'/('target-and-masks-library.blend' if last_pair else 'terrain-library.blend' if terrain_only else 'material-library-sample.blend' if sample else 'wasteland-material-library.blend')))

report=dict(passed=True,blender=bpy.app.version_string,rendered=len(records),sample=sample,records=records,
    registration='Original UV colors and geometric shading guide; new Blender material layers; exact alpha restored on export',
    source_geometry_modified=False,gameplay_modified=False)
if records and not library_only:
    (ASSET/'source'/('render-target-masks.json' if last_pair else 'render-terrain.json' if terrain_only else 'render-sample.json' if sample else 'render-active.json' if active_only else 'render.json')).write_text(json.dumps(report,indent=2))
if not library_only:print(json.dumps(dict(passed=True,rendered=len(records),sample=sample)),flush=True)
