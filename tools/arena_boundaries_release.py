"""Strict offline client-only boundary release predicates; no network or writes."""
from collections import Counter
import hashlib
import io
import re
import struct
from pathlib import PurePosixPath

OLD='2026.10.07.2'
NEW='2026.10.07.3'
SCENE_PATTERN=r'base/maps/as_(rv|de|ny|mz)_([1-3])_(38|57)\.s'
RESOURCE_PATTERN=r'base/setting/arena_boundaries/ab_(rv|de|ny|mz)_a_(38|57)_p([0-9]{4})\.(t|png)'


def require(value,message):
    if not value:raise RuntimeError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def records(manifest):
    require(manifest.get('schema')==1 and isinstance(manifest.get('files'),list),'Invalid launcher manifest')
    result={};folded=set()
    for r in manifest['files']:
        p=r['path'];path=PurePosixPath(p)
        require(path.as_posix()==p and not path.is_absolute() and '..' not in path.parts and
            '\\' not in p and ':' not in p and p.lower() not in folded and
            re.fullmatch('[a-f0-9]{64}',r['sha256']) and type(r['size']) is int and 0<=r['size']<=512*1024*1024,
            'Unsafe/duplicate launcher record')
        result[p]=r;folded.add(p.lower())
    return result


def allow_addition(path):return re.fullmatch(RESOURCE_PATTERN,path) is not None


def allow_scene_replacement(path):return re.fullmatch(SCENE_PATTERN,path) is not None


def manifest_delta(before,after,additions,replacements):
    require(before['version']==OLD and after['version']==NEW,'Unexpected boundary release versions')
    a,b=records(before),records(after)
    require(len(a)==6218 and set(a)<=set(b),'Existing client record deleted')
    added=set(b)-set(a);changed={p for p in a if a[p]!=b[p]}
    expected={p for p in a if allow_scene_replacement(p)}
    require(len(expected)==24 and changed==expected==set(replacements),'Only all 24 original SET records may change')
    require(bool(added) and added==set(additions) and all(allow_addition(p) for p in added),'Unsafe/missing boundary addition')
    require({p[:-2] for p in added if p.endswith('.t')}=={p[:-4] for p in added if p.endswith('.png')},'Unpaired boundary TILE/PNG')
    require({re.fullmatch(RESOURCE_PATTERN,p).group(1,2) for p in added}==
            {(city,size) for city in ('rv','de','ny','mz') for size in ('38','57')},'All eight approved rings required')
    for p in changed:
        require(b[p]==replacements[p] and {k:v for k,v in a[p].items() if k not in ('size','sha256')}==
                {k:v for k,v in b[p].items() if k not in ('size','sha256')},'Existing SET metadata changed')
    for p in added:require(b[p]==additions[p] and set(b[p])=={'path','size','sha256'},'New resource metadata differs')
    require({k:v for k,v in before.items() if k not in ('version','news','files')}==
            {k:v for k,v in after.items() if k not in ('version','news','files')},'Launcher metadata changed')
    return dict(changed_scene_records=24,new_resource_records=len(added),unchanged_existing_records=6194,
        existing_records_preserved=6218,legacy_records_preserved=5090,b1_tiles_preserved=552,source_pngs_preserved=552,
        unique_rings=8,scene_variants=24,existing_record_paths_preserved=True)


def scene_records(raw):
    require(raw[:9]==b'TI SET\0\x02\0' and len(raw)>=34,'Expected uncompressed native SET v2')
    w,h,count=struct.unpack_from('<3H',raw,12)
    require((w,h)==(1,1) and struct.unpack_from('<H',raw,18)[0]==2 and raw[20:24]==bytes(4) and
            raw[32:34]==bytes(2) and len(raw)==34+72*count,'Boundary SET geometry/cells differ')
    result=[]
    for index in range(count):
        r=raw[34+72*index:34+72*(index+1)];n=r[0]
        require(0<n<=63 and r[n+1:64]==bytes(63-n),'Invalid SET model shortstring')
        name=r[1:1+n].decode('ascii');x,y=struct.unpack_from('<ii',r,64)
        require(re.fullmatch('[A-Za-z0-9_.-]+\\.t',name),'Unsafe SET model name')
        result.append(dict(basename=name,x=x,y=y))
    return result


