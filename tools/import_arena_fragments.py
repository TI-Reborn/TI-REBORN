"""Import TI SET v2 (including ZIP) footprints, native doors and provenance."""
import hashlib,json,struct,sys,zlib
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASE=Path(r'C:\Program Files (x86)\TIOnline\base')

@lru_cache(maxsize=None)
def model_doors(name):
    from tools.read_tile_doors_native import read_doors
    path=next((BASE/'setting').rglob(name))
    # Legacy ground brushes and rocks are static scenery, not interactive doors.
    if path.read_bytes()[10]==0 and name in ('ground_military_2.t','ground_military_5.t','ground_military_6.t','stone2.t','stone5.t','stone7.t','stone16.t'):
        return (),hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        doors=read_doors(path)
    except ValueError:
        from tools.read_tile_doors_extended_native import read_doors as extended
        doors=extended(path)
    return doors,hashlib.sha256(path.read_bytes()).hexdigest()

def read_fragment(path):
    source=path.read_bytes()
    raw=zlib.decompress(source[16:]) if source[:4]==b'\x03ZIP' else source
    if source[:4]==b'\x03ZIP' and len(raw)!=struct.unpack_from('<I',source,8)[0]:
        raise ValueError('Compressed fragment length mismatch')
    if len(raw)<32 or raw[:8]!=b'TI SET\0\2':raise ValueError('Expected uncompressed TI SET v2')
    width,height,count=struct.unpack_from('<3H',raw,12)
    end=32+2*width*height
    if not width or not height or end+72*count>len(raw):raise ValueError('Truncated fragment')
    tiles=list(raw[32:end:2])
    models=[];containers=[];doors=[];door_models={}
    for i in range(count):
        record=raw[end+72*i:end+72*(i+1)]
        length=record[0]
        if length>63:raise ValueError('Invalid model name')
        models.append(record[1:1+length].decode('ascii'))
        x,y=struct.unpack_from('<ii',record,64)
        model_entries,digest=model_doors(models[-1])
        if digest:door_models[models[-1]]=digest
        for door in model_entries:
            dx,dy=x+door['x'],y+door['y']
            if not (0<=dx<width and 0<=dy<height) or door['state'] not in (1,2):
                raise ValueError('Invalid original door state or position')
            doors.append([dx,dy,door['state']==2])
        if models[-1] in ('item_steel_box_01.t','item_steel_box_01b.t'):
            x,y=struct.unpack_from('<ii',record,64)
            if not (0<=x<width and 0<=y<height):raise ValueError('Container outside fragment')
            containers.append([x,y])
    return dict(width=width,height=height,tiles=tiles,models=models,containers=containers,
                doors=doors,door_models_sha256=door_models,sha256=hashlib.sha256(source).hexdigest())

if __name__=='__main__':
    names={'shed_v1.s','outpost_v2.s','forest_tree_v01.s'}
    profiles=json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']
    for profile in profiles.values():
        if profile['enabled']:
            for category in ('houses','hangars','walls','cover','crates'):names.update(profile.get(category,[]))
            for pool in profile.get('pools',{}).values():names.update(pool)
    result=json.loads((ROOT/'config/arena_fragments.json').read_text())
    result.update({name:read_fragment(BASE/'maps'/name) for name in sorted(names)})
    for item in result.values():
        missing=[name for name in item['models'] if not list((BASE/'setting').rglob(name))]
        if missing:raise ValueError(f'Missing fragment models: {missing}')
    (ROOT/'config/arena_fragments.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Imported',[(k,v['width'],v['height']) for k,v in result.items()])
