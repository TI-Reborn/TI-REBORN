"""Package generated GUI artwork into the existing native sprite layouts."""
from pathlib import Path
import hashlib
import io
import json
import sys
from PIL import Image, ImageEnhance, ImageOps

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.build_visual_asset_catalog import decode
from tools.equipment_texture_export import native_encode
from tools.build_main_hud_degrain_assets import original_png_metadata

ASSET=ROOT/'assets/personal-gui-v1'
BASE=ROOT/'work/personal-gui-20261020/baseline'
OUT=ROOT/'reports/personal-gui-20261020'
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def generated_glyph(master,index,size):
    w,h=master.size
    cell=master.crop((index%2*w//2,index//2*h//2,(index%2+1)*w//2,(index//2+1)*h//2))
    bounds=cell.getchannel('A').getbbox()
    assert bounds
    cell=cell.crop(bounds)
    factor=(size-6)/max(cell.size)
    cell=cell.resize(tuple(max(1,round(n*factor)) for n in cell.size),Image.Resampling.LANCZOS)
    fitted=Image.new('RGBA',(size,size))
    fitted.alpha_composite(cell,((size-cell.width)//2,(size-cell.height)//2))
    return fitted


def states(glyph,size,canvas):
    atlas=Image.new('RGBA',canvas)
    for state in range(4):
        frame=glyph.copy()
        if state==1:
            frame=ImageOps.grayscale(frame).convert('RGBA');frame.putalpha(glyph.getchannel('A'))
            frame=ImageEnhance.Brightness(frame).enhance(.44)
        elif state==2:frame=ImageEnhance.Brightness(frame).enhance(.72)
        elif state==3:frame=ImageEnhance.Brightness(frame).enhance(1.18)
        columns=canvas[0]//size
        atlas.alpha_composite(frame,(state%columns*size,state//columns*size))
    return atlas


def build():
    source=ASSET/'source';runtime=ASSET/'runtime';runtime.mkdir(exist_ok=True)
    guide=Image.open(source/'hud-master.png').convert('RGBA').resize((1024,1024),Image.Resampling.LANCZOS)
    layout=json.loads((source/'hud-atlas-layout.json').read_text())
    manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    records={r['path']:r for r in manifest['files']}
    overrides={};proof=[]
    def save(name,raw,alpha_exact,provenance):
        before=(BASE/name).read_bytes();row=records[name]
        assert sha(before)==row['sha256'] and len(before)==row['size'] and not row.get('seed')
        old,_=decode(before);new,_=decode(raw)
        assert old.size==new.size
        if alpha_exact:assert old.getchannel('A').tobytes()==new.getchannel('A').tobytes()
        assert before!=raw,name
        path=runtime/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        overrides[name]=name
        proof.append(dict(path=name,source_sha256=sha(before),sha256=sha(raw),size=len(raw),
            dimensions=list(new.size),native_alpha_exact=alpha_exact,master=provenance))
    for filename,bounds in layout.items():
        name='base/pda/'+filename;before=(BASE/name).read_bytes();reference,_=decode(before)
        art=guide.crop(bounds)
        assert art.size==reference.size
        raw=native_encode(before,art,reference)
        if before.startswith(b'\x89PNG'):
            # Preserve native PNG metadata where its original color model is RGBA8.
            try:raw=original_png_metadata(before,raw)
            except AssertionError:pass
        save(name,raw,True,'hud-master.png')
    before=(BASE/'base/pda/loc_reserve.jpg').read_bytes();ref,_=decode(before)
    bg=Image.open(source/'reservation-master.png').convert('RGB').resize(ref.size,Image.Resampling.LANCZOS)
    stream=io.BytesIO();bg.save(stream,format='JPEG',quality=97,subsampling=0)
    save('base/pda/loc_reserve.jpg',stream.getvalue(),True,'reservation-master.png')
    name='base/pda/jack_pot_progress.png'
    before=(BASE/name).read_bytes();reference,_=decode(before)
    art=Image.open(source/'progress-master.png').convert('RGBA').resize(reference.size,Image.Resampling.LANCZOS)
    save(name,native_encode(before,art,reference),True,'progress-master.png: eleven native progress states')
    nav=Image.open(source/'navigation-master.png').convert('RGBA')
    # A generated neutral instrument material replaces the old olive folded
    # location menu backing, retaining its native fade and occupied geometry.
    name='base/pda/pda_underlay.png'
    before=(BASE/name).read_bytes();reference,_=decode(before)
    material=guide.crop((200,50,380,300)).resize(reference.size,Image.Resampling.LANCZOS)
    save(name,native_encode(before,material,reference),True,'hud-master.png: neutral panel material')
    for index,symbol in enumerate(('map','soldier','ratings','money')):
        # Original fallback atlas uses three 40px columns; HD uses two.
        name=f'base/pda/pda_btn_{index+1}.png'
        tile=generated_glyph(nav,index,40)
        im=states(tile,40,(128,128));stream=io.BytesIO();im.save(stream,format='PNG')
        save(name,stream.getvalue(),False,'navigation-master.png')
        for density in (100,125,150,200):
            name=f'base/ui-hd/icons/a/{density}/a-{symbol}-{density}.png'
            size=40*density//100;old,_=decode((BASE/name).read_bytes())
            assert old.size==(size*2,size*2)
            im=states(generated_glyph(nav,index,size),size,old.size)
            stream=io.BytesIO();im.save(stream,format='PNG')
            save(name,stream.getvalue(),False,'navigation-master.png')
    (ASSET/'overrides.json').write_text(json.dumps(overrides,indent=2)+'\n',encoding='utf-8')
    report=dict(passed=True,baseline_version=manifest['version'],changed_files=len(proof),files=proof,
        executable_changes=False,native_layouts_preserved=True,callbacks_unchanged=True,
        generation_tool='built-in image_gen',packing='registered atlas crops, native codec/alpha, glyph density and state packing')
    (OUT/'asset-proof.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'changed_files':len(proof),'total_bytes':sum(p['size'] for p in proof)}))


if __name__=='__main__':build()
