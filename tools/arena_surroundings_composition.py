"""Compose decorative arena props at their original pixel size.

This compositor translates existing sprites. It never scales, rotates, shears,
or remaps their pixels. The exporter supplies the native ground underneath and
clips the final alpha to the non-playable ring.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from arena_surroundings_layout import build_layout

ROOT = Path(__file__).resolve().parents[1]
PALETTE = ROOT/'reports/arena-surroundings-implementation/native-prop-palette/palette.json'
SIDES = ('x_negative', 'y_negative', 'x_at_or_above_width', 'y_at_or_above_width')


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project(x, y):
    return 32 * (y - x), 16 * (x + y)


def paste_translated(canvas, sprite, xy):
    x, y = map(int, xy)
    left, top = max(0, x), max(0, y)
    right, bottom = min(canvas.width, x + sprite.width), min(canvas.height, y + sprite.height)
    if right <= left or bottom <= top:
        return
    canvas.alpha_composite(sprite.crop((left-x, top-y, right-x, bottom-y)), (left, top))


def source_path(record):
    value = record.get('path_rel_root') or record.get('raster')
    path = Path(value)
    path = (ROOT/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError('Palette raster must exist inside this workspace')
    return path


def opaque_world_extents(sprite, bbox):
    """Keep complete visible roofs/canopies outside the field before clipping."""
    yy, xx = np.nonzero(np.asarray(sprite.getchannel('A')) >= 16)
    if not len(xx):
        raise ValueError('Native prop has no visible pixels')
    px, py = xx + bbox[0], yy + bbox[1]
    wx, wy = py/32-px/64, py/32+px/64
    return (float(wx.min()),float(wx.max()),float(wy.min()),float(wy.max()))


def native_props(master_id, width, depth, full_size):
    raw = PALETTE.read_bytes()
    palette = json.loads(raw)
    records = list({r['id']:r for records in palette['masters'].values() for r in records}.values())
    records = [r for r in records if r.get('usable', True)]
    if not records:
        raise ValueError('No verified original props for '+master_id)
    prepared = []
    for record in records:
        if record['pixel_scale'] != [1, 1]:
            raise ValueError('Original prop raster must retain its pixel size')
        path = source_path(record)
        image = Image.open(path).convert('RGBA')
        bbox = record['screen_bbox']
        if image.size != (bbox[2]-bbox[0], bbox[3]-bbox[1]):
            raise ValueError('Palette raster and original pixel bbox differ')
        if record.get('raster_sha256') and sha(path) != record['raster_sha256']:
            raise ValueError('Palette raster changed')
        prepared.append((record, image, path, opaque_world_extents(image,bbox)))
    by_id = {p[0]['id']:p for p in prepared}
    def outside_origin(side, item, along, margin):
        xmin,xmax,ymin,ymax=item[3]
        if side == 'x_negative': return -math.ceil(xmax)-margin,along
        if side == 'y_negative': return along,-math.ceil(ymax)-margin
        if side == 'x_at_or_above_width': return width-math.floor(xmin)+margin,along
        return along,width-math.floor(ymin)+margin
    placements,layout_proof=build_layout(master_id,width,depth,by_id.get,outside_origin)
    canvas = Image.new('RGBA', full_size)
    instances = []
    for x, y, side, row, (record, sprite, path, extents), role, group in sorted(placements,
            key=lambda p: (p[3],p[0]+p[1]+sum(p[4][0]['world_footprint']),p[0],p[1])):
        xmin,xmax,ymin,ymax = extents
        assert (x+xmax <= -1 if side == 'x_negative' else
                y+ymax <= -1 if side == 'y_negative' else
                x+xmin >= width+1 if side == 'x_at_or_above_width' else y+ymin >= width+1)
        px, py = project(x, y)
        left = int(full_size[0]//2 + px + record['screen_bbox'][0])
        top = int(32*depth + py + record['screen_bbox'][1])
        paste_translated(canvas, sprite, (left, top))
        instances.append(dict(id=record['id'], side=side, row=row, world_origin=[x,y],
            role=role,group=group,
            canvas_origin=[left,top], raster=path.relative_to(ROOT).as_posix(),
            raster_sha256=sha(path), original_dimensions=list(sprite.size), pixel_scale=[1,1],
            source_sha256=record['source_sha256'],visible_alpha_threshold=16,
            source_opaque_world_extents=list(extents),
            whole_visible_prop_outside_game_before_clipping=True))
    building_count=sum(r['role']=='building' for r in instances)
    assert building_count<=6
    return canvas, dict(method='Original native city props in distinct functional groups at 1:1 pixel size',
        no_nonlinear_warp=True, native_prop_scale=[1,1], palette_sha256=hashlib.sha256(raw).hexdigest(),
        palette_path=PALETTE.relative_to(ROOT).as_posix(), instances=instances,
        four_sides=list(SIDES), rendering_resize=False,layout=layout_proof,
        large_building_count=building_count,unique_prop_types=len({r['id'] for r in instances}),
        layout_source=dict(path='tools/arena_surroundings_layout.py',sha256=sha(ROOT/'tools/arena_surroundings_layout.py')))


def canal_modules(width, depth, full_size):
    path = ROOT/'assets/arena-surroundings-v1/masters/R3-detail-bank.png'
    source = Image.open(path).convert('RGBA')
    pixels = np.asarray(source)
    # Register the measured top corner of the edited source. Its painted hole
    # is approximately isometric; do not reshape it to force exact geometry.
    # Straight sections and corners are copied at their original pixel size.
    source_origin = (893, 250)
    reference_width = 14
    yy, xx = np.mgrid[0:source.height, 0:source.width]
    sx, sy = xx-source_origin[0], yy-source_origin[1]
    wx, wy = sy/32-sx/64, sy/32+sx/64
    canvas = Image.new('RGBA', full_size)
    instances = []
    module_specs = [
        ('x_negative', (-7,2,3,11), (0,3)),
        ('y_negative', (3,11,-7,2), (3,0)),
        ('x_at_or_above_width', (12,21,3,11), (14,3)),
        ('y_at_or_above_width', (3,11,12,21), (3,14)),
    ]
    for side, bounds, origin in module_specs:
        mask = ((wx>=bounds[0]) & (wx<bounds[1]) & (wy>=bounds[2]) & (wy<bounds[3]))
        rows, cols = np.nonzero(mask & (pixels[:,:,3]>0))
        bbox = (int(cols.min()),int(rows.min()),int(cols.max()+1),int(rows.max()+1))
        module = pixels[bbox[1]:bbox[3],bbox[0]:bbox[2]].copy()
        module[:,:,3] = np.where(mask[bbox[1]:bbox[3],bbox[0]:bbox[2]],module[:,:,3],0)
        sprite = Image.fromarray(module)
        for along in range(-1,width+1,8):
            length = min(8,width+1-along)
            copied_bounds=list(bounds)
            loop_sprite=sprite
            if length<8:
                along_axis=wy if side.startswith('x_') else wx
                along_origin=origin[1] if side.startswith('x_') else origin[0]
                clipped=module.copy()
                clipped[:,:,3]=np.where(along_axis[bbox[1]:bbox[3],bbox[0]:bbox[2]]<along_origin+length,
                                        clipped[:,:,3],0)
                loop_sprite=Image.fromarray(clipped)
                copied_bounds[3 if side.startswith('x_') else 1]=along_origin+length
            if side == 'x_negative': target=(-3,along)
            elif side == 'y_negative': target=(along,-3)
            elif side == 'x_at_or_above_width': target=(width+3,along)
            else: target=(along,width+3)
            dx,dy = project(target[0]-origin[0],target[1]-origin[1])
            left = full_size[0]//2-source_origin[0]+bbox[0]+dx
            top = 32*depth-source_origin[1]+bbox[1]+dy
            paste_translated(canvas,loop_sprite,(left,top))
            instances.append(dict(side=side,source_bounds=list(bbox),source_world_bounds=copied_bounds,
                target_world_origin=list(target),canvas_origin=[left,top],pixel_scale=[1,1]))
    for cx,cy in ((0,0),(0,14),(14,0),(14,14)):
        bx=(-7,2) if cx==0 else (12,21)
        by=(-7,2) if cy==0 else (12,21)
        mask=(wx>=bx[0])&(wx<bx[1])&(wy>=by[0])&(wy<by[1])
        rows,cols=np.nonzero(mask & (pixels[:,:,3]>0))
        bbox=(int(cols.min()),int(rows.min()),int(cols.max()+1),int(rows.max()+1))
        module=pixels[bbox[1]:bbox[3],bbox[0]:bbox[2]].copy()
        module[:,:,3]=np.where(mask[bbox[1]:bbox[3],bbox[0]:bbox[2]],module[:,:,3],0)
        tx,ty=(-3 if cx==0 else width+3),(-3 if cy==0 else width+3)
        dx,dy=project(tx-cx,ty-cy)
        left=full_size[0]//2-source_origin[0]+bbox[0]+dx
        top=32*depth-source_origin[1]+bbox[1]+dy
        paste_translated(canvas,Image.fromarray(module),(left,top))
        instances.append(dict(side='corner',source_bounds=list(bbox),target_world_origin=[tx,ty],
            canvas_origin=[left,top],pixel_scale=[1,1]))
    return canvas,dict(method='Approved canal straight modules and corners translated at 1:1 pixel size',
        no_nonlinear_warp=True,native_prop_scale=[1,1],rendering_resize=False,
        approved_source=path.relative_to(ROOT).as_posix(),approved_source_sha256=sha(path),
        source_registration=dict(origin=list(source_origin),reference_width=reference_width,
                                 exact_geometry_preservation=False),
        four_sides=list(SIDES),canal_modules=instances)


def compose_native_ring(master_id, width, depth, full_size):
    if master_id == 'R3':
        canal, canal_proof = canal_modules(width,depth,full_size)
        props, prop_proof = native_props(master_id,width,depth,full_size)
        canal.alpha_composite(props)
        return canal, {**prop_proof, **canal_proof}
    return native_props(master_id,width,depth,full_size)
