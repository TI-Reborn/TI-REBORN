"""Import the original Assault4 three-flag SET scenes; no player data."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

from tools.import_arena_fragments import BASE,model_doors

ROOT=Path(__file__).resolve().parents[1]
STATIC_MODELS={*(f'ground_military_{i}.t' for i in range(1,7)),
    *(f'stone{i}.t' for i in (2,5,10,11,13,14,15,16))}


def read(path):
    source=path.read_bytes()
    raw=zlib.decompress(source[16:]) if source[:4]==b'\x03ZIP' else source
    if raw[:8]!=b'TI SET\0\2':raise ValueError('Unsupported native assault scene')
    if source[:4]==b'\x03ZIP' and len(raw)!=struct.unpack_from('<I',source,8)[0]:
        raise ValueError('Native ZIP length mismatch')
    w,h,count=struct.unpack_from('<3H',raw,12)
    if not 1<=w<=255 or not 1<=h<=255:raise ValueError('Invalid scene dimensions')
    end=32+2*w*h
    if len(raw)<end+72*count:raise ValueError('Truncated SET scene')
    models=[];flags=[];doors=[];hashes={}
    for i in range(count):
        record=raw[end+72*i:end+72*(i+1)]
        if record[0]>63:raise ValueError('Invalid native model name')
        name=record[1:1+record[0]].decode('ascii')
        x,y=struct.unpack_from('<ii',record,64);models.append([name,x,y])
        if name=='assault_flag.t':flags.append([x,y])
        if name in STATIC_MODELS:
            model=next((BASE/'setting').rglob(name));tile=model.read_bytes()
            if len(tile)!=428 or tile[:12]!=b'TI TILE\0\1\0\0\0':
                raise ValueError('Unexpected legacy static ground/rock record')
            # Pinned one-record legacy v0 ground/rocks. These contain no door
            # state; their movement/visibility footprint is in the SET grid.
            entries,digest=(),hashlib.sha256(tile).hexdigest()
        else:
            try:entries,digest=model_doors(name)
            except ValueError as error:raise ValueError('Unsupported native TILE '+name) from error
        if entries:hashes[name]=digest
        for door in entries:
            dx,dy=x+door['x'],y+door['y']
            if not 0<=dx<w or not 0<=dy<h or door['state'] not in (1,2):
                raise ValueError('Invalid native door')
            doors.append([dx,dy,door['state']==2])
    if len(flags)!=3 or len(set(map(tuple,flags)))!=3:raise ValueError('Expected three Assault4 flags')
    tiles=list(raw[32:end:2])
    if set(tiles)-{0,1,2,3,4}:raise ValueError('Unknown scene collision class')
    return dict(file=path.stem,width=w,height=h,tiles=tiles,models=models,flags=flags,
        doors=doors,door_models_sha256=hashes,sha256=hashlib.sha256(source).hexdigest())


if __name__=='__main__':
    scenes=[read(BASE/'maps/assault'/f'assault_map_{i:02}.s') for i in range(1,6)]
    (ROOT/'config/assault_maps.json').write_text(json.dumps(scenes,separators=(',',':'))+'\n')
    print(json.dumps(dict(original_scenes=len(scenes),flags_each=3,
        dimensions=[[v['width'],v['height']] for v in scenes],doors=[len(v['doors']) for v in scenes])))
