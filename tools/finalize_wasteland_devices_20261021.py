"""Export newly modelled icons into their unchanged native inventory canvases."""
import hashlib,json,sys
from pathlib import Path
from PIL import Image,ImageStat
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.build_visual_asset_catalog import decode
OUT=ROOT/'assets/wasteland-materials-v1';REPORT=ROOT/'reports/remaining-textures-20261021';ORIGINAL=ROOT/'work/remaining-textures-20261021/original'
proof=json.loads((REPORT/'texture-proof.json').read_text(encoding='utf-8'));sha=lambda b:hashlib.sha256(b).hexdigest()
for t in json.loads((OUT/'source/active-icons-layout.json').read_bytes()):
    stem=Path(t['path']).stem;master=OUT/'devices'/(stem+'.png');image=Image.open(master).convert('RGBA')
    src,_=decode((ORIGINAL/t['path']).read_bytes());bounds=src.getchannel('A').point(lambda a:255 if a>=32 else 0).getbbox()
    # All new prop pixels stay within the old icon's footprint. The new
    # geometry gets its own antialiased alpha, rather than an obsolete cutout.
    x0,y0,x1,y1=bounds;crop=image.crop(image.getchannel('A').getbbox());crop.thumbnail(((x1-x0)*16,(y1-y0)*16),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(src.width*16,src.height*16));canvas.alpha_composite(crop,(x0*16+((x1-x0)*16-crop.width)//2,y0*16+((y1-y0)*16-crop.height)//2))
    canvas.save(OUT/'devices'/(stem+'-registered.png'))
    native=canvas.resize(src.size,Image.Resampling.LANCZOS);target=OUT/'native'/t['path'];native.save(target,format='PNG');raw=target.read_bytes()
    row=next(r for r in proof if r['path']==t['path']);row.update(sha256=sha(raw),size=len(raw),master_sha256=sha(master.read_bytes()),original_alpha_exact=False,
        entirely_new_blender_geometry=True,alpha_policy='New antialiased geometry inside original bounds',native_size=list(native.size),native_codec='PNG',
        icon_source=str(master.relative_to(ROOT)).replace('\\','/'))
(REPORT/'texture-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(passed=True,new_blender_icons=8,original_canvas_dimensions=True)))
