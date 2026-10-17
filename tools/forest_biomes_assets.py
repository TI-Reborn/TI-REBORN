"""Verified published inputs, non-destructive biome resource copies and texture build."""
from pathlib import Path
import copy,hashlib,io,json,shlex,struct,subprocess,urllib.request,zlib,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/forest-biomes';ASSETS=ROOT/'assets/forest-encounter-v2'
BASE=Path(r'C:/Program Files (x86)/TIOnline/base')
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
SERVER_FILES=('tools/encounter_scene.py','tio/world_encounters.py','tio/battle_rewards.py','tio/arena_service.py',
 'tio/item_stacking.py','tio/shop.py','server/runtime.py','config/world_encounters.json',
 'config/battle_map_profiles.json','config/arena_fragments.json','evidence/items_diagnostic.xml','tio/encounter_loot.py')
BIOMES={'ash':('ashfor',7),'autumn':('autfor',8),'blight':('wetfor',9)}
TEXTURES=['forest/ground_forest_base_a.tga','forest/ground_forest_base_b.tga',
 'forest/ground_forest_detail_a.tga','forest/ground_forest_detail_b.tga',
 'forest/forest_tree/forest_tree_v1.png','forest/forest_tree/forest_tree_v2.png','forest/forest_tree/forest_tree_v3.png',
 'forest/forest_summerhouse/forest_summerhouse_a.png','forest/forest_summerhouse/forest_summerhouse_b.png']

def sha(raw):return hashlib.sha256(raw).hexdigest()
def fetch(name):
    manifest=json.loads((OUT/'previous-client-manifest.json').read_bytes())
    record=next(r for r in manifest['files'] if r['path']==name)
    p=OUT/'source'/name
    if not p.exists():
        p.parent.mkdir(parents=True,exist_ok=True)
        with urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+record['sha256'],timeout=30) as response:p.write_bytes(response.read())
    raw=p.read_bytes();assert len(raw)==record['size'] and sha(raw)==record['sha256'],name
    return p

def inspect():
    OUT.mkdir(parents=True,exist_ok=True)
    code="""import pathlib,json,sys,hashlib,sqlite3,subprocess
r=pathlib.Path('/opt/tio-emulator');d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
integrity=d.execute('PRAGMA integrity_check').fetchone()[0],accounts=d.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
checkpoints=d.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=d.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],
files={n:(dict(sha=hashlib.sha256((r/n).read_bytes()).hexdigest(),source=(r/n).read_text()) if (r/n).exists() else None) for n in json.load(sys.stdin)},
client=pathlib.Path('/var/www/tio-client/updates/manifest.json').read_text())))"""
    r=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(SERVER_FILES),capture_output=True,text=True,encoding='utf-8')
    if r.returncode:raise RuntimeError(r.stderr)
    data=json.loads(r.stdout);files=data.pop('files');client=data.pop('client')
    (OUT/'previous-client-manifest.json').write_text(client,encoding='utf-8')
    hashes={}
    for name,record in files.items():
        hashes[name]=record['sha'] if record else None
        if record:
            p=OUT/'remote-before'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(record['source'],encoding='utf-8',newline='')
            assert sha((ROOT/name).read_bytes())==record['sha'],f'Local differs from hosted: {name}'
    (OUT/'before-hashes.json').write_text(json.dumps(hashes,indent=2))
    (OUT/'inspection.json').write_text(json.dumps(data,indent=2));print(json.dumps(data))

def inputs():
    from tools.build_visual_asset_catalog import decode
    (ASSETS/'inputs').mkdir(parents=True,exist_ok=True)
    for name in TEXTURES:
        original=fetch('base/setting/'+name)
        im,_=decode(original.read_bytes());im.save(ASSETS/'inputs'/(Path(name).stem+'.png'))
    fetch('base/ground.xml');fetch('base/shared config/items.xml');fetch('base/items.cfg');fetch('base/russian.lng')
    for name in ('forest_tree_v01.s','forest_tree_v02.s','forest_tree_v03.s','forest_summerhouse_v1.s'):fetch('base/maps/'+name)
    ground=ET.parse(OUT/'source/base/ground.xml').getroot().find("ground[@id='3']")
    models=[b.get('filename').replace('\\','/') for b in ground if b.get('layer') in ('0','1')]
    for name in models:fetch('base/setting/'+name)
    for name in ('forest_tree_v1.t','forest_tree_v2.t','forest_tree_v3.t','forest_summerhouse.t'):
        local=next((BASE/'setting').rglob(name));fetch('base/'+local.relative_to(BASE).as_posix())
    print(json.dumps(dict(texture_inputs=len(TEXTURES),source_version=json.loads((OUT/'previous-client-manifest.json').read_bytes())['version'])))

