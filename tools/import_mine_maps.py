"""Import original full 60x60 mine scenes; keep resource basenames unchanged."""
from pathlib import Path
import hashlib,json,struct

ROOT=Path(__file__).resolve().parents[1]
BASE=Path(r'C:\Program Files (x86)\TIOnline\base')


def read(path):
    raw=path.read_bytes()
    if raw[:8]!=b'TI SET\0\2':raise ValueError('Unsupported mine format')
    w,h,n=struct.unpack_from('<3H',raw,12)
    if (w,h)!=(60,60):raise ValueError('Unexpected original mine dimensions')
    end=32+w*h*2; models=[]
    for i in range(n):
        r=raw[end+72*i:end+72*(i+1)]
        name=r[1:1+r[0]].decode('ascii');x,y=struct.unpack_from('<ii',r,64)
        models.append([name,x,y])
    tiles=list(raw[32:end:2])
    if set(tiles)-{0,1,2,3,4}:raise ValueError('Unknown mine collision class')
    return dict(file=path.stem,width=w,height=h,tiles=tiles,models=models,sha256=hashlib.sha256(raw).hexdigest())


if __name__=='__main__':
    maps=[read(BASE/'maps/mines_01'/f'mine_{i:02}.s') for i in range(1,21)]
    (ROOT/'config/mine_maps.json').write_text(json.dumps(maps,separators=(',',':'))+'\n')
    print('Imported 20 original 60x60 mine scenes')