def scene_append(path,old,new,resources):
    match=re.fullmatch(SCENE_PATTERN,path);require(match is not None,'Unexpected replacement SET')
    city,variant,size=match.groups();size=int(size)
    before,after=scene_records(old),scene_records(new)
    require(len(after)>len(before) and new[:16]==old[:16] and new[18:34]==old[18:34] and
            new[34:34+72*len(before)]==old[34:],'Original SET cells/record order/header changed')
    appended=after[len(before):]
    originals={r['basename']:r for r in before}
    model_paths=set()
    for r in appended:
        p='base/setting/arena_boundaries/'+r['basename'];m=re.fullmatch(RESOURCE_PATTERN,p)
        require(m is not None and m.group(1)==city and int(m.group(2))==size and m.group(4)=='t' and p in resources,
                'Boundary scene references foreign/unlisted resource')
        require(0<=r['x']<size and 0<=r['y']<size,'Boundary anchor extends game grid')
        index=m.group(3);source=f'as_{city}_{variant}_{size}_p{index}.t'
        require(source in originals and (r['x'],r['y'])==(originals[source]['x'],originals[source]['y']),
                'Boundary anchor differs from the corresponding original foreground patch')
        model_paths.add(p)
    counts=Counter((r['x'],r['y']) for r in after)
    require(max(counts.values())<=255,'Native foreground attachment limit exceeded')
    return dict(path=path,old_sha256=sha(old),sha256=sha(new),models=appended,
                city=city,size=size,variant=int(variant),old_model_count=len(before),new_model_count=len(after),
                max_models_per_anchor=max(counts.values()),model_paths=sorted(model_paths))


def boundary_tile(path,raw):
    match=re.fullmatch(RESOURCE_PATTERN,path)
    require(match is not None and path.endswith('.t') and len(raw)==544 and raw[:8]==b'TI TILE\0',
            'Expected a new uncompressed boundary TILE544')
    require(struct.unpack_from('<II',raw,52)==(0x00b1b1b1,255),'Boundary foreground must remain B1/255')
    from tools.verify_hosted_arena_surroundings import validate_tile_blob
    normalized=bytearray(raw);normalized[52:55]=b'\xff\xff\xff'
    record=validate_tile_blob(bytes(normalized))
    require(record['texture']==PurePosixPath(path).name[:-2]+'.png','Foreign boundary PNG reference')
    return record


def boundary_png(raw):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        require(image.format=='PNG' and image.mode=='RGBA' and image.size==(1024,1024),'Boundary PNG must be full-frame RGBA1024')
        image.load()
        return dict(dimensions=list(image.size),mode=image.mode,rgba_sha256=sha(image.tobytes()),alpha_extrema=list(image.getchannel('A').getextrema()))


def ring_alpha(size,models,tiles,pngs,depth):
    """Reconstruct actual foreground alpha with the native -32 X correction."""
    from PIL import Image
    require(depth=={38:24,57:36}[size],'Boundary canvas must inherit the current surroundings depth')
    width,height=64*(size+2*depth),32*(size+2*depth)
    canvas=Image.new('RGBA',(width,height))
    for model in models:
        info=tiles[model['basename']];offset=info['screen_offset']
        point=(width//2+32*(model['y']-model['x'])-32+offset[0],
               32*depth+16*(model['x']+model['y'])+offset[1])
        with Image.open(io.BytesIO(pngs[info['texture']])) as image:canvas.alpha_composite(image,point)
    alpha=canvas.getchannel('A').tobytes();hole=outside=0
    sides={key:0 for key in ('x_negative','y_negative','x_at_or_above_width','y_at_or_above_width')}
    corners={key:0 for key in ('x_negative_y_negative','x_negative_y_positive','x_positive_y_negative','x_positive_y_positive')}
    def interval(row,low,high):
        first=max(0,(low+width)//2);last=min(width,(high+width-1)//2+1)
        return row[first:max(first,last)]
    negative=(-128*depth,-1);inside=(0,128*size-1);positive=(128*size,128*(size+depth)-1)
    regions=((negative,inside),(inside,negative),(positive,inside),(inside,positive),
             (negative,negative),(negative,positive),(positive,negative),(positive,positive))
    totals=dict.fromkeys(tuple(sides)+tuple(corners),0)
    for y in range(height):
        row=alpha[y*width:(y+1)*width];radius=64*size-2*abs(2*y+1-height)
        if radius>=0:
            pixels=interval(row,-radius,radius);hole+=len(pixels)-pixels.count(b'\0')
        outer=width-2*abs(2*y+1-height)
        for pixels in (interval(row,-width,-outer-1),interval(row,outer+1,width)):
            outside+=len(pixels)-pixels.count(b'\0')
        sy2=2*y+1-64*depth
        for label,(xr,yr) in zip(totals,regions):
            pixels=interval(row,max(2*sy2-xr[1],yr[0]-2*sy2),min(2*sy2-xr[0],yr[1]-2*sy2))
            totals[label]+=len(pixels)-pixels.count(b'\0')
    require(hole==0 and outside==0,'Boundary alpha covers playable ground or escapes its original outer diamond')
    require(all(totals.values()),'A boundary side/corner has no visible pixels')
    return dict(passed=True,hole_nonzero_pixels=hole,outside_nonzero_pixels=outside,
        four_sides={k:totals[k] for k in sides},four_corners={k:totals[k] for k in corners},
        rgba_sha256=sha(canvas.tobytes()),canvas_dimensions=[width,height],depth=depth,
        renderer_x_correction=-32)
