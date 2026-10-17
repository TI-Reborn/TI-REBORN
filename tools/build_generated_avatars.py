"""Package original AI portraits for the native 4096-byte JPEG protocol."""
import base64
import hashlib
import io
import json
import shutil
import sys
import zlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy.client_generated_avatars import patch
FOLDER=ROOT/'reports/generated-avatars-20261013'
LABELS=('Ветеран','Разведчик','Рейнджер','Медик','Боевой пёс','Шахтёр')


def build():
    metadata=json.loads((FOLDER/'prompts.json').read_text(encoding='utf-8'))
    inspected=json.loads((FOLDER/'inspection.json').read_text(encoding='utf-8'))
    config=json.loads(inspected['sources']['config/avatars.json']['text'])
    destination=FOLDER/'client/base/avatars';destination.mkdir(parents=True,exist_ok=True)
    source_dir=ROOT/'assets/generated-avatars-v1';source_dir.mkdir(parents=True,exist_ok=True)
    sheet=Image.new('RGB',(768,340),(24,28,25));draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
    proof=[]
    for identity,(meta,label) in enumerate(zip(metadata,LABELS),10007):
        source=source_dir/(meta['name']+'.png')
        shutil.copy2(meta['path'],source)
        with Image.open(source) as original:
            if original.width!=original.height:raise ValueError('Square avatar required')
            # Pure packaging resize; preserve generated composition/colors.
            image=original.convert('RGB').resize((64,64),Image.Resampling.LANCZOS)
            buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=90,optimize=True)
            blob=buffer.getvalue()
            assert len(blob)<=4096
            x=(identity-10007)*128
            sheet.paste(original.resize((120,120),Image.Resampling.LANCZOS),(x+4,8))
            draw.text((x+4,138),label,font=font,fill=(215,216,194))
            sheet.paste(image.resize((128,128),Image.Resampling.NEAREST),(x,174))
            draw.text((x+4,310),'64×64 / '+str(identity),font=font,fill=(215,216,194))
        (destination/f'avatar-{identity}.jpg').write_bytes(blob)
        row=dict(id=identity,name=label,premium=False,generated=True,crc32=zlib.crc32(blob),
                 asset=f'base/avatars/avatar-{identity}.jpg',jpeg_b64=base64.b64encode(blob).decode(),
                 source=source.relative_to(ROOT).as_posix(),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        config['avatars'].append(row)
        proof.append(dict(id=identity,name=label,size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),crc32=row['crc32']))
    config['policy']='Free emulator catalog: legacy client artwork in Premium; original generated portraits in Ordinary. All offers cost zero.'
    encoded=(json.dumps(config,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (ROOT/'config/avatars.json').write_bytes(encoded)
    candidate=FOLDER/'server-candidate/config';candidate.mkdir(parents=True,exist_ok=True)
    (candidate/'avatars.json').write_bytes(encoded)
    candidate=FOLDER/'server-candidate/tio';candidate.mkdir(parents=True,exist_ok=True)
    (candidate/'avatars.py').write_bytes((ROOT/'tio/avatars.py').read_text(encoding='utf-8').encode('utf-8'))
    (FOLDER/'client/silver.dll').write_bytes(patch((FOLDER/'silver-source.dll').read_bytes()))
    sheet.save(FOLDER/'preview.png')
    (FOLDER/'asset-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    (source_dir/'prompts.json').write_text(json.dumps([dict(name=r['name'],prompt=r['prompt'],tool='built-in image_gen') for r in metadata],indent=2),encoding='utf-8')
    print(json.dumps(dict(catalog_count=len(config['avatars']),generated=len(proof),sizes=[p['size'] for p in proof])))


if __name__=='__main__':build()
