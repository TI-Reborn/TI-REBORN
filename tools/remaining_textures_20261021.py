"""Inventory original installer art; prepare UV-safe Blender material restoration.

Only byte-identical, still-published original resources are eligible. Original
color/shading is a registration guide: silhouettes, UV islands and alpha never
move. Functional masks, text, diagrams, photographs and already replaced art
are listed separately rather than passed through a generic recoloring filter.
"""
from pathlib import Path
import argparse, hashlib, json, sys
from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.build_visual_asset_catalog import decode
from tools.equipment_texture_export import native_encode

OUT=ROOT/'reports/remaining-textures-20261021'
ASSET=ROOT/'assets/wasteland-materials-v1'
ORIGINAL=ROOT/'work/remaining-textures-20261021/original'
sha=lambda b:hashlib.sha256(b).hexdigest()

def family(name):
    n=name.lower().removeprefix('base/')
    if n.endswith('target_diffuse.jpg'):return 'wood'
    if any(k in n for k in ('hair_',)):return 'hair'
    if any(k in n for k in ('chr_man','chr_woman','mob_sickminer','mob_wildminer','miner_new')):return 'skin_cloth'
    if any(k in n for k in ('ground','crater','decal','road_desert','sidewalk','pavement','mine_ground')):return 'ground'
    if any(k in n for k in ('tree','foliage','bush','grass','flower','christmas_tree')):return 'foliage'
    if any(k in n for k in ('wood','forest_house','village_house','village_bench','shack','pallet','stool','stool','crate','fence_wood')):return 'wood'
    if any(k in n for k in ('armor','cloth','gloves','beret','budenovka','hat','rucksack','tent','bed','chair','couch','sofa','armchair','hammock','medikit')):return 'cloth_metal'
    if any(k in n for k in ('car','veh','barrel','container','hangar','garage','train','rail','shelf','shelves','stove','metal','pipe','tank','drill','radio','weapon','gun','ak74','rpg','ammo','pp19','toz','flashbang','c4','coldsteel','nightvision','bomb','mine','rack','box')):return 'metal'
    if any(k in n for k in ('house','wall','roof','office','building','ny_','concrete','brick','cafe','hospital','clinic','bunker','base left','base right')):return 'masonry'
    return 'mixed'

def exclusion(name,image):
    n=name.lower();group=name.split('/')[1]
    if group=='fonts':return 'Font/glyph atlas; functional typography'
    if ('_mask' in n and n.endswith('.png')) or n.endswith('/woman_mask.png'):return 'Functional camouflage/skin selection mask'
    if group in ('tutorial','quest'):return 'Tutorial diagram or narrative portrait; requires separate illustration work'
    if group in ('pda','gui','gui2','assault'):return 'Interface atlas/text/diagram; requires icon-by-icon authoring'
    if group not in ('setting','models','items','gfx'):return 'Engine helper texture'
    if group=='gfx' and not any(k in n for k in ('rocket.','rucksack','meat.','missiles.')):return 'Particle, visibility or tactical marker; requires effect-specific validation'
    if '/setting/environment/' in n or n.endswith('/mzflash.png'):return 'Animated light/fire effect; separate frame continuity contract'
    if any(k in n for k in ('snow_explode','road_dust')):return 'Animated particle atlas; separate frame continuity contract'
    if '/setting/system/' in n or '/setting/gui/' in n:return 'Engine/UI helper atlas'
    if 'shadow' in n:return 'Shadow-only alpha atlas'
    stat=ImageStat.Stat(image.convert('RGB'),image.getchannel('A').point(lambda v:255 if v>100 else 0))
    if max(stat.mean)<8:return 'Shadow-only or empty color plane; alpha owns appearance'
    return None

