"""Contact sheets of decoded source/export assets for visual quality checks."""
from reservation_texture_assets import *
from PIL import Image,ImageDraw

def review():
    from tools.build_visual_asset_catalog import decode
    proof=json.loads((OUT/'texture-proof.json').read_text());tasks={t['id']:t for t in json.loads((ASSETS/'tasks.json').read_text())}
    art=[p for p in proof if not p.get('shadow_preserved')];outputs=[]
    for offset in range(0,len(art),12):
        page=Image.new('RGB',(1000,6*205),(58,58,58));draw=ImageDraw.Draw(page)
        for index,p in enumerate(art[offset:offset+12]):
            x=(index%2)*500;y=(index//2)*205;draw.text((x+5,y+4),p['id'],fill='white')
            for column,path in enumerate((fetch(tasks[p['id']]['path']),OUT/'client'/p['target'])):
                im,_=decode(path.read_bytes());im.thumbnail((245,175),Image.Resampling.LANCZOS)
                page.paste(im,(x+column*250+(245-im.width)//2,y+25+(175-im.height)//2),im)
        output=OUT/f'review-{offset//12+1:02d}.png';page.save(output);outputs.append(str(output))
    print(json.dumps(dict(pages=outputs,mismatched_islands=[{k:p[k] for k in ('id','source_islands','generated_islands')} for p in art if p.get('source_islands')!=p.get('generated_islands')])))

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT));review()
