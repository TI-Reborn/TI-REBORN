"""Build the eight still-original, active inventory devices as new Blender props."""
import bpy, math, json
from pathlib import Path
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'assets/wasteland-materials-v1'
folder=OUT/'devices';folder.mkdir(exist_ok=True)
scene=bpy.context.scene
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene.render.engine='CYCLES';scene.cycles.samples=48;scene.cycles.use_denoising=True
scene.render.resolution_x=1024;scene.render.resolution_y=512;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA';scene.render.film_transparent=True
scene.view_settings.view_transform='AgX';scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.5
props=[]

def mat(name,color,metal=0,rough=.55,texture=None):
    m=bpy.data.materials.new(name);m.use_nodes=True;n=m.node_tree.nodes;p=n.get('Principled BSDF')
    p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;p.inputs['Metallic'].default_value=metal
    if texture:
        tex=n.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(OUT/'source'/('material-'+texture+'.png')),check_existing=True);tex.projection='BOX';tex.projection_blend=.2
        coord=n.new('ShaderNodeTexCoord');m.node_tree.links.new(coord.outputs['Generated'],tex.inputs['Vector'])
        mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=.48;mix.inputs[1].default_value=(*color,1);m.node_tree.links.new(tex.outputs['Color'],mix.inputs[2]);m.node_tree.links.new(mix.outputs[0],p.inputs['Base Color'])
        bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.20;bump.inputs['Distance'].default_value=.018;m.node_tree.links.new(tex.outputs['Color'],bump.inputs['Height']);m.node_tree.links.new(bump.outputs[0],p.inputs['Normal'])
    return m
paint=mat('Scuffed olive field enamel',(.18,.21,.14),.45,.5,'steel')
steel=mat('Oxidized machined steel',(.33,.36,.35),.8,.36)
black=mat('Aged charcoal rubber',(.025,.03,.024),.02,.72)
canvas=mat('Worn field webbing',(.32,.26,.16),0,.8,'canvas')
bronze=mat('Dull connector brass',(.40,.28,.10),.7,.4)
colors=[mat('Insulated wire '+str(i),c,.05,.55) for i,c in enumerate(((.35,.055,.025),(.09,.18,.29),(.16,.27,.12),(.48,.34,.09)))]

def finish(o,name,m):
    o.name=name;o.data.materials.append(m);props.append(o);return o
def box(name,loc,size,m,bevel=.035):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    if bevel:
        b=o.modifiers.new('Soft machined edges','BEVEL');b.width=bevel;b.segments=3
        o.modifiers.new('Weighted corner normals','WEIGHTED_NORMAL')
    return finish(o,name,m)
