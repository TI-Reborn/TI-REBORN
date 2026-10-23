"""Apply the approved graphite/amber frame artwork to every native UI skin.

Native coordinates, alpha masks, atlas states, semantic glyphs and callbacks
are retained. Baseline resources are pinned to the inspected hosted manifest.
"""
from pathlib import Path
import hashlib
import json
import sys
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_visual_asset_catalog import decode
from tools.equipment_texture_export import native_encode
from tools.build_main_hud_degrain_assets import original_png_metadata
from tools.build_menu_interface_assets import frame_atlas, framed_plate, button_atlas

WORK = ROOT / 'work/personal-gui-all-20261020'
OUT = ROOT / 'reports/personal-gui-all-20261020'
ASSET = ROOT / 'assets/personal-gui-all-v1'
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def candidates(records):
    roots = ('base/gui/', 'base/gui2/', 'base/pda/')
    return [name for name in records if name.startswith(roots)
            and '/' not in name.removeprefix(next((p for p in roots if name.startswith(p)), ''))
            and name.lower().endswith(('.png', '.tga', '.ajpg'))]


def source(name, record):
    for base in (WORK/'baseline', ROOT/'work/personal-gui-20261020/gui/game-a',
                 ROOT/'work/personal-gui-20261020/baseline', Path('C:/Program Files (x86)/TIOnline')):
        path = base/name
        if path.is_file() and sha(path.read_bytes()) == record['sha256']:
            return path
    from urllib.request import Request, urlopen
    path = WORK/'baseline'/name
    with urlopen(Request('https://ti-reborn.com/updates/blobs/'+record['sha256'],
                        headers={'User-Agent':'TIO-launcher-self-update-verification'}), timeout=40) as response:
        raw = response.read()
    assert sha(raw) == record['sha256'] and len(raw) == record['size'], name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def audit():
    manifest = json.loads((WORK/'previous-manifest.json').read_bytes())
    records = {r['path']:r for r in manifest['files']}
    entries, errors = [], []
    OUT.mkdir(parents=True, exist_ok=True)
    for name in candidates(records):
        try:
            path = source(name, records[name]); im, codec = decode(path.read_bytes())
            entries.append({'path':name, 'size':list(im.size), 'alpha':list(im.getchannel('A').getextrema()),
                            'codec':codec, 'source':str(path)})
        except Exception as exc:
            errors.append({'path':name,'error':str(exc)})
    (OUT/'ui-inventory-errors.json').write_text(json.dumps(errors,indent=2)+'\n',encoding='utf-8')
    (OUT/'ui-inventory.json').write_text(json.dumps(entries, indent=2)+'\n', encoding='utf-8')
    font = ImageFont.truetype('C:/Windows/Fonts/consola.ttf', 14)
    for offset in range(0,len(entries),30):
        sheet = Image.new('RGB',(1500,6*215),'#303940'); draw=ImageDraw.Draw(sheet)
        for i,entry in enumerate(entries[offset:offset+30]):
            x,y=i%5*300,i//5*215
            im,_=decode(Path(entry['source']).read_bytes())
            im.thumbnail((286,174),Image.Resampling.LANCZOS)
            sheet.paste(im,(x+(300-im.width)//2,y+32+(174-im.height)//2),im)
            draw.text((x+5,y+2),entry['path'].split('/')[-1],font=font,fill='white')
            draw.text((x+5,y+18),str(entry['size']),font=font,fill='#d5b570')
        sheet.save(OUT/f'audit-{offset//30+1:02}.png')
    print(json.dumps({'textures':len(entries),'sheets':(len(entries)+29)//30}))


def registered(art, reference, *, cell=None):
    """Restore each generated region to its exact occupied native rectangle."""
    strong=Image.new('L',art.size)
    strong.putdata([255 if max(r,g,b)>100 or r>82 and r>g*1.25 else 0
                    for r,g,b in art.convert('RGB').getdata()])
    box=strong.getbbox()
    if box:
        pad=2
        art=art.crop((max(0,box[0]-pad),max(0,box[1]-pad),
                      min(art.width,box[2]+pad),min(art.height,box[3]+pad)))
    bounds=reference.getchannel('A').getbbox(); assert bounds
    result=Image.new('RGBA',reference.size)
    result.paste(art.resize((bounds[2]-bounds[0],bounds[3]-bounds[1]),Image.Resampling.LANCZOS),bounds[:2])
    return result


def recolor_controls(reference):
    """Retain exact native glyphs and state brightness; recolor olive metal only.

    Glyph silhouettes are gameplay labels, not framing artwork. Whites, reds,
    blues and signal greens are retained; bronze/olive controls become amber.
    """
    result=reference.copy();pixels=[]
    for r,g,b,a in reference.convert('RGBA').getdata():
        if r>18 and g>15 and r>b*1.15 and g>b*1.18 and g<r*1.55 and max(r,g)>b+6:
            value=max(r,g)
            pixels.append((min(255,int(value*1.35)),int(value*.86),int(value*.34),a))
        else:pixels.append((r,g,b,a))
    result.putdata(pixels)
    return result


def build():
    entries=json.loads((OUT/'ui-inventory.json').read_text())
    refs={e['path']:e for e in entries}
    manifest=json.loads((WORK/'previous-manifest.json').read_bytes())
    records={r['path']:r for r in manifest['files']}
    extra=['base/pda/loc_squad.jpg','base/ui-hd/battle-controls/hd4-bui-plates.png']
    extra += [n for n in records if n.startswith('base/ui-hd/icons/a/') and
              not any('/a-'+s+'-' in n for s in ('map','soldier','ratings','money'))]
    for name in extra:
        refs[name]={'source':str(source(name,records[name]))}
    runtime=ASSET/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    overrides={};proof=[];images={}
    def load(name):
        raw=Path(refs[name]['source']).read_bytes()
        assert sha(raw)==records[name]['sha256'] and len(raw)==records[name]['size']
        return raw,decode(raw)[0]
    def save(name,art,provenance,preserved=None):
        raw,reference=load(name)
        art=art.convert('RGBA');art.putalpha(reference.getchannel('A'))
        if preserved:
            for bounds in preserved:art.paste(reference.crop(bounds),bounds[:2])
        exported=native_encode(raw,art,reference)
        if raw.startswith(b'\x89PNG'):
            try:exported=original_png_metadata(raw,exported)
            except AssertionError:pass
        new,_=decode(exported)
        assert new.size==reference.size and new.getchannel('A').tobytes()==reference.getchannel('A').tobytes(),name
        if preserved:
            for bounds in preserved:assert new.crop(bounds).tobytes()==reference.crop(bounds).tobytes(),name
        assert raw!=exported,name
        path=runtime/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(exported)
        overrides[name]=name;images[name]=new
        proof.append(dict(path=name,source=str(Path(refs[name]['source']).resolve()),source_sha256=sha(raw),
                          sha256=sha(exported),size=len(exported),dimensions=list(new.size),native_alpha_exact=True,
                          master=provenance,semantic_regions_preserved=preserved or []))
    # Full atlas edits were generated against the exact native reference pack.
    crops={
        'windows':[(20,16,239,224),(345,15,565,225),(676,15,894,224),(1005,14,1221,224),
                   (20,309,240,516),(345,309,565,516),(676,309,887,501),(1004,309,1221,501),
                   (20,596,239,795),(344,595,576,723),(665,608,759,853),(1001,592,1210,855),
                   (20,895,241,1119),(345,893,587,1185),(675,917,888,1105),(990,896,1221,1185)],
        'battle':[(0,55,305,399),(539,92,829,405),(805,0,1026,70),(0,393,140,750),
                  (431,394,730,648),(828,643,1050,802),(92,984,425,1204),(520,1067,830,1205)]}
    for group,size in (('windows',1024),('battle',768)):
        master=Image.open(ASSET/'source'/(group+'-master.png')).convert('RGBA')
        assert master.size==(1254,1254)
        layout=json.loads((ASSET/'source'/(group+'-layout.json')).read_text())
        for index,(name,bounds) in enumerate(layout.items()):
            _,reference=load(name)
            # Explicit reviewed object bounds avoid adjacent rows: generators
            # can drift relative to the requested atlas's nominal cell edges.
            cell=master.crop(crops[group][index])
            preserved=[]
            if name.endswith('bui_nick.png'):
                art=recolor_controls(reference)
                # Its native additive nickname gradient is a semantic overlay.
            else:art=registered(cell,reference)
            if name.endswith('bui_soldierbar.png'):
                preserved=[(22,20,63,60),(75,20,187,57),(89,70,111,105)]
            if name.endswith('bui_radar.png'):preserved=[(14,53,44,222)]
            save(name,art,group+'-master.png',preserved)
    # Derive all auxiliary frame shapes from the same newly generated window,
    # using the renderer's original nine-slice 0,1,2 / 4,5,6 / 8,9,10 packing.
    panel=images['base/pda/d_window.png'].crop((0,0,96,96))
    # The sampler expects a full-sized master with a clean 128px center.
    # Upscale before sampling so the center cannot include any frame edge.
    atlas=frame_atlas(panel.resize((512,512),Image.Resampling.LANCZOS),edge_width=8)
    def plate(size):return framed_plate(atlas,size)
    _,reference=load('base/pda/loc_squad.jpg')
    save('base/pda/loc_squad.jpg',plate(reference.size),'windows-master.png: full squad/inventory panel')
    # HD native controls can override the fallback sprites. Reskin every
    # density and all four states; retain each readable central glyph.
    for name in extra:
        if not name.startswith('base/ui-hd/'):continue
        _,reference=load(name)
        if '/icons/' in name:
            cellw,cellh=reference.width//2,reference.height//2;positions=[(0,0),(cellw,0),(0,cellh),(cellw,cellh)]
        else:
            cellw=cellh=184;positions=[(i*184,0) for i in range(4)]
        art=Image.new('RGBA',reference.size)
        for state,(x,y) in enumerate(positions):
            tile=ImageEnhance.Brightness(plate((cellw,cellh))).enhance((1,.48,.72,1.4)[state])
            if '/icons/' in name:
                old=reference.crop((x,y,x+cellw,y+cellh))
                margin=max(3,cellh//8)
                glyph=Image.new('L',old.size)
                glyph.putdata([min(255,max(0,(max(r,g,b)-60)*12)) for r,g,b,a in old.getdata()])
                edge=ImageDraw.Draw(glyph)
                edge.rectangle((0,0,cellw,margin-1),fill=0);edge.rectangle((0,cellh-margin,cellw,cellh),fill=0)
                edge.rectangle((0,0,margin-1,cellh),fill=0);edge.rectangle((cellw-margin,0,cellw,cellh),fill=0)
                tile.paste(recolor_controls(old),(0,0),glyph)
            if state in (2,3):
                draw=ImageDraw.Draw(tile);margin=max(1,cellh//40)
                draw.rounded_rectangle((margin,margin,cellw-margin-1,cellh-margin-1),radius=max(2,cellh//18),
                                       outline='#f1b345' if state==3 else '#a96d26',width=max(1,cellh//35))
            art.paste(tile,(x,y))
        save(name,art,'windows-master.png: exact HD density/state frames; native central glyphs')
    rects={
        'base/pda/frame32px.png':[(1,1,41,41)],
        'base/pda/frame40px.png':[(0,0,48,48)],
        'base/pda/itemslot.png':[(0,0,64,35)],
        'base/pda/itemslotU.png':[(0,0,64,35)],
        'base/pda/skillbar.png':[(1,1,53,39)],
        'base/pda/skillbar_v.png':[(1,1,39,53)],
        'base/pda/infopane.png':[(0,0,256,43)],
        'base/pda/trnt_border.png':[(3,2,93,36)],
        'base/pda/tradelot.png':[(4,5,251,58),(4,69,251,122)],
        'base/pda/tradelotA.png':[(4,5,265,58),(4,69,265,122)],
        'base/pda/btn_square.png':[(x,y,x+40,y+40) for x,y in [(0,0),(44,0),(88,0),(0,44)]],
        'base/pda/bui_controls_btn.png':[(x,1,x+44,45) for x in (1,47,93,139)],
        'base/pda/icon_button_inventory.png':[(0,0,100,32),(100,0,200,32),(0,32,100,64),(100,32,200,64)],
        'base/pda/gui_premiumac.png':[(0,y,96,y+96) for y in (0,96,192,288)],
        'base/pda/character_phase.tga':[(x,y,x+96,y+77) for y in (0,77,154) for x in (0,97)],
        'base/pda/character_phase_mini.tga':[(0,y,113,y+77) for y in (0,77,154)],
        'base/gui/menu_message.tga':[(0,0,328,104)],
        'base/gui/menu_messageOK.tga':[(0,0,328,104)],
        'base/gui/menu_messageQuestion.tga':[(0,0,328,104)],
    }
    for name,boxes in rects.items():
        _,reference=load(name);art=Image.new('RGBA',reference.size)
        for index,box in enumerate(boxes):
            tile=plate((box[2]-box[0],box[3]-box[1]))
            if len(boxes)==4:
                tile=ImageEnhance.Brightness(tile).enhance((1,.48,.72,1.3)[index])
            if 'character_phase' in name:
                state=index//2 if name.endswith('/character_phase.tga') else index
                tile=ImageEnhance.Brightness(tile).enhance((.65,1.4,.9)[state])
                if state==1:
                    draw=ImageDraw.Draw(tile)
                    draw.rounded_rectangle((1,1,tile.width-2,tile.height-2),radius=4,outline='#e8a538',width=2)
            art.paste(tile,box[:2])
        if name.endswith('itemslotU.png'):
            art.paste(recolor_controls(reference).crop((5,5,59,30)),(5,5))
        if name.startswith('base/gui/menu_message'):
            # Confirmation controls and their native labels keep exact bounds.
            art.paste(recolor_controls(reference).crop((60,53,280,83)),(60,53))
        save(name,art,'windows-master.png: native nine-slice auxiliary frame')
    # Tiny line atlases and original icon/button atlases retain their glyphs,
    # state placement and status semantics, while old olive/brass becomes amber.
    names=['base/gui2/borders.tga','base/gui2/borders2.tga','base/gui2/borders2_.tga',
           'base/gui2/closebtn.png','base/gui2/closebtnjack.png','base/gui2/window_close.tga',
           'base/gui/menuitem.tga','base/gui/replay_panel.tga','base/gui/scroll.tga','base/gui/hud2btn.tga',
           'base/pda/borders2.tga','base/pda/bui_controls_btn2.png','base/pda/closebtn.png',
           'base/pda/checkbox.png','base/pda/gui_checkbox.png','base/pda/timer.png','base/pda/timer2.png',
           'base/pda/trackbar.png','base/pda/progressbar.png','base/pda/underprogr.png',
           'base/pda/vertical_button.tga','base/pda/40_40_button.tga','base/pda/move_right_button.tga',
           'base/pda/20_20ps_button.ajpg','base/pda/20_20ps_button.png']
    names += [n for n in refs if n.startswith('base/pda/btn_') and n not in overrides and n!='base/pda/btn_menu.png']
    names += [n for n in refs if n.startswith('base/pda/squad_page_') and 'button' in n]
    names += [n for n in refs if n.startswith('base/pda/icon_button_') and n not in overrides]
    for name in dict.fromkeys(names):
        if name in overrides:continue
        _,reference=load(name)
        art=recolor_controls(reference)
        # Keep the two health/AP data windows and the replay transport glyphs.
        preserved=[]
        if name.endswith('timer.png'):preserved=[(38,4,129,24)]
        if name.endswith('timer2.png'):preserved=[(39,4,138,24),(39,36,138,56)]
        if art.tobytes()!=reference.tobytes():save(name,art,'approved amber palette; exact native control glyphs',preserved)
    # Every UI resource has an explicit coverage classification. Content art
    # (items, portraits, location images, badges) does not define a window skin.
    prior=set(json.loads((ROOT/'assets/personal-gui-v1/overrides.json').read_text()))
    coverage=[]
    for row in entries:
        name=row['path']
        status='updated_this_release' if name in overrides else 'already_personal_gui' if name in prior else 'content_or_semantic_art'
        coverage.append({'path':name,'classification':status})
    (ASSET/'overrides.json').write_text(json.dumps(overrides,indent=2)+'\n',encoding='utf-8')
    (OUT/'asset-proof.json').write_text(json.dumps({'passed':True,'files':proof,'changed_files':len(proof),
        'native_alpha_exact':True,'native_binaries_unchanged':True,'source_manifest_sha256':sha((WORK/'previous-manifest.json').read_bytes())},indent=2)+'\n',encoding='utf-8')
    (OUT/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n',encoding='utf-8')
    # D3DX validation receives alternating original/candidate paths.
    (OUT/'native-pairs.txt').write_text('\n'.join(str(p) for row in proof for p in
        (Path(row['source']),runtime/row['path']))+'\n',encoding='utf-8')
    font=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',14)
    for offset in range(0,len(proof),15):
        sheet=Image.new('RGB',(1500,5*220),'#303940');draw=ImageDraw.Draw(sheet)
        for i,row in enumerate(proof[offset:offset+15]):
            x,y=i%3*500,i//3*220;name=row['path']
            draw.text((x+5,y+2),name,font=font,fill='white')
            for col,im in enumerate((load(name)[1],images[name])):
                im=im.copy();im.thumbnail((240,185),Image.Resampling.LANCZOS)
                sheet.paste(im,(x+col*250+(250-im.width)//2,y+25+(185-im.height)//2),im)
        sheet.save(OUT/f'review-{offset//15+1:02}.png')
    print(json.dumps({'passed':True,'changed_files':len(proof),'bytes':sum(r['size'] for r in proof)}))


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('audit','build'),default='audit',nargs='?')
    {'audit':audit,'build':build}[parser.parse_args().mode]()
