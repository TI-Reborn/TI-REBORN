"""Prepare three original-resource portraits; never modify installed game files."""
import argparse,base64,hashlib,io,json,zlib,sys
from pathlib import Path
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def build(original):
    from deploy.client_avatars import patch
    folder=ROOT/'reports/avatars';destination=folder/'client/base/avatars';destination.mkdir(parents=True,exist_ok=True)
    rows=[]
    for identity,(name,label) in enumerate((('ack_avatar_raider_male_random.jpg','Рейдер'),('ack_avatar_sc.jpg','Spectra Crystals'),('ack_avatar_scjamm.jpg','Spectra Crystals — сигнал')),10001):
        source=original/'base/quest/data'/name
        with Image.open(source) as image:
            image=ImageOps.fit(image,(64,64),centering=(.5,.15)) if identity==10001 else ImageOps.pad(image,(64,64),color=(10,10,10))
            buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=85,optimize=True)
        blob=buffer.getvalue();assert len(blob)<=4096
        (destination/f'avatar-{identity}.jpg').write_bytes(blob)
        rows.append(dict(id=identity,name=label,crc32=zlib.crc32(blob),asset=f'base/avatars/avatar-{identity}.jpg',jpeg_b64=base64.b64encode(blob).decode(),original=f'base/quest/data/{name}',original_sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    config=dict(version=1,price=0,policy='Free emulator catalog derived from original client art; IDs and price are emulator choices, not recovered historical offers.',avatars=rows)
    encoded=(json.dumps(config,ensure_ascii=False,indent=2)+'\n').encode()
    (ROOT/'config/avatars.json').write_bytes(encoded)
    (folder/'server-candidate/config/avatars.json').write_bytes(encoded)
    (folder/'resource-proof.json').write_text(json.dumps({'original_dependencies':{r['original']:r['original_sha256'] for r in rows}},indent=2))
    (folder/'client/silver.dll').write_bytes(patch((folder/'silver-source.dll').read_bytes()))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--original',type=Path,required=True);build(parser.parse_args().original)
