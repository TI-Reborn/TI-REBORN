"""Validate the self-contained GLB package and render layers, then package it."""
import hashlib
import io
import json
import math
import shutil
import struct
import sys
import zipfile
from pathlib import Path
from PIL import Image,ImageStat

ROOT=Path(__file__).resolve().parents[1]
DETAILS_V2='--details-v2' in sys.argv
OUT=ROOT/('assets/hangar-wasteland-v2' if DETAILS_V2 else 'assets/hangar-wasteland-v1')


def glb(path):
    raw=path.read_bytes()
    assert raw[:4]==b'glTF' and struct.unpack_from('<II',raw,4)==(2,len(raw))
    length,kind=struct.unpack_from('<II',raw,12);assert kind==0x4e4f534a
    doc=json.loads(raw[20:20+length])
    at=20+length;n,kind=struct.unpack_from('<II',raw,at);assert kind==0x004e4942
    data=raw[at+8:at+8+n]
    assert len(data)==n and doc['buffers'][0]['byteLength']<=len(data)
    assert all('uri' not in image for image in doc.get('images',[]))
    for image in doc.get('images',[]):
        v=doc['bufferViews'][image['bufferView']]
        encoded=data[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']]
        with Image.open(io.BytesIO(encoded)) as im:im.verify()

    def accessor(index):
        a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']]
        fmt={5126:'f',5125:'I',5123:'H',5121:'B'}[a['componentType']]
        components={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[a['type']]
        size=struct.calcsize('<'+fmt*components)
        stride=v.get('byteStride',size);start=v.get('byteOffset',0)+a.get('byteOffset',0)
        assert start+(a['count']-1)*stride+size<=v.get('byteOffset',0)+v['byteLength']
        return [struct.unpack_from('<'+fmt*components,data,start+i*stride) for i in range(a['count'])]

    tris=0
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            assert primitive.get('mode',4)==4
            assert 'TEXCOORD_0' in primitive['attributes']
            pos=accessor(primitive['attributes']['POSITION'])
            assert all(math.isfinite(v) for xyz in pos for v in xyz)
            ids=[r[0] for r in accessor(primitive['indices'])]
            assert len(ids)%3==0 and max(ids)<len(pos)
            tris+=len(ids)//3
    animations=[]
    if DETAILS_V2 and path.name=='hangar-wasteland.glb':
        graffiti=[m for m in doc['materials'] if m.get('name')=='Graffiti_spray_RGBA']
        assert len(graffiti)==1
        assert graffiti[0].get('alphaMode') in ('BLEND','MASK'),graffiti
        assert 'baseColorTexture' in graffiti[0]['pbrMetallicRoughness']
        assert graffiti[0].get('doubleSided') is True
    for a in doc.get('animations',[]):
        channels=a['channels'];assert len(channels)==1
        target=doc['nodes'][channels[0]['target']['node']]['name']
        assert target==a['name'].replace('_Open_Close','_Hinge')
        times=accessor(a['samplers'][0]['input'])
        assert len(times)>2 and times[-1][0]>2.9
        animations.append({'name':a['name'],'target':target,'keys':len(times)})
    return {'path':path.relative_to(OUT).as_posix(),'bytes':len(raw),'meshes':len(doc['meshes']),
            'triangles':tris,'embedded_images':len(doc.get('images',[])),'animations':animations,
            'sha256':hashlib.sha256(raw).hexdigest()}


result={'full_scene':glb(OUT/'hangar-wasteland.glb'),
        'modules':[glb(p) for p in sorted((OUT/'modules').glob('*.glb'))]}
assert {a['name'] for a in result['full_scene']['animations']}=={'Door_A_Open_Close','Door_B_Open_Close'}
assert all(not m['animations'] for m in result['modules'])
metadata=json.loads((OUT/'model.json').read_text())
assert result['full_scene']['triangles']==metadata['total_triangles']
textures=[]
for path in sorted((OUT/'textures').glob('*.png')):
    with Image.open(path) as im:
        if path.name=='graffiti-atlas.png':
            assert DETAILS_V2 and im.mode=='RGBA' and im.getchannel('A').getextrema()==(0,255)
        else:assert im.size==(1024,1024)
        variance=ImageStat.Stat(im.convert('RGB')).var
        assert max(variance)>.00001,(path,variance)
        textures.append({'name':path.name,'size':list(im.size),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
assert len(textures)==(22 if DETAILS_V2 else 21),len(textures)
result['textures']=textures
layers=[]
for path in sorted((OUT/'isometric').glob('*.png')):
    with Image.open(path) as im:
        assert im.size==(740,600) and im.mode=='RGBA'
        alpha=im.getchannel('A');bounds=alpha.getbbox();assert bounds
        assert bounds[0]>0 and bounds[1]>0 and bounds[2]<740 and bounds[3]<600,(path,bounds)
        assert alpha.getextrema()==(0,255)
        layers.append({'name':path.name,'bounds':list(bounds),'common_origin':[384,240]})
assert len(layers)==(13 if DETAILS_V2 else 12),len(layers)
result['isometric_layers']=layers
blender=json.loads((OUT/'validation-blender.json').read_text());assert blender['passed']
assert (OUT/'hangar-wasteland.blend').stat().st_size>1_000_000
result.update(passed=True,scope='Source/GLB/PBR/PNG verification; no installation or game-client runtime claim')
(OUT/'validation-exports.json').write_text(json.dumps(result,indent=2)+'\n')
for name in ('hangar_wasteland_blender_20261021.py','validate_hangar_wasteland_blender_20261021.py',
             'validate_hangar_wasteland_exports_20261021.py','hangar_wasteland_details_20261021.py'):
    shutil.copyfile(ROOT/'tools'/name,OUT/'source'/name)
files=[p for p in sorted(OUT.rglob('*')) if p.is_file() and p.suffix!='.blend1' and '__pycache__' not in p.parts
       and p.name!='SHA256SUMS.txt']
(OUT/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(OUT).as_posix()+'\n' for p in files))
archive=OUT.with_suffix('.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in files+[OUT/'SHA256SUMS.txt']:z.write(p,Path(OUT.name)/p.relative_to(OUT))
print(json.dumps({'passed':True,'triangles':result['full_scene']['triangles'],'module_exports':len(result['modules']),
                  'door_clips':len(result['full_scene']['animations']),'texture_maps':len(textures),
                  'isometric_layers':len(layers),'archive':str(archive),'archive_bytes':archive.stat().st_size}))