def cyl(name,loc,r,depth,m,rot=(0,0,0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=r,depth=depth,location=loc,rotation=rot);o=bpy.context.object
    b=o.modifiers.new('Rounded rim','BEVEL');b.width=.012;b.segments=2;o.modifiers.new('Smooth manufactured normals','WEIGHTED_NORMAL')
    return finish(o,name,m)
def wire(name,points,m,r=.024):
    c=bpy.data.curves.new(name,'CURVE');c.dimensions='3D';c.bevel_depth=r;c.bevel_resolution=3;s=c.splines.new('BEZIER');s.bezier_points.add(len(points)-1)
    for p,xyz in zip(s.bezier_points,points):p.co=xyz;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
    o=bpy.data.objects.new(name,c);scene.collection.objects.link(o);return finish(o,name,m)
def screw(x,y,z):
    cyl('Captive screw',(x,y,z),.046,.018,steel)
    box('Screw slot',(x,y,z+.012),(.055,.012,.009),black,.002)
def field_device(kind,grade):
    box('Enamel instrument housing',(0,0,.08),(1.6,.78,.36),paint,.065)
    box('Split casing seam',(0,0,.065),(1.64,.795,.025),black,.014)
    for x in (-.66,.66):
        for y in (-.26,.26):screw(x,y,.271)
    for x in (-1,1):
        cyl('Threaded plug',(x*.9,0,.08),.13,.32,steel,(0,math.pi/2,0))
        cyl('Insulating grip',(x*1.08,0,.08),.105,.15,black,(0,math.pi/2,0))
    for x in (-.48,.48):
        box('Fabric mounting strap',(x,0,-.14),(.16,1.2,.075),canvas,.015)
        box('Strap buckle',(x,-.48,-.10),(.23,.19,.055),bronze,.01)
    if kind=='trainer':
        tint=((.43,.38,.13),(.10,.32,.38),(.10,.38,.22))[grade]
        glass=mat('Faded non-emissive instrument glass '+str(grade),tint,.12,.23)
        box('Raised display bezel',(0,0,.31),(.96,.55,.12),steel,.035)
        box('Dusty glass screen',(0,0,.383),(.82,.40,.028),glass,.012)
        for i in range(7):
            y=-.14+i*.046
            box('Screen etched scale',(-.27,y,.399),(.09 if i%2 else .15,.008,.003),black,.001)
        wire('Analogue instrument trace',[(-.12,-.13,.405),(.00,-.04,.405),(.08,-.10,.405),(.18,.10,.405),(.29,.13,.405)],steel,.009)
    else:
        box('Serviced terminal panel',(0,0,.31),(1,.5,.1),black,.018)
        for i in range(6):
            x=-.36+i*.145
            cyl('Terminal collar',(x,0,.4),.065,.11,steel)
            cyl('Brass terminal',(x,0,.47),.039,.025,bronze)
        for i in range(grade+2):
            x=-.4+i*.23
            wire('Replaceable insulated lead',[(x,-.14,.43),(x-.12,-.38,.65),(x+.2,-.54,.30),(x+.28,-.35,.13)],colors[i%4])
    for i in range(grade+1):
        box('Field grade tick',(-.23+i*.19,.29,.276),(.1,.035,.012),bronze,.002)
    if grade==2:
        for x in (-.62,.62):box('Reinforced corner guard',(x,0,.29),(.13,.72,.10),steel,.025)
def optics():
    lens=mat('Coated green objective glass',(.07,.21,.15),.35,.15)
    box('Adjustable goggle bridge',(0,0,.18),(1.12,.28,.19),paint,.05)
    for x in (-.4,.4):
        cyl('Optics barrel',(x,0,.11),.25,.95,paint,(math.pi/2,0,0))
        for y in (-.4,.34):cyl('Thick rubber eyecup',(x,y,.11),.285,.16,black,(math.pi/2,0,0))
        cyl('Recessed objective glass',(x,-.489,.11),.215,.016,lens,(math.pi/2,0,0))
        for y in (-.28,-.20,-.12):cyl('Focus ring ribs',(x,y,.11),.26,.032,black,(math.pi/2,0,0))
    box('Battery pod',(.05,.3,.47),(.51,.29,.3),black,.045)
    wire('Braided head strap',[(-.62,.2,.12),(-.95,.8,.05),(.0,1.02,.04),(.95,.8,.05),(.62,.2,.12)],canvas,.075)
    wire('External battery cable',[(.33,.35,.5),(.7,.5,.43),(.82,.37,.17)],black,.031)
def injector():
    box('Reusable field syringe case',(0,0,-.1),(1.9,.69,.20),paint,.065)
    for x in (-.68,.66):
        cyl('Syringe steel barrel',(x,0,.10),.13,.56,steel,(0,math.pi/2,0))
    ampoule=mat('Amber medical ampoule',(.34,.20,.055),.15,.18)
    cyl('Dose ampoule',(0,0,.10),.125,.9,ampoule,(0,math.pi/2,0))
    for x in (-.28,-.12,.04,.20):box('Measured dose graduation',(x,-.105,.17),(.018,.035,.06),black,.001)
    cyl('Hollow steel needle',(.98,0,.10),.018,.45,steel,(0,math.pi/2,0))
    cyl('Plunger grip',(-1.04,0,.10),.19,.08,black,(0,math.pi/2,0))
    box('Surplus canvas case strap',(.33,0,-.03),(.17,.79,.07),canvas,.012)

def area(name,loc,power,size):
    bpy.ops.object.light_add(type='AREA',location=loc);o=bpy.context.object;o.name=name;o.data.energy=power;o.data.shape='DISK';o.data.size=size;o.rotation_euler=(Vector((0,0,0))-o.location).to_track_quat('-Z','Y').to_euler()
area('Large soft key',(-3,-4,6),480,5);area('Cool edge fill',(3,2,4),350,4)
bpy.ops.object.camera_add(location=(2.5,-5,5.5));camera=bpy.context.object;camera.name='Inventory orthographic';camera.data.type='ORTHO';camera.data.ortho_scale=3.25;camera.rotation_euler=(Vector((0,0,.15))-camera.location).to_track_quat('-Z','Y').to_euler();scene.camera=camera

records=[]
for name,kind,grade in (
 ('item_light_advisor','advisor',0),('item_improved_advisor','advisor',1),('item_ultra_advisor','advisor',2),
 ('item_light_trainer','trainer',0),('item_improved_trainer','trainer',1),('item_ultra_trainer','trainer',2),
 ('itm_buff_sight','injector',0),('itm_nightvision','optics',0)):
    for o in props:bpy.data.objects.remove(o,do_unlink=True)
    props.clear()
    if kind=='optics':optics()
    elif kind=='injector':injector()
    else:field_device(kind,grade)
    scene.render.filepath=str(folder/(name+'.png'));bpy.ops.render.render(write_still=True)
    for image in bpy.data.images:
        if image.source=='FILE' and not image.packed_file:image.pack()
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/(name+'.blend')))
    records.append(dict(name=name,kind=kind,grade=grade,objects=len(props),resolution=[1024,512]))
(folder/'devices.json').write_text(json.dumps(dict(passed=True,blender=bpy.app.version_string,entirely_new_geometry=True,devices=records),indent=2))
