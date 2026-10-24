"""Place the reviewed generated rocket in RPG-only HUD frame4; preserve all others."""
import hashlib,json,shutil,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
WORK=ROOT/'work/rpg-action-icon-20261019';OUT=ROOT/'reports/rpg-action-icon-20261019'
ASSET=ROOT/'assets/rpg-action-icon-v1';NAME='base/ui-hd/battle-controls/hd4-bui-glyphs.png'
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def build():
    ASSET.mkdir(exist_ok=True)
    master=ASSET/'rocket-master.png'
    if not master.exists():shutil.copyfile(WORK/'rocket-master.png',master)
    before=Image.open(WORK/'hd4-bui-glyphs.png').convert('RGBA')
    rocket=Image.open(master).convert('RGBA');assert rocket.getchannel('A').getextrema()[0]==0
    box=rocket.getchannel('A').getbbox();assert box
    crop=rocket.crop(box);factor=158/max(crop.size)
    small=crop.resize(tuple(max(1,round(v*factor)) for v in crop.size),Image.Resampling.LANCZOS)
    core=small.getchannel('A').point(lambda a:255 if a>=16 else 0).getbbox();assert core
    tile=Image.new('RGBA',(184,184))
    tile.alpha_composite(small,(round(92-(core[0]+core[2])/2),round(92-(core[1]+core[3])/2)))
    assert before.size==(1104,1104)
    candidate=before.copy();candidate.paste(tile,(4*184,0))
    for frame in range(36):
        x,y=frame%6*184,frame//6*184;bounds=(x,y,x+184,y+184)
        assert (before.crop(bounds).tobytes()!=candidate.crop(bounds).tobytes())==(frame==4)
    bounds=tile.getchannel('A').getbbox();assert min(bounds[:2])>=12 and max(bounds[2:])<=172
    destination=OUT/'client'/NAME;destination.parent.mkdir(parents=True,exist_ok=True)
    candidate.save(destination,compress_level=9);tile.save(ASSET/'rocket-glyph-184.png',compress_level=9)
    plate=Image.open(WORK/'hd4-bui-plates.png').convert('RGBA').crop((0,0,184,184))
    preview=Image.new('RGB',(600,280),'#23241b');draw=ImageDraw.Draw(preview)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
    for index,(label,glyph) in enumerate((('Before',before.crop((736,0,920,184))),('RPG rocket',tile))):
        draw.text((20+index*290,10),label,font=font,fill='#e4dfbb')
        button=Image.alpha_composite(plate,glyph)
        preview.paste(button,(20+index*290,48),button)
        actual=button.resize((46,46),Image.Resampling.LANCZOS)
        preview.paste(actual,(220+index*290,110),actual)
    preview.save(OUT/'icon-review.png')
    result=dict(passed=True,master=str(master),master_sha256=sha(master.read_bytes()),
        source_sha256=sha((WORK/'hd4-bui-glyphs.png').read_bytes()),candidate_sha256=sha(destination.read_bytes()),
        asset=str(destination),frame=4,atlas_size=[1104,1104],logical_cell=[46,46],density=4,
        other_35_cells_pixel_identical=True,alpha_bounds=bounds,transparent_background=True,
        source='Built-in image_gen, manual printed page39 and existing olive/brass HUD style',
        native_changes=False,server_changes=False)
    (OUT/'asset-proof.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
if __name__=='__main__':build()
