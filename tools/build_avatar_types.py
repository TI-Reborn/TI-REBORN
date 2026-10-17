"""Extract female silhouette, dog and miner portraits from original atlases."""
import argparse,base64,hashlib,io,json,sys,zlib
from pathlib import Path
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def build(original):
    from deploy.client_avatar_types import patch
    folder=ROOT/'reports/avatar-types';destination=folder/'client/base/avatars';destination.mkdir(parents=True,exist_ok=True)
    prior=json.loads((folder/'inspection.json').read_text(encoding='utf-8'))['sources']['config/avatars.json']['text']
    config=json.loads(prior)
    specifications=((10004,'Женский силуэт','base/pda/avatars.PNG',(40,0,80,40)),
                    (10005,'Собака','base/pda/ts_npc_icons.png',(2,131,148,256)),
                    (10006,'Шрек','base/pda/ts_npc_icons.png',(152,131,298,256)))
    for identity,label,name,box in specifications:
        source=original/name
        with Image.open(source) as image:
            image=image.crop(box).convert('RGBA')
            image=ImageOps.pad(image,(64,64),method=Image.Resampling.LANCZOS,color=(18,18,18,255))
            backdrop=Image.new('RGBA',image.size,(18,18,18,255));image=Image.alpha_composite(backdrop,image).convert('RGB')
            buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=85,optimize=True)
        blob=buffer.getvalue();assert len(blob)<=4096
        (destination/f'avatar-{identity}.jpg').write_bytes(blob)
        config['avatars'].append(dict(id=identity,name=label,crc32=zlib.crc32(blob),asset=f'base/avatars/avatar-{identity}.jpg',jpeg_b64=base64.b64encode(blob).decode(),original=name,original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),original_crop=list(box)))
    encoded=(json.dumps(config,ensure_ascii=False,indent=2)+'\n').encode()
    (ROOT/'config/avatars.json').write_bytes(encoded)
    (folder/'server-candidate/config').mkdir(parents=True,exist_ok=True)
    (folder/'server-candidate/config/avatars.json').write_bytes(encoded)
    (folder/'resource-proof.json').write_text(json.dumps({'original_dependencies':{r['original']:r['original_sha256'] for r in config['avatars']}},indent=2))
    (folder/'client/silver.dll').write_bytes(patch((folder/'silver-source.dll').read_bytes()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True);build(p.parse_args().original)
