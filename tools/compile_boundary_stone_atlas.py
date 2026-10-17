"""Slice generated RGBA atlas and normalize pixel density uniformly.

This is technical sprite compilation, never per-axis scaling or a warp.
The original ImageGen atlas is preserved byte-for-byte.
"""
import hashlib
import json
from pathlib import Path
import shutil
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets/arena-boundaries-v1/generated-stones'
SOURCE=Path('C:/Users/jundu/.codex/generated_images/01a11496-9fc1-78e3-83d6-10cefe8254fc/exec-8ff1f48a-3257-4643-b049-755a420f06e6.png')
PROMPT='Use case: stylized-concept. Asset type: production isometric raster game sprite atlas for the Total Influence forest arena boundary. The reference image is a STYLE reference: use ONLY its top row A mossy stones and ferns, not logs, not its composition. Create a transparent 4 by 4 sprite atlas of SIXTEEN separate low mossy fieldstone clusters. One small natural rock plus sparse ferns/ivy per cluster, some two-rock clusters, varied rounded and chipped silhouettes. Photographic gritty hand-painted 2000s isometric RPG game texture, grey olive moss and weathered stone, muted desaturated earthy green palette, detailed irregular natural stone surfaces, no low-poly faceting. Orthographic isometric 2:1 ground projection, light from upper left on ALL pieces. Stones are LOW, not tall boulders or walls. Atlas layout: canvas1024x1024, sixteen equally spaced cells256x256. Each object centered in its own cell, complete isolated silhouette surrounded by at least48 transparent pixels; no shared ground rectangles, no contact between different cells, no rows of connected stones, no floor mats. Object native footprint approximately one game cell. Include a small natural contact shadow in alpha, no cast shadow extending far. True transparent background, no white or checkerboard, no text/labels/grid/watermark. No houses/logs/fences. Output the atlas only. This will be uniformly reduced into native small sprites without any per-axis scaling.'
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    atlas=OUT/'atlas.png';shutil.copyfile(SOURCE,atlas)
    image=Image.open(atlas);assert image.mode=='RGBA' and image.width==image.height
    records=[]
    for index in range(16):
        column,row=index%4,index//4
        x,y=round(column*image.width/4),round(row*image.height/4)
        x1,y1=round((column+1)*image.width/4),round((row+1)*image.height/4)
        cell=image.crop((x,y,x1,y1));box=cell.getchannel('A').point(lambda a:255 if a>=16 else 0).getbbox()
        assert box and box[0]>0 and box[1]>0 and box[2]<cell.width and box[3]<cell.height
        cut=cell.crop(box)
        scale=min(48/cut.width,32/cut.height)
        assert scale<1
        # Pillow affine uses exactly the SAME scale in both axes, with
        # integer output padding; independent width/height resizing is avoided.
        w,h=__import__('math').ceil(cut.width*scale),__import__('math').ceil(cut.height*scale)
        sprite=cut.transform((w,h),Image.Transform.AFFINE,(1/scale,0,0,0,1/scale,0),resample=Image.Resampling.BICUBIC)
        path=OUT/f'stone-{index+1:02d}.png';sprite.save(path)
        records.append(dict(id=f'denver_moss_stone_{index+1:02d}',raster=path.relative_to(ROOT).as_posix(),
            raster_sha256=sha(path.read_bytes()),screen_bbox=[-w//2,-h,-w//2+w,0],
            source_atlas_crop=[x+box[0],y+box[1],x+box[2],y+box[3]],crop_alpha_threshold=16,uniform_source_scale=scale,
            affine_scale_xy=[scale,scale],native_render_scale=[1,1],dimensions=[w,h]))
    proof=dict(passed=True,source_atlas_sha256=sha(atlas.read_bytes()),source_dimensions=list(image.size),
        generated_by='built-in image_gen',sprites=records,per_axis_stretch=False,mirror=False,
        purpose='Native sized forest boundary sprites; crop, uniform density normalization, native rendering at1:1')
    (OUT/'sprites.json').write_text(json.dumps(proof,indent=2)+'\n','utf-8')
    reference=ROOT/'assets/arena-boundary-proposals-v1/denver.png'
    (OUT/'prompts.json').write_text(json.dumps(dict(prompt=PROMPT,transparent_background=True,
        reference=reference.relative_to(ROOT).as_posix(),reference_sha256=sha(reference.read_bytes()),
        source_atlas=atlas.relative_to(ROOT).as_posix(),source_atlas_sha256=proof['source_atlas_sha256']),indent=2)+'\n','utf-8')
    print(json.dumps(dict(passed=True,sprites=len(records),source_dimensions=list(image.size),uniform_scale=True)))

if __name__=='__main__':main()
