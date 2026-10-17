"""Compile the approved low A boundaries in native isometric coordinates.

Native sprites are translated at 1:1. Concrete is a small code-native mesh
with original material texels; nothing scales, mirrors or warps a sprite.
Only new noninteractive foreground models are appended to the existing SETs.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from arena_surroundings_native import encode_tile
from arena_surroundings_composition import paste_translated, opaque_world_extents

OUT = ROOT/'assets/arena-boundaries-v1'
OVERLAY = OUT/'client-overlay'
REPORTS = ROOT/'reports/arena-boundaries-implementation'
PREVIOUS = REPORTS/'previous-client-manifest.json'
OLD_OVERLAY = ROOT/'assets/arena-surroundings-v2/client-overlay'
PALETTE = OUT/'native-palette/palette.json'
OLD_PALETTE = ROOT/'reports/arena-surroundings-implementation/native-prop-palette/palette.json'
TOWNS = ('rv', 'de', 'ny', 'mz')
SIDE_NAMES = ('x_negative', 'y_negative', 'x_at_or_above_width', 'y_at_or_above_width')
CORNER_NAMES = ('origin', 'x', 'y', 'opposite')
PATCH = 1024
DEPTHS = {38:24,57:36}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def project(x, y, z=0):
    return 32*(y-x), 16*(x+y)-z


def world_pixels(width):
    depth=DEPTHS[width]
    fw = (2*width+4*depth)*32
    fh = fw//2
    yy, xx = np.indices((fh, fw), dtype=np.float32)
    px, py = xx+.5-fw/2, yy+.5-32*depth
    return fw, fh, py/32-px/64, py/32+px/64


def side_point(side, along, normal, width):
    return ((-normal, along), (along, -normal),
            (width+normal, along), (along, width+normal))[side]


def sprite_path(record):
    relative = record.get('raster') or record.get('path_rel_root')
    path = (ROOT/relative).resolve()
    assert path.is_relative_to(ROOT) and path.is_file()
    if record.get('raster_sha256'):
        assert sha(path.read_bytes()) == record['raster_sha256']
    return path


def native_sprite(record):
    path = sprite_path(record)
    with Image.open(path) as image:
        sprite = image.convert('RGBA')
    bbox = record['screen_bbox']
    assert sprite.size == (bbox[2]-bbox[0], bbox[3]-bbox[1])
    return sprite, bbox


def load_palette():
    value = json.loads(PALETTE.read_bytes())
    records = value.get('models', {})
    if isinstance(records, list):
        records = {r['id']: r for r in records}
    return value, records


def material_patch():
    """Choose an opaque original concrete face patch, without a resize."""
    palette = json.loads(OLD_PALETTE.read_bytes())
    record = palette['models']['concrete_wall_01.t']
    sprite, _ = native_sprite(record)
    a = np.asarray(sprite)
    best = None
    for y in range(0, a.shape[0]-16, 4):
        for x in range(0, a.shape[1]-32, 4):
            part = a[y:y+16, x:x+32]
            opacity = np.count_nonzero(part[:, :, 3] >= 220)
            rgb = part[:, :, :3].astype(float)
            # An old grey face, rather than the silhouette or black shadow.
            score = opacity - abs(float(rgb.mean())-125)*.2
            if best is None or score > best[0]:
                best = (score, x, y, part.copy())
    _, x, y, patch = best
    assert np.count_nonzero(patch[:, :, 3] >= 200) >= 500
    patch[:, :, 3] = 255
    return patch, dict(source=record['source_path'], source_sha256=record['source_sha256'],
        raster=record['raster'], raster_sha256=record['raster_sha256'],
        source_crop=[x, y, x+32, y+16], source_pixel_scale=[1, 1],
        purpose='Original concrete texels on new low geometric curb faces')


class Mesh:
    """Orthographic low geometry; all positions are exact world coordinates."""
    def __init__(self, width, material):
        self.width = width
        self.depth=DEPTHS[width]
        self.fw = (2*width+4*self.depth)*32
        self.fh = self.fw//2
        self.canvas = Image.new('RGBA', (self.fw, self.fh))
        self.material = material
        self.moss = None
        self.faces = []

    def p(self, xyz):
        px, py = project(*xyz)
        return round(px+self.fw/2), round(py+32*self.depth)

    def face(self, vertices, factor=1., marking=False, moss=False):
        points = [self.p(v) for v in vertices]
        x0 = max(0, min(p[0] for p in points))
        y0 = max(0, min(p[1] for p in points))
        x1 = min(self.fw, max(p[0] for p in points)+1)
        y1 = min(self.fh, max(p[1] for p in points)+1)
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new('L', (x1-x0, y1-y0))
        ImageDraw.Draw(mask).polygon([(x-x0, y-y0) for x, y in points], fill=255)
        yy, xx = np.indices((y1-y0, x1-x0))
        raw = self.material[(yy+y0)%16, (xx+x0)%32].copy()
        rgb = np.clip(raw[:, :, :3].astype(float)*factor, 0, 255)
        if marking:
            stripe = ((xx+x0+2*(yy+y0))//9)%2 == 0
            # Worn caution paint belongs to this new geometric material.
            rgb[stripe] = rgb[stripe]*.45+np.array([165, 145, 64])*.55
        if moss and self.moss is not None:
            forest = self.moss[(yy+y0)%32,(xx+x0)%32]
            amount = forest[:,:,3:4].astype(float)/255*.7
            rgb = rgb*(1-amount)+forest[:,:,:3]*amount
        raw[:, :, :3] = rgb.astype(np.uint8)
        raw[:, :, 3] = np.asarray(mask)
        self.canvas.alpha_composite(Image.fromarray(raw), (x0, y0))
        self.faces.append(dict(world_vertices=vertices, screen_vertices=points,
                               shading=factor, caution_paint=marking))

    def box(self, x0, y0, x1, y1, height, marking=False, base=0, factor=1.):
        # Back faces first, top last. All four sides retain the same light.
        self.face([(x0,y0,base),(x1,y0,base),(x1,y0,height),(x0,y0,height)], .73*factor)
        self.face([(x0,y0,base),(x0,y1,base),(x0,y1,height),(x0,y0,height)], .82*factor)
        self.face([(x0,y1,base),(x1,y1,base),(x1,y1,height),(x0,y1,height)], .87*factor, marking)
        self.face([(x1,y0,base),(x1,y1,base),(x1,y1,height),(x1,y0,height)], .68*factor, marking)
        self.face([(x0,y0,height),(x1,y0,height),(x1,y1,height),(x0,y1,height)], 1.14*factor, marking)


def concrete_ring(town, width, material):
    mesh = Mesh(width, material)
    outer, inner = (1.02, .5) if town == 'rv' else (1.685, .875)
    height = 4 if town == 'rv' else 7
    elements = []
    for side in range(4):
        for along in range(width):
            # Narrow joints; differently shaded blocks avoid a flat solid line.
            a0, a1 = along+.018, along+1-.018
            n0, n1 = inner, outer
            rect = ((-n1,a0,-n0,a1),(a0,-n1,a1,-n0),
                    (width+n0,a0,width+n1,a1),(a0,width+n0,a1,width+n1))[side]
            marked = town == 'mz' and along%5 == 1
            factor = (1., .97, 1.025, .99, 1.015)[(along+side*2)%5]
            mesh.box(*rect, height, marking=marked, factor=factor)
            elements.append(dict(side=SIDE_NAMES[side], along=along, world_rect=rect,
                height_pixels=height, role='concrete_curb', caution_paint=marked))
        if town == 'mz':
            # Low old steel rail, below the scale of an actor's ankles.
            for along in range(1, width, 5):
                x, y = side_point(side, along+.5, 1.3, width)
                mesh.box(x-.035,y-.035,x+.035,y+.035,13,factor=.6)
                elements.append(dict(side=SIDE_NAMES[side], along=along+.5,
                    height_pixels=13, role='low_rail_post'))
            start, end = side_point(side, .35, 1.3, width), side_point(side, width-.35, 1.3, width)
            # A thin continuous horizontal rail is an actual 3D prism.
            if side in (0, 2):
                mesh.box(start[0]-.02,start[1],start[0]+.02,end[1],11,base=9.5,factor=.68)
            else:
                mesh.box(start[0],start[1]-.02,end[0],start[1]+.02,11,base=9.5,factor=.68)
    for x, y, corner in ((-outer,-outer,'origin'),(width+inner,-outer,'x'),
                         (-outer,width+inner,'y'),(width+inner,width+inner,'opposite')):
        mesh.box(x,y,x+outer-inner,y+outer-inner,height,marking=town=='mz')
        elements.append(dict(corner=corner, role='concrete_corner_cap', height_pixels=height))
    return mesh.canvas, dict(method='New low orthographic mesh with original concrete material texels',
        material_texel_scale=[1,1], sprite_transform=None, projection='32*(y-x),16*(x+y)-height',
        faces=mesh.faces, instances=elements)


def native_ring(town, width, records):
    if town=='de':
        return forest_ring(width,records)
    return sidewalk_ring(width,records)


def paste_native(canvas, record, x, y, width, instances, **details):
    sprite,bbox=native_sprite(record)
    px,py=project(x,y)
    origin=(round(px+canvas.width/2+bbox[0]),round(py+32*DEPTHS[width]+bbox[1]))
    paste_translated(canvas,sprite,origin)
    instances.append(dict(id=record['id'],raster=record['raster'],
        raster_sha256=record['raster_sha256'],world_origin=[x,y],
        canvas_origin=list(origin),source_bbox=bbox,pixel_scale=[1,1],**details))


def forest_ring(width,records):
    source=OUT/'generated-stones/sprites.json'
    proof=json.loads(source.read_bytes());assert proof['passed'] and not proof['per_axis_stretch']
    prepared=[]
    for record in proof['sprites']:
        assert record['affine_scale_xy'][0]==record['affine_scale_xy'][1]
        sprite,bbox=native_sprite(record)
        prepared.append((record,sprite,bbox,opaque_world_extents(sprite,bbox)))
    fw=(2*width+4*DEPTHS[width])*32
    canvas=Image.new('RGBA',(fw,fw//2));instances=[];placements=[]
    for side in range(4):
        for step in range(math.ceil(width/.65)):
            record,sprite,bbox,extent=prepared[(step*7+side*3)%16]
            xmin,xmax,ymin,ymax=extent
            along=min(width-.2,step*.65+.2)
            jitter=(0,.125,.0625,.1875)[(step+side)%4]
            if side==0:x,y=-xmax-.25-jitter,along-(ymin+ymax)/2
            elif side==1:x,y=along-(xmin+xmax)/2,-ymax-.25-jitter
            elif side==2:x,y=width-xmin+.25+jitter,along-(ymin+ymax)/2
            else:x,y=along-(xmin+xmax)/2,width-ymin+.25+jitter
            placements.append((record,sprite,bbox,x,y,dict(side=SIDE_NAMES[side],along=along)))
    for index,(cx,cy,label) in enumerate(((0,0,'origin'),(width,0,'x'),(0,width,'y'),(width,width,'opposite'))):
        record,sprite,bbox,(xmin,xmax,ymin,ymax)=prepared[(index*5+2)%16]
        x=-xmax-.25 if cx==0 else width-xmin+.25
        y=-ymax-.25 if cy==0 else width-ymin+.25
        placements.append((record,sprite,bbox,x,y,dict(corner=label)))
    for record,sprite,bbox,x,y,detail in sorted(placements,key=lambda p:project(p[3],p[4])[1]):
        px,py=project(x,y)
        origin=(round(px+fw/2+bbox[0]),round(py+32*DEPTHS[width]+bbox[1]))
        paste_translated(canvas,sprite,origin)
        instances.append(dict(id=record['id'],raster=record['raster'],raster_sha256=record['raster_sha256'],
            native_pixel_scale=[1,1],uniform_atlas_scale=record['uniform_source_scale'],
            world_origin=[x,y],canvas_origin=list(origin),**detail))
    return canvas,dict(method='Sixteen generated low mossy fieldstone/fern sprites, compiled with equal axis scale, native rendering at1:1',
        source_atlas_sha256=proof['source_atlas_sha256'],sprite_compiler_proof_sha256=sha(source.read_bytes()),
        native_sprites_unscaled=True,mirror=False,instances=instances)


def sidewalk_ring(width,records):
    fw=(2*width+4*DEPTHS[width])*32
    canvas=Image.new('RGBA',(fw,fw//2))
    instances=[]
    orientations=('DL','DR','UR','UL')
    normals=((.75,2.75,-3),(1.75,3.75,-4),(-.75,1.25,width+1),(.25,2.25,width))
    for side in range(4):
        for cell in range(-1,width+1):
            orientation=orientations[side]
            sewer=cell%9==4
            name='ny_sidewalk_'+('sewers_' if sewer else '')+orientation+'.t'
            record=records[name]
            sprite,bbox=native_sprite(record)
            pixels=np.asarray(sprite).copy()
            yy,xx=np.indices((sprite.height,sprite.width))
            sx,sy=xx+.5+bbox[0],yy+.5+bbox[1]
            wx,wy=sy/32-sx/64,sy/32+sx/64
            normal,tangent=(wx,wy) if side in (0,2) else (wy,wx)
            n0,n1,origin=normals[side]
            # Only this native tangent interval is registration-compatible on
            # all four planes. Other atlas lengths have different silhouettes.
            t0=3
            mask=(normal>=n0)&(normal<n1)&(tangent>=t0)&(tangent<t0+1)
            pixels[~mask]=0
            cropped=Image.fromarray(pixels)
            x,y=(origin,cell-t0) if side in (0,2) else (cell-t0,origin)
            px,py=project(x,y)
            point=(round(px+fw/2+bbox[0]),round(py+32*DEPTHS[width]+bbox[1]))
            paste_translated(canvas,cropped,point)
            instances.append(dict(id=record['id'],source=record['source_path'],
                raster_sha256=record['raster_sha256'],side=SIDE_NAMES[side],world_origin=[x,y],
                native_roi=dict(normal=[n0,n1],tangent=[t0,t0+1]),
                native_pixel_scale=[1,1],sprite_transform=None,sewer=sewer))
    corners=(('down',-5,-6,0,0,'origin'),('right',width+1,-7,width,0,'x'),
             ('left',-6,width,0,width,'y'),('up',width+1,width,width,width,'opposite'))
    for orientation,x,y,cx,cy,label in corners:
        record=records[f'ny_sidewalk_corner_{orientation}.t']
        sprite,bbox=native_sprite(record)
        pixels=np.asarray(sprite).copy()
        yy,xx=np.indices((sprite.height,sprite.width))
        sx,sy=xx+.5+bbox[0],yy+.5+bbox[1]
        wx,wy=sy/32-sx/64+x,sy/32+sx/64+y
        # Exact small corner ROI; no giant original paving platform is pasted.
        mask=(np.abs(wx-cx)<=2.25)&(np.abs(wy-cy)<=2.25)
        mask &= ~((wx>-.25)&(wx<width+.25)&(wy>-.25)&(wy<width+.25))
        pixels[~mask]=0
        px,py=project(x,y)
        paste_translated(canvas,Image.fromarray(pixels),
            (round(px+fw/2+bbox[0]),round(py+32*DEPTHS[width]+bbox[1])))
        instances.append(dict(id=record['id'],source=record['source_path'],
            raster_sha256=record['raster_sha256'],corner=label,world_origin=[x,y],
            native_pixel_scale=[1,1],sprite_transform=None,roi_max_world_distance=2.25))
    return canvas,dict(method='Original sidewalk curb planes and four native corner orientations, cropped in exact world space',
        native_sprites_unscaled=True,mirror=False,instances=instances,
        straight_stride_world_cells=1,minimum_ground_distance_cells=.25,
        maximum_ground_distance_cells=2.25)


def clip_and_check(image, width):
    fw, fh, wx, wy = world_pixels(width)
    depth=DEPTHS[width]
    assert image.size == (fw, fh)
    raw = np.asarray(image).copy()
    hole = (wx>=0)&(wx<=width)&(wy>=0)&(wy<=width)
    outer = (wx>=-depth)&(wx<=width+depth)&(wy>=-depth)&(wy<=width+depth)
    raw[hole|~outer] = 0
    alpha = raw[:,:,3]
    counts = {}
    for index, name in enumerate(SIDE_NAMES):
        normal = (-wx,-wy,wx-width,wy-width)[index]
        along = (wy,wx,wy,wx)[index]
        # Every 1-cell section must contain visible boundary pixels close to
        # the line. This samples objects, not an unrelated opaque terrain band.
        mask = (normal>0)&(normal<2.5)&(along>=0)&(along<width)&(alpha>=64)
        occupied = np.bincount(np.floor(along[mask]).astype(np.int32),minlength=width).tolist()
        assert min(occupied)>0, (width,name,'Boundary contains an empty cell')
        counts[name] = dict(visible_pixels=sum(occupied), cells=width,
                           minimum_visible_pixels_per_cell=min(occupied))
    corners = {}
    for x, y, name in ((0,0,'origin'),(width,0,'x'),(0,width,'y'),(width,width,'opposite')):
        mask = (np.abs(wx-x)<2.5)&(np.abs(wy-y)<2.5)&~hole
        count = int(np.count_nonzero(alpha[mask]>=64))
        assert count>0, (width,name,'Missing corner')
        corners[name] = dict(visible_pixels=count)
    assert not np.any(raw[hole]) and not np.any(raw[~outer])
    return Image.fromarray(raw), dict(passed=True,hole_nonzero_pixels=0,
        outside_nonzero_pixels=0, four_sides=counts, four_corners=corners,
        method='Independent inverse projection at each pixel center; every boundary cell checked',
        height_scope='Only visible image pixels; gameplay hole contains no border pixels')


def export_ring(town, width, image, composition):
    image, alpha_proof = clip_and_check(image,width)
    fw, fh = image.size
    depth=DEPTHS[width]
    oldscene=(OLD_OVERLAY/f'base/maps/as_{town}_1_{width}.s').read_bytes()
    slots={}
    for index in range((len(oldscene)-34)//72):
        offset=34+index*72
        name=oldscene[offset+1:offset+1+oldscene[offset]].decode('ascii')
        x,y=struct.unpack_from('<ii',oldscene,offset+64)
        tile=(OLD_OVERLAY/'base/setting/arena_surroundings'/name).read_bytes()
        sx,sy=struct.unpack_from('<hh',tile,48)
        cx=32*(y-x)+sx-32+fw//2
        cy=16*(x+y)+sy+32*depth
        assert (cx,cy) not in slots and cx%PATCH==cy%PATCH==0
        slots[(cx,cy)]=(x,y,sx,sy,name,tile)
    models, files = [], []
    for cy in range(0, fh, PATCH):
        for cx in range(0, fw, PATCH):
            cut = image.crop((cx,cy,min(fw,cx+PATCH),min(fh,cy+PATCH)))
            if not cut.getchannel('A').getbbox():
                continue
            assert (cx,cy) in slots,'No existing foreground under boundary patch'
            x,y,sx,sy,oldname,oldtile=slots[(cx,cy)]
            patch_index=re.search(r'_p(\d{4})\.t$',oldname).group(1)
            basename = f'ab_{town}_a_{width}_p{patch_index}'
            folder = OVERLAY/'base/setting/arena_boundaries'
            folder.mkdir(parents=True,exist_ok=True)
            texture = Image.new('RGBA',(PATCH,PATCH))
            texture.paste(cut,(0,0))
            png = folder/(basename+'.png')
            texture.save(png)
            # Match the underlying old patch's exact anchor and screen box.
            # Both native foreground iteration branches sort attachments by
            # record index within a cell. Appended markers therefore overlay
            # the old art without relying on another cell or camera position.
            assert (cx,cy) in slots,'No existing foreground under boundary patch'
            x,y,sx,sy,oldname,oldtile=slots[(cx,cy)]
            raw = bytearray(encode_tile(basename+'.png',PATCH,PATCH,sx,sy,render_type=1))
            struct.pack_into('<I',raw,52,0x00b1b1b1)
            for start,end in ((28,74),(334,356),(539,544)):
                assert raw[start:end]==oldtile[start:end],'Native foreground geometry/flags drift'
            tile = folder/(basename+'.t')
            tile.write_bytes(raw)
            models.append(dict(basename=basename+'.t',x=x,y=y,texture_basename=basename+'.png',
                screen_offset=[sx,sy],canvas_origin=[cx,cy],texture_dimensions=[PATCH,PATCH],
                matched_underlay_model=oldname, matched_underlay_sha256=sha(oldtile),
                native_model_sha256=sha(raw),alpha_nonzero_pixels=int(np.count_nonzero(np.asarray(texture)[:,:,3]))))
            for path in (png,tile):
                data = path.read_bytes()
                files.append(dict(path=path.relative_to(OVERLAY).as_posix(),size=len(data),sha256=sha(data)))
    assert models and len(models)<255
    # Reconstruct using decoded TILE and SET placement rather than trusting
    # the source canvas. Full-frame1024 UVs and minus32 are fixed by native proof.
    rebuilt = Image.new('RGBA',(fw,fh))
    for model in models:
        raw = (OVERLAY/'base/setting/arena_boundaries'/model['basename']).read_bytes()
        sx,sy = struct.unpack_from('<hh',raw,48)
        px = 32*(model['y']-model['x'])+sx-32+fw//2
        py = 16*(model['x']+model['y'])+sy+32*depth
        texture = Image.open(OVERLAY/'base/setting/arena_boundaries'/model['texture_basename']).convert('RGBA')
        paste_translated(rebuilt,texture,(px,py))
    assert rebuilt.tobytes()==image.tobytes()
    preview = REPORTS/'ring-previews'/f'ab_{town}_a_{width}.png'
    preview.parent.mkdir(parents=True,exist_ok=True)
    image.save(preview)
    # No player bitmap is published. Viewport images are clearly offline art.
    viewports = []
    for side in range(4):
        wx,wy = side_point(side,width/2,0,width)
        px,py = project(wx,wy)
        box = (round(px+fw/2)-256,round(py+32*depth)-128,
               round(px+fw/2)+256,round(py+32*depth)+128)
        path = REPORTS/'ring-previews'/f'ab_{town}_a_{width}_{SIDE_NAMES[side]}.png'
        image.crop(box).save(path)
        viewports.append(dict(side=SIDE_NAMES[side],path=path.relative_to(ROOT).as_posix(),
                              dimensions=[512,256],source='Offline asset canvas, not a game screenshot'))
    return dict(town=town,width=width,canvas_width=fw,canvas_height=fh,depth=depth,
        models=models, alpha_proof=alpha_proof, composition=composition,viewports=viewports,
        render_proof=dict(full_uv=True,rgba_reconstruction_equal=True,sprite_scale=[1,1],
                          constant_tint='00b1b1b1',native_alpha=255,
                          exact_underlay_anchors_offsets_and_culling=True,
                          order='Appended model indices at same cell as underlying old nonoverlapping patch')), files


def append_scene(raw, models):
    assert raw[:8]==b'TI SET\0\x02' and raw[32:34]==b'\0\0'
    count = struct.unpack_from('<H',raw,16)[0]
    assert len(raw)==34+count*72
    result = bytearray(raw)
    struct.pack_into('<H',result,16,count+len(models))
    for model in models:
        name = model['basename'].encode('ascii')
        assert 0<len(name)<=63
        result.extend(bytes([len(name)])+name+bytes(63-len(name)))
        result.extend(struct.pack('<ii',model['x'],model['y']))
    assert result[:16]==raw[:16] and result[18:len(raw)]==raw[18:]
    assert result[len(raw):] and len(result)==34+(count+len(models))*72
    return bytes(result)


def main():
    baseline = json.loads(PREVIOUS.read_bytes())
    assert baseline['version']=='2026.10.07.2'
    by_path = {r['path']:r for r in baseline['files']}
    palette, records = load_palette()
    material, material_proof = material_patch()
    rings, files, scenes = [], [], []
    for town in TOWNS:
        for width in (38,57):
            if town in ('rv','mz'):
                canvas, composition = concrete_ring(town,width,material)
                composition['material']=material_proof
            else:
                canvas, composition = native_ring(town,width,records)
            ring, inventory = export_ring(town,width,canvas,composition)
            rings.append(ring);files.extend(inventory)
            for variant in (1,2,3):
                relative = f'base/maps/as_{town}_{variant}_{width}.s'
                old = (OLD_OVERLAY/relative).read_bytes()
                assert sha(old)==by_path[relative]['sha256'] and len(old)==by_path[relative]['size']
                new = append_scene(old,ring['models'])
                path = OVERLAY/relative
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(new)
                files.append(dict(path=relative,size=len(new),sha256=sha(new)))
                counts=Counter(struct.unpack_from('<ii',new,34+i*72+64) for i in range((len(new)-34)//72))
                assert max(counts.values())<=255
                scenes.append(dict(path=relative,old_sha256=sha(old),sha256=sha(new),
                    old_count=(len(old)-34)//72,new_count=(len(new)-34)//72,
                    models=[{key:m[key] for key in ('basename','x','y')} for m in ring['models']],
                    old_records_and_cells_preserved=True, max_models_per_anchor=max(counts.values())))
    assert len(rings)==8 and len(scenes)==24
    actual={p.relative_to(OVERLAY).as_posix() for p in OVERLAY.rglob('*') if p.is_file()}
    assert actual=={r['path'] for r in files}
    proof=dict(schema='arena-approved-boundaries/v1',passed=True,version='2026.10.07.3',
        previous_version='2026.10.07.2',selected_option='A',towns=list(TOWNS),
        previous_manifest_sha256=sha(PREVIOUS.read_bytes()),files=sorted(files,key=lambda r:r['path']),
        scenes=scenes,rings=rings, palette_sha256=sha(PALETTE.read_bytes()),
        source_tint_proof_sha256=sha((ROOT/'reports/arena-surroundings-fog/native-fog-tint.json').read_bytes()),
        gameplay_geometry_changed=False,interactive_models=False,existing_pngs_and_tiles_changed=False,
        source_code_sha256=sha(Path(__file__).read_bytes()),
        scope='Four approved A boundaries, all3 variants per city,38/57, all4 sides/corners')
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'boundary-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(dict(passed=True,rings=8,scenes=24,files=len(files),version=proof['version'])))


if __name__=='__main__':
    main()