def prepare():
    for folder in ('guides','masters','native','source','preview'):(ASSET/folder).mkdir(parents=True,exist_ok=True)
    inv=json.loads((OUT/'inventory.json').read_bytes());tasks=[];skipped=[]
    rows={r['path']:r for r in json.loads((OUT/'manifest-before.json').read_bytes())['files']}
    for record in inv:
        if record['status']!='original':continue
        name=record['path'];raw=(ORIGINAL/name).read_bytes();assert sha(raw)==rows[name]['sha256']==record['original_sha256']
        try:image,codec=decode(raw)
        except Exception as error:
            skipped.append(dict(path=name,reason='Not a decodable material bitmap: '+type(error).__name__));continue
        why=exclusion(name,image)
        if why:skipped.append(dict(path=name,reason=why));continue
        ident=sha(name.encode())[:16];guide=ASSET/'guides'/(ident+'.png');image.convert('RGB').save(guide)
        is_model=name.startswith('base/models/')
        # Native sprite atlases have pixel coordinates. Only UV-mapped model
        # diffuse maps can safely gain native resolution, maintaining aspect.
        factor=max(1,min(4,1024//max(image.size))) if is_model else 1
        native=[image.width*factor,image.height*factor]
        render_factor=2 if max(native)<=1024 else 1
        tasks.append(dict(id=ident,path=name,material=family(name),source_size=list(image.size),
            native_size=native,render_size=[v*render_factor for v in native],
            source_sha256=sha(raw),guide=guide.relative_to(ROOT).as_posix(),codec=codec,
            native_resolution_increased=factor>1,alpha_extrema=image.getchannel('A').getextrema()))
        if name.startswith('base/setting/') and (('ground_' in name and '_base_' in name) or name.endswith(('/mine_ground.png','/jt_ground_v01.png'))):
            mean=ImageStat.Stat(image.convert('RGB'),image.getchannel('A').point(lambda v:255 if v>180 else 0)).mean
            tasks[-1]['terrain_linear_rgb']=[((v/255+.055)/1.055)**2.4 if v>10 else v/3294.6 for v in mean]
    (ASSET/'tasks.json').write_text(json.dumps(tasks,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'separate-artwork.json').write_text(json.dumps(skipped,indent=2))
    print(json.dumps(dict(material_textures=len(tasks),separate_artwork=len(skipped),already_replaced=sum(r['status']=='replaced' for r in inv))))

def export():
    tasks=json.loads((ASSET/'tasks.json').read_text(encoding='utf-8'));proof=[]
    if '--active' in sys.argv:
        names={t['path'] for t in json.loads((OUT/'active-materials.json').read_text(encoding='utf-8'))};tasks=[t for t in tasks if t['path'] in names]
    for t in tasks:
        raw=(ORIGINAL/t['path']).read_bytes();ref,_=decode(raw)
        master=ASSET/'masters'/(t['id']+'.png')
        if '--partial' in sys.argv and not master.exists():continue
        im=Image.open(master).convert('RGBA');assert list(im.size)==t['render_size']
        im=im.resize(t['native_size'],Image.Resampling.BOX)
        # Mapped models are opaque JPEGs; sprites retain exact native alpha.
        if t['native_resolution_increased']:
            assert raw[:2]==b'\xff\xd8' and ref.getchannel('A').getextrema()==(255,255)
            import io
            stream=io.BytesIO();im.convert('RGB').save(stream,format='JPEG',quality=97,subsampling=0);encoded=stream.getvalue()
        else:encoded=native_encode(raw,im,ref)
        target=ASSET/'native'/t['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(encoded)
        check,codec=decode(encoded);assert list(check.size)==t['native_size'] and encoded!=raw
        if not t['native_resolution_increased']:
            assert check.getchannel('A').tobytes()==ref.getchannel('A').tobytes(),t['path']
        before=ref.convert('RGB').resize(check.size,Image.Resampling.BICUBIC);after=check.convert('RGB')
        from PIL import ImageChops
        diff=ImageStat.Stat(ImageChops.difference(before,after)).mean
        proof.append(dict(**t,sha256=sha(encoded),size=len(encoded),master_sha256=sha(master.read_bytes()),
            original_alpha_exact=not t['native_resolution_increased'],mean_rgb_change=diff,native_codec=codec))
    (OUT/'texture-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,exported=len(proof),high_resolution_models=sum(t['native_resolution_increased'] for t in proof))))

def sheets():
    tasks=json.loads((ASSET/'tasks.json').read_text(encoding='utf-8'))
    if '--active' in sys.argv:
        names={t['path'] for t in json.loads((OUT/'active-materials.json').read_text(encoding='utf-8'))};tasks=[t for t in tasks if t['path'] in names]
    if '--partial' in sys.argv:tasks=[t for t in tasks if (ASSET/'native'/t['path']).exists()]
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',15)
    # Each page contains BEFORE/AFTER pairs, including every exported atlas.
    pages=[]
    for start in range(0,len(tasks),24):
        subset=tasks[start:start+24];canvas=Image.new('RGB',(1600,6*225),(29,33,34));d=ImageDraw.Draw(canvas)
        for at,t in enumerate(subset):
            x=at%4*400;y=at//4*225
            source,_=decode((ORIGINAL/t['path']).read_bytes())
            target,_=decode((ASSET/'native'/t['path']).read_bytes())
            for off,im,label in ((0,source,'Original'),(200,target,'Blender')):
                im.thumbnail((194,185));canvas.paste(im,(x+off+(194-im.width)//2,y+19+(185-im.height)//2),im)
                d.text((x+off+4,y),label,font=font,fill='#acb8b8')
            d.text((x+4,y+204),t['path'].split('base/')[-1][-47:],font=font,fill='white')
        p=ASSET/'preview'/f'comparison-{start//24+1:02}.jpg';canvas.save(p,quality=92);pages.append(p.relative_to(ROOT).as_posix())
    (OUT/'comparison-pages.json').write_text(json.dumps(pages,indent=2));print(json.dumps(dict(pages=len(pages))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','export','sheets'));p.add_argument('--partial',action='store_true');p.add_argument('--active',action='store_true');globals()[p.parse_args().mode]()
