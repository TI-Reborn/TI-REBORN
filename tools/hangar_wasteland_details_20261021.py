"""Blender-native overgrowth, stains and transparent wall graffiti for v2."""
import math
import random
import bpy
from mathutils import Vector


def add_details(ctx):
    rng=random.Random(2187)
    cols=ctx['collections'];out=ctx['OUT'];modules=ctx['MODULES']
    start=ctx['module_start'];end=ctx['module_end'];finish=ctx['finish']
    solid=ctx['solid'];beam=ctx['beam'];box=ctx['box'];polygon=ctx['scrap_polygon']
    counts={'graffiti_decals':0,'grass_clumps':0,'bushes':0,'ivy_runs':0,'leaves':0,'moss_patches':0}
    col=bpy.data.collections.new('11_Vegetation');bpy.context.scene.collection.children.link(col);cols[col.name]=col
    leaf_mats=[solid('Leaf_olive',(.105,.15,.035),.94),
               solid('Leaf_dark_green',(.035,.085,.023),.97),
               solid('Leaf_dusty_sage',(.19,.23,.075),.96),
               solid('Leaf_dry_ochre',(.26,.20,.075),.99)]
    stem=solid('Dry_vine_bark',(.075,.055,.026),.99)
    moss=solid('Damp_moss',(.055,.085,.021),.99)
    grime=solid('Rain_runoff',(.065,.043,.019),1)

    def mesh(name,vertices,faces,indices,mats):
        data=bpy.data.meshes.new(name);data.from_pydata(vertices,[],faces);data.update()
        obj=bpy.data.objects.new(name,data);ctx['CURRENT'].objects.link(obj)
        finish(obj,name,mats[0])
        for material in mats[1:]:obj.data.materials.append(material)
        for face,index in zip(obj.data.polygons,indices):face.material_index=index
        return obj

    def leaf_geometry(verts,faces,ids,base,tip,width,mat):
        base,tip=Vector(base),Vector(tip);axis=tip-base
        lateral=axis.cross(Vector((0,0,1)))
        if lateral.length<.001:lateral=Vector((1,0,0))
        lateral.normalize();lateral*=width
        middle=base+axis*.48;ridge=middle+Vector((0,0,width*.20))
        at=len(verts)
        verts.extend([base,middle+lateral,tip,middle-lateral,ridge])
        faces.extend([(at,at+1,at+4),(at+1,at+2,at+4),(at+2,at+3,at+4),(at+3,at,at+4)])
        ids.extend([mat]*4);counts['leaves']+=1

    def leaf_cluster(name,center,radius,height,leaves=45):
        vertices=[];faces=[];ids=[]
        for i in range(leaves):
            a=rng.uniform(0,math.tau);r=radius*math.sqrt(rng.random())
            z=center[2]+height*rng.uniform(.18,.92)
            base=Vector((center[0]+math.cos(a)*r*.75,center[1]+math.sin(a)*r*.75,z))
            tip=base+Vector((math.cos(a),math.sin(a),rng.uniform(-.25,.7)))*rng.uniform(.12,.29)
            leaf_geometry(vertices,faces,ids,base,tip,rng.uniform(.035,.075),rng.choices(range(4),[4,4,3,1])[0])
        mesh(name,vertices,faces,ids,leaf_mats)

    def grass(x,y,z,height):
        vertices=[];faces=[];ids=[]
        for i in range(rng.randint(9,15)):
            a=rng.uniform(0,math.tau);r=rng.uniform(0,.10)
            base=Vector((x+math.cos(a)*r,y+math.sin(a)*r,z))
            h=height*rng.uniform(.5,1.2);lean=Vector((math.cos(a)*h*.4,math.sin(a)*h*.4,0))
            mid=base+Vector((0,0,h*.58))+lean*.25;tip=base+Vector((0,0,h))+lean
            side=Vector((-math.sin(a),math.cos(a),0))*rng.uniform(.009,.020)
            at=len(vertices);vertices.extend([base-side,base+side,mid+side*.55,tip,mid-side*.55])
            faces.extend([(at,at+1,at+2),(at,at+2,at+4),(at+4,at+2,at+3)])
            index=rng.choices(range(4),[4,3,3,3])[0];ids.extend([index]*3)
        mesh('Crack_grass',vertices,faces,ids,leaf_mats);counts['grass_clumps']+=1

    def curve(name,points,radius,material):
        data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D';data.resolution_u=1
        data.bevel_depth=radius;data.bevel_resolution=1
        spline=data.splines.new('POLY');spline.points.add(len(points)-1)
        for v,co in zip(spline.points,points):v.co=(*co,1)
        obj=bpy.data.objects.new(name,data);ctx['CURRENT'].objects.link(obj)
        bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
        bpy.ops.object.convert(target='MESH');return finish(bpy.context.object,name,material)

    # Independent atlas quadrants, with transparent overspray and no wall baked in.
    image=bpy.data.images.load(str(out/'textures/graffiti-atlas.png'));image.pack()
    decal=solid('Graffiti_spray_RGBA',(1,1,1),.99)
    shader=decal.node_tree.nodes.get('Principled BSDF')
    tex=decal.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image;tex.extension='CLIP'
    decal.node_tree.links.new(tex.outputs['Color'],shader.inputs['Base Color'])
    decal.node_tree.links.new(tex.outputs['Alpha'],shader.inputs['Alpha'])
    decal.surface_render_method='DITHERED'
    decal.use_backface_culling=False

    def graffiti(name,collection,center,u,width,height,quadrant):
        ctx['CURRENT']=cols[collection];start()
        center=Vector(center);u=Vector(u);v=Vector((0,0,1))
        coords=[center-u*width/2-v*height/2,center+u*width/2-v*height/2,
                center+u*width/2+v*height/2,center-u*width/2+v*height/2]
        obj=polygon(name,coords,decal)
        x,y=quadrant;uvs=[(x+.015,y+.015),(x+.485,y+.015),(x+.485,y+.485),(x+.015,y+.485)]
        for loop in obj.data.polygons[0].loop_indices:obj.data.uv_layers.active.data[loop].uv=uvs[loop]
        end(name,tuple(center),'graffiti');counts['graffiti_decals']+=1

    graffiti('Graffiti_Alive','03_Wall_B',(10.12,2.22,1.82),(0,1,0),2.05,1.42,(0,.5))
    graffiti('Graffiti_Warning','05_Wall_Right',(4.1,7.15,1.10),(-1,0,0),1.8,1.45,(.5,0))
    graffiti('Graffiti_Radiation','05_Wall_Right',(7.8,7.15,1.30),(-1,0,0),1.35,1.35,(0,0))
    graffiti('Graffiti_Wolf_Rear','02_Wall_A',(.875,2.25,1.65),(0,-1,0),1.85,1.7,(.5,.5))
    graffiti('Graffiti_Wolf_Side','04_Wall_Left',(5.05,.855,1.18),(1,0,0),1.55,1.45,(.5,.5))
    graffiti('Graffiti_Alive_Far','04_Wall_Left',(8.,.855,1.35),(1,0,0),1.75,1.35,(0,.5))

    # Wet streaks and moss sit on the actual wall/plinth surfaces.
    for y,collection in ((.86,'04_Wall_Left'),(7.145,'05_Wall_Right')):
        ctx['CURRENT']=cols[collection];start()
        for x in (1.6,2.45,3.8,5.9,6.65,8.6,9.55):
            w=rng.uniform(.025,.075);low=rng.uniform(.45,1.15)
            polygon('Old_runoff',[(x-w,y,1.97),(x+w,y,1.97),(x+w*.2,y,low),(x-w*.1,y,low+.13)],grime)
        for x in (1.9,3.6,6.4,8.85):
            coords=[(x-.5,y,.075),(x+.5,y,.075)]
            coords.extend((x+.5-i*.125,y,rng.uniform(.16,.43)) for i in range(9))
            polygon('Moss_on_concrete',coords,moss);counts['moss_patches']+=1
        end('Runoff_and_moss_'+collection,(5.5,y,0),'wall_weathering')

    # Plants stay within the original apron and outside both complete door arcs.
    ctx['CURRENT']=col;start()
    for y in (.46,7.55):
        for i in range(32):
            x=1.22+i*.276+rng.uniform(-.09,.09)
            grass(x,y+rng.uniform(-.16,.16),.015,rng.uniform(.19,.52))
    for x in (.43,10.57):
        for i in range(23):
            y=.6+i*.32
            if 2.95<y<5.15:continue
            grass(x+rng.uniform(-.10,.10),y,.015,rng.uniform(.2,.55))
    for x,y in ((2.05,1.2),(7.75,1.18),(9.3,1.2),(2.0,6.8),(7.5,6.8),(9.5,6.8)):
        grass(x,y,.10,.19)
    end('Apron_and_crack_grass',(5.5,4,0),'vegetation')

    ctx['CURRENT']=col
    for i,(x,y,r,h) in enumerate(((.45,1.55,.31,.72),(.48,6.92,.34,.87),(2.2,7.58,.35,.85),
                                 (8.4,7.64,.32,.8),(10.51,6.65,.33,.8),(10.55,1.75,.30,.65),
                                 (3.45,.42,.30,.7),(7.75,.41,.30,.62))):
        start()
        for j in range(7):
            a=rng.uniform(0,math.tau);tip=(x+math.cos(a)*r,y+math.sin(a)*r,h*rng.uniform(.65,1))
            curve('Woody_bush_stem',[(x,y,.02),(x+math.cos(a)*r*.3,y+math.sin(a)*r*.3,h*.5),tip],.008,stem)
        leaf_cluster('Weedy_bush',(x,y,.02),r,h,70)
        end('Bush_'+str(i+1),(x,y,0),'vegetation');counts['bushes']+=1

    def ivy(name,collection,points,normal):
        ctx['CURRENT']=cols[collection];start();curve('Ivy_main_stem',points,.012,stem)
        vertices=[];faces=[];ids=[];normal=Vector(normal)
        for a,b in zip(points,points[1:]):
            a,b=Vector(a),Vector(b)
            for j in range(6):
                origin=a+(b-a)*(j+.25)/6
                lateral=Vector((normal.y,-normal.x,0))*(1 if j%2 else -1)
                if lateral.length<.001:lateral=Vector((1 if j%2 else -1,0,0))
                end_point=origin+lateral*rng.uniform(.13,.30)+Vector((0,0,rng.uniform(-.06,.12)))
                end_point+=normal*.025
                curve('Ivy_branch',[origin,end_point],.004,stem)
                for t in (.25,.75):
                    base=origin+(end_point-origin)*t
                    tip=base+Vector((0,0,rng.uniform(.09,.16)))+lateral*.06+normal*.035
                    leaf_geometry(vertices,faces,ids,base,tip,rng.uniform(.035,.065),rng.choice((0,1,2)))
        mesh('Ivy_folded_leaves',vertices,faces,ids,leaf_mats)
        end(name,tuple(points[0]),'roof_growth' if collection=='06_Roof' else 'wall_growth')
        counts['ivy_runs']+=1

    ivy('Ivy_near_corner','05_Wall_Right',[(9.65,7.19,.10),(9.5,7.19,.7),(9.68,7.19,1.3),
         (9.42,7.19,1.9),(9.6,7.19,2.5),(9.25,7.19,3.13)],(0,1,0))
    ivy('Ivy_near_window','05_Wall_Right',[(6.15,7.19,.1),(5.95,7.19,.65),(6.2,7.19,1.2),
         (5.98,7.19,1.85),(6.32,7.19,2.5)],(0,1,0))
    ivy('Ivy_front_corner','03_Wall_B',[(10.19,6.8,.1),(10.19,6.65,.7),(10.19,6.85,1.4),
         (10.19,6.55,2.1),(10.19,6.75,2.95)],(1,0,0))
    ivy('Ivy_far_corner','04_Wall_Left',[(1.8,.81,.1),(2.0,.81,.7),(1.78,.81,1.45),
         (2.1,.81,2.2),(1.85,.81,3.05)],(0,-1,0))
    ivy('Ivy_rear_wall','02_Wall_A',[(.80,6.5,.1),(.80,6.65,.8),(.80,6.4,1.5),(.80,6.6,2.25)],(-1,0,0))
    ivy('Ivy_roof_edge','06_Roof',[(9.25,7.18,3.25),(9.0,6.65,3.32),(9.25,6.1,3.41),
         (8.9,5.65,3.49),(9.15,5.2,3.56)],(0,0,1))

    ctx['CURRENT']=col;start()
    for x,y in ((1.75,7.4),(2.4,.35),(8.9,7.7),(10.6,6.2),(6.1,.6)):
        for i in range(8):
            base=Vector((x+rng.uniform(-.22,.22),y+rng.uniform(-.16,.16),.016))
            tip=base+Vector((rng.uniform(.04,.10),rng.uniform(.03,.08),.008))
            vertices=[];faces=[];ids=[]
            leaf_geometry(vertices,faces,ids,base,tip,.025,3)
            mesh('Fallen_leaf',vertices,faces,ids,leaf_mats)
    end('Windblown_leaf_litter',(5.5,4,0),'vegetation')
    counts['added_mesh_modules']=len(modules)-31
    counts['atlas_texture']='textures/graffiti-atlas.png'
    counts['authoring']='Built-in image_gen transparent graffiti atlas; all plants/stems/leaves authored as Blender meshes'
    return counts