def resources():
    """New resource names, unchanged geometry/collision; old Denver stays intact."""
    client=OUT/'client';source=OUT/'source/base'
    ground=ET.parse(source/'ground.xml').getroot();original=ground.find("ground[@id='3']")
    fragments=json.loads((ROOT/'config/arena_fragments.json').read_text())
    profiles_path=ROOT/'config/battle_map_profiles.json';profiles=json.loads(profiles_path.read_text())
    for biome,(prefix,brush_id) in BIOMES.items():
        target=client/'base/setting/biomes'/biome;target.mkdir(parents=True,exist_ok=True)
        group=ET.SubElement(ground,'ground',name='encounter_'+biome,id=str(brush_id))
        # Only ground layers, with no decorative container sprites.
        for brush in original:
            if brush.get('layer') not in ('0','1'):continue
            name=brush.get('filename').replace('\\','/');old=source/'setting'/name
            new=old.name.replace('forest',prefix)
            (target/new).write_bytes(old.read_bytes().replace(b'forest',prefix.encode()))
            ET.SubElement(group,'brush',filename='biomes\\'+biome+'\\'+new,layer=brush.get('layer'))
        for name in ('forest_tree_v01.s','forest_tree_v02.s','forest_tree_v03.s','forest_summerhouse_v1.s'):
            old=source/'maps'/name;raw=old.read_bytes()
            raw=zlib.decompress(raw[16:]) if raw[:4]==b'\x03ZIP' else raw
            new=name.replace('forest',prefix);raw=raw.replace(b'forest',prefix.encode())
            dest=client/'base/maps'/new;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
            info=copy.deepcopy(fragments[name]);info['sha256']=sha(raw)
            info['models']=[m.replace('forest',prefix) for m in info['models']]
            model_hashes={}
            for model in fragments[name]['models']:
                original_model=next((source/'setting').rglob(model))
                model_name=model.replace('forest',prefix);model_raw=original_model.read_bytes().replace(b'forest',prefix.encode())
                (target/model_name).write_bytes(model_raw);model_hashes[model_name]=sha(model_raw)
            info['door_models_sha256']=model_hashes;fragments[new]=info
        size={'ash':38,'autumn':42,'blight':40}[biome]
        profiles['profiles']['encounter_'+biome]=dict(enabled=True,width=size,height=size,ground_id=3,
           ground_brush_id=brush_id,large_modes=[],pools=dict(trees=[prefix+'_tree_v0'+str(i)+'.s' for i in (1,2,3)],
           ruins=[prefix+'_summerhouse_v1.s']),variants=[dict(name='clearing',counts=dict(trees=[12,16])),
           dict(name='ruins',counts=dict(trees=[14,18],ruins=[1,1]))],notes='Dedicated post-apocalyptic dog encounter; no crates. Native cell brush '+str(brush_id))
    ET.indent(ground);(client/'base/ground.xml').write_bytes(ET.tostring(ground,encoding='utf-8',xml_declaration=True))
    (ROOT/'config/arena_fragments.json').write_text(json.dumps(fragments,indent=2)+'\n')
    profiles_path.write_text(json.dumps(profiles,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    from tio.world_encounters import POLICY
    rules=POLICY['loot'];root=ET.parse(source/'shared config/items.xml').getroot()
    server=ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()
    cfg=(source/'items.cfg').read_bytes().decode('cp1251')
    for identity,rule in rules.items():
        assert root.find(f"item[@id='{identity}']") is None
        values=dict(weight=str(rule['weight']),durability='0',stackable='1',packamount='1',
                    image=rule['image'],name=rule['name'])
        node=ET.Element('item',id=identity,name=rule['name'])
        for key,value in values.items():
            if key!='name':ET.SubElement(node,'value',key=key,val=value)
        prior=server.find(f"item[@id='{identity}']")
        if prior is not None:server.remove(prior)
        root.append(node);server.append(copy.deepcopy(node))
        cfg+='\nSection '+identity+': '+rule['name']+'\n{\n\titem_id='+identity+'\n'+''.join('\t'+k+'='+v+'\n' for k,v in values.items())+'}\n'
    for tree,path in ((root,client/'base/shared config/items.xml'),(server,ROOT/'evidence/items_diagnostic.xml')):
        path.parent.mkdir(parents=True,exist_ok=True);ET.indent(tree);path.write_bytes(ET.tostring(tree,encoding='utf-8',xml_declaration=True))
    (client/'base/items.cfg').write_bytes(cfg.encode('cp1251'))
    print(json.dumps(dict(biomes=list(BIOMES),files=len(list(client.rglob('*'))),materials=list(rules))))

def textures():
    """Export AI-created art to original codec/size/alpha for existing UVs."""
    from PIL import Image
    from tools.build_visual_asset_catalog import decode
    generated={r['id']:Path(r['path']) for r in [*json.loads((ASSETS/'generated.json').read_text()),*json.loads((ASSETS/'icons.json').read_text())]}
    for biome,(prefix,_) in BIOMES.items():
        raw_dir=ASSETS/'generated'/biome;raw_dir.mkdir(parents=True,exist_ok=True)
        target=OUT/'client/base/setting/biomes'/biome
        for name in TEXTURES:
            original=OUT/'source/base/setting'/name;raw=original.read_bytes();reference,_=decode(raw)
            created=generated[biome+'/'+Path(name).stem]
            (raw_dir/created.name).write_bytes(created.read_bytes())
            art=Image.open(created).convert('RGBA')
            if 'ground_forest_base_' in name:
                # Sprite atlas export: align the two generated rhombus bounding
                # boxes to the two original UV islands, without altering art.
                canvas=Image.new('RGBA',reference.size)
                for half in (0,1):
                    crop=art.crop((0,half*art.height//2,art.width,(half+1)*art.height//2))
                    bounds=crop.getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()
                    if bounds is None:raise ValueError('Generated ground island missing')
                    sprite=crop.crop(bounds).resize((reference.width,reference.height//2),Image.Resampling.LANCZOS)
                    canvas.paste(sprite,(0,half*reference.height//2))
                art=canvas
            else:art=art.resize(reference.size,Image.Resampling.LANCZOS)
            # Standard sprite-edge colour padding prevents transparent generated
            # pixels from leaving black seams under the original engine mask.
            from collections import deque
            rgba=list(art.getdata());source_pixels=list(reference.getdata());w,h=art.size
            needed=[i for i,(a,b) in enumerate(zip(rgba,source_pixels)) if a[3]<32 and b[3]>64 and max(b[:3])>20]
            if needed:
                nearest=[-1]*(w*h);queue=deque()
                for i,pixel in enumerate(rgba):
                    if pixel[3]>=64:nearest[i]=i;queue.append(i)
                if not queue:raise ValueError('Generated sprite is empty')
                while queue:
                    i=queue.popleft();x=i%w;y=i//w
                    for n in ((i-1 if x else -1),(i+1 if x+1<w else -1),(i-w if y else -1),(i+w if y+1<h else -1)):
                        if n>=0 and nearest[n]<0:nearest[n]=nearest[i];queue.append(n)
                for i in needed:rgba[i]=rgba[nearest[i]]
                art.putdata(rgba)
            im=art.convert('RGB')
            dest=target/Path(name).name.replace('forest',prefix)
            if raw.startswith(bytes.fromhex('07e181')):
                # Native AJPG_EX: retain the exact original mask JPEG/header.
                key=100;plain=bytearray()
                for cipher in raw:
                    plain.append(cipher^(key>>8));key=((key+cipher)*0xce6d+0x58bf)&65535
                old_size,mask_size=struct.unpack_from('<QQ',plain,39)
                color=io.BytesIO();im.save(color,format='JPEG',quality=94,subsampling=0)
                header=bytearray(plain[:55]);struct.pack_into('<QQ',header,39,len(color.getvalue()),mask_size)
                payload=header+color.getvalue()+plain[55+old_size:]
                encrypted=bytearray();key=100
                for value in payload:
                    cipher=value^(key>>8);encrypted.append(cipher);key=((key+cipher)*0xce6d+0x58bf)&65535
                dest.write_bytes(encrypted)
            else:
                im=im.convert('RGBA');im.putalpha(reference.getchannel('A'));im.save(dest,format='TGA')
            check,_=decode(dest.read_bytes())
            assert check.size==reference.size and check.getchannel('A').tobytes()==reference.getchannel('A').tobytes(),dest
    for identity,rule in __import__('tio.world_encounters',fromlist=['POLICY']).POLICY['loot'].items():
        created=generated['icon/'+rule['image'].split('.')[0]]
        dest=OUT/'client/base/items'/rule['image'];dest.parent.mkdir(parents=True,exist_ok=True)
        Image.open(created).convert('RGBA').resize((64,64),Image.Resampling.LANCZOS).save(dest)
        (ASSETS/'generated'/created.name).write_bytes(created.read_bytes())
    print(json.dumps(dict(textures=27,icons=2,alpha='original masks retained byte-exactly')))

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    {'inspect':inspect,'inputs':inputs,'resources':resources,'textures':textures}[sys.argv[1]]()
