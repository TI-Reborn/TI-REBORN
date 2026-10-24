"""Assemble Blender renders for inspection; no AI image editing."""
import json,math,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/armor-fit-20261021';FRONT='--front' in sys.argv;VETERAN='--veteran' in sys.argv;report=json.loads((OUT/('blender-reference-veteran.json' if VETERAN else 'blender-reference-front.json' if FRONT else 'blender-reference-renders.json')).read_text())
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16);small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',12)
for resource in range(1,7):
 rows=[r for r in report['cases'] if r['resource']==resource];columns=5 if len(rows)>10 else 3;width=280;height=375
 if not rows:continue
 sheet=Image.new('RGB',(columns*width,math.ceil(len(rows)/columns)*height),(22,28,34));d=ImageDraw.Draw(sheet)
 for i,row in enumerate(rows):
  x=i%columns*width;y=i//columns*height;sheet.paste(Image.open(OUT/('renders-veteran' if VETERAN else 'renders-front' if FRONT else 'renders')/row['render']).convert('RGB'),(x,y));d.text((x+6,y+341),str(row['item'])+' '+row['name'][:30],font=small,fill='white')
 sheet.save(OUT/('armor-veteran.jpg' if VETERAN else f'armor-class-{resource}'+('-front' if FRONT else '')+'.jpg'),quality=92)
print(json.dumps({'sheets':len({r['resource'] for r in report['cases']}),'cases':len(report['cases'])}))
