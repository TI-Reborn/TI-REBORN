"""Read-only contest scene review; static conservative grid, not deployed gameplay."""
from pathlib import Path
from collections import Counter,deque
import json,zlib,struct,hashlib,html
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
BASE=Path(r'C:\Program Files (x86)\TIOnline\base')
OUT=ROOT/'reports/reservation-maps'
COLORS={0:'#e9e3d3',1:'#e9e3d3',2:'#819ca0',3:'#333d49',4:'#819ca0'}
FONT=Path('C:/Windows/Fonts/arial.ttf')
def font(size):return ImageFont.truetype(str(FONT),size)
def neighbors(p,w,h):
 x,y=p
 return [(a,b) for a,b in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)) if 0<=a<w and 0<=b<h]
def analyze(w,h,tiles,boxes,doors,opened):
 blocked={(i%w,i//w) for i,t in enumerate(tiles) if t in (2,3,4)}|set(boxes)
 for x,y,state in doors:
  if opened or state==2:blocked.discard((x,y))
  else:blocked.add((x,y))
 free={(x,y) for y in range(h) for x in range(w)}-blocked;left=set(free);components=[]
 while left:
  start=min(left);seen={start};left.remove(start);todo=deque([start])
  while todo:
   for p in neighbors(todo.popleft(),w,h):
    if p in left:left.remove(p);seen.add(p);todo.append(p)
  components.append(seen)
 main=max(components,key=len,default=set())
 broad={p for p in main if all((p[0]+dx,p[1]+dy) in free for dx in (-1,0,1) for dy in (-1,0,1))}
 necks={p for p in main if ((p[0]-1,p[1]) in blocked and (p[0]+1,p[1]) in blocked) or ((p[0],p[1]-1) in blocked and (p[0],p[1]+1) in blocked)}
 accessible=[p for p in boxes if any(q in main for q in neighbors(p,w,h))]
 return dict(blocked=sorted(blocked),main=sorted(main),narrow=sorted(necks),broad=sorted(broad),free=len(free),free_pct=round(100*len(free)/(w*h),1),main_pct=round(100*len(main)/max(1,len(free)),1),components=len(components),isolated=len(free-main),broad_pct=round(100*len(broad)/max(1,len(main)),1),accessible_boxes=len(accessible),unreachable_boxes=[p for p in boxes if p not in accessible])
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 audit=json.loads((ROOT/'evidence/reservation-map-resource-audit.json').read_text())
 doorlib=json.loads((ROOT/'evidence/reservation-map-doors.json').read_text())
 maps=[]
 for entry in audit['sets']:
  if not entry['file'].startswith('contest/'):continue
  source=BASE/'maps'/entry['file'];blob=source.read_bytes();raw=zlib.decompress(blob[16:])
  assert len(raw)==struct.unpack_from('<I',blob,8)[0]
  w,h,n=struct.unpack_from('<3H',raw,12);tiles=list(raw[32:32+2*w*h:2]);assert set(tiles)<={0,1,2,3,4}
  models=entry['model_records'];assert n==len(models)
  boxes=sorted({(m['x'],m['y']) for m in models if m['name'].lower().startswith('item_steel_box')})
  doors=[];unknown=set()
  for m in models:
   rule=doorlib.get(m['name'])
   if not rule:continue
   if rule['status']!='native decoded':unknown.add(m['name'])
   for d in rule['doors']:
    x,y=m['x']+d['x'],m['y']+d['y']
    if 0<=x<w and 0<=y<h:doors.append((x,y,d['state']))
    else:unknown.add(m['name']+' (door outside grid)')
  assert all(0<=x<w and 0<=y<h for x,y in boxes)
  doors=sorted(set(doors));name=source.stem.removeprefix('contest_').removesuffix('_01')
  landmarks=[m for m in models if m['name'] in doorlib or any(k in m['name'].lower() for k in ('assault_flag','crater_','water_tower','oil_tank'))]
  row=dict(name=name,file=entry['file'],sha256=hashlib.sha256(blob).hexdigest(),width=w,height=h,tiles=tiles,boxes=boxes,doors=doors,unknown_doors=sorted(unknown),models=models,landmarks=landmarks)
  # Contest marker records: checked against all nine files and flag models.
  end=32+2*w*h+72*n
  marker_count=struct.unpack_from('<I',raw,end+48)[0]
  assert marker_count==3
  markers=[]
  for i in range(marker_count):
   offset=end+72+i*10760;label_offset=offset+10248
   length=raw[label_offset];label=raw[label_offset+1:label_offset+1+length].decode('ascii').strip()
   x,y=struct.unpack_from('<2i',raw,offset)
   assert label in ('True_skill 1 team','True_skill 2 team','True_skill center')
   assert any(o['name']=='assault_flag.t' and (o['x'],o['y'])==(x,y) for o in models)
   markers.append(dict(name=label,x=x,y=y,kind='flag',offset=offset))
  tail=end+72+marker_count*10760
  assert len(raw)-tail==3402
  length=raw[tail];ground_label=raw[tail+1:tail+1+length].decode('ascii')
  assert ground_label in ('village','military','forest','junk','town')
  row.update(markers=markers,ground_label=ground_label,spawn_status='not recovered; flag markers are not spawns')
  row['closed']=analyze(w,h,tiles,boxes,doors,False);row['open']=analyze(w,h,tiles,boxes,doors,True)
  maps.append(row)
 # No ranking from name alone: combine openness, access and known visual families.
 for m in maps:
  m['image']=m['name']+'.png';render(m,OUT/m['image'])
 (OUT/'maps.json').write_text(json.dumps(maps,ensure_ascii=False,indent=2),encoding='utf-8')
 sheet=Image.new('RGB',(1500,1740),'#131d29');d=ImageDraw.Draw(sheet)
 d.text((25,18),'RESERVATION / оригинальные сцены',font=font(34),fill='white')
 d.text((25,65),'Планы исходной сетки • подтверждённые двери открыты • не игровой рендер',font=font(20),fill='#b8c9d5')
 for i,m in enumerate(maps):
  im=Image.open(OUT/m['image']);im.thumbnail((490,530));sheet.paste(im,(10+(i%3)*495,115+(i//3)*535))
 sheet.save(OUT/'overview.png')
 template=(ROOT/'tools/reservation_review_template.html').read_text(encoding='utf-8')
 (OUT/'index.html').write_text(template.replace('__MAP_DATA__',json.dumps(maps,ensure_ascii=False).replace('</','<\\/')),encoding='utf-8')
 for m in maps:print(m['name'], {k:m['open'][k] for k in ('free_pct','main_pct','broad_pct','accessible_boxes','isolated')},'boxes',len(m['boxes']),'doors',len(m['doors']),'unknown',m['unknown_doors'])
def render(m,path):
 im=Image.new('RGB',(1000,1080),'#182434');d=ImageDraw.Draw(im);f=font(26);small=font(18)
 d.text((30,18),m['name'].upper(),font=font(32),fill='white')
 a=m['open'];d.text((30,62),f"Свободно {a['free_pct']}%  •  ящиков {len(m['boxes'])}  •  грунт {m['ground_label']}",font=small,fill='#c9d5df')
 size=22;ox=70;oy=115;blocked=set(map(tuple,a['blocked']));mainset=set(map(tuple,a['main']));doors={(x,y) for x,y,_ in m['doors']}
 for y in range(m['height']):
  for x in range(m['width']):
   p=(x,y);color=COLORS[m['tiles'][y*m['width']+x]]
   if p in doors:color='#5cad80'
   elif p not in blocked and p not in mainset:color='#bca4ca'
   d.rectangle((ox+x*size,oy+y*size,ox+(x+1)*size-1,oy+(y+1)*size-1),fill=color)
 for x in range(0,m['width'],5):d.text((ox+x*size,oy-25),str(x),font=small,fill='#c9d5df')
 for y in range(0,m['height'],5):d.text((ox-32,oy+y*size),str(y),font=small,fill='#c9d5df')
 for x,y in a['narrow']:
  cx=ox+x*size+size//2;cy=oy+y*size+size//2;d.ellipse((cx-3,cy-3,cx+3,cy+3),fill='#dd5445')
 for index,(x,y) in enumerate(m['boxes'],1):
  cx=ox+x*size;cy=oy+y*size;d.rectangle((cx,cy,cx+size-1,cy+size-1),fill='#e1a53e',outline='#6b4200');d.text((cx+2,cy+1),str(index),font=font(13),fill='#152130')
 for mark in m['markers']:
  label='C' if mark['name'].endswith('center') else ('1' if '1 team' in mark['name'] else '2')
  cx=ox+mark['x']*size;cy=oy+mark['y']*size
  d.ellipse((cx,cy,cx+size-1,cy+size-1),fill={'1':'#4398ef','2':'#e56a72','C':'#eeeeee'}[label],outline='#142435')
  d.text((cx+6,cy+2),label,font=font(13),fill='#152130')
 d.text((30,1054),'Круги 1 / 2 / C: исходные флаги TrueSkill, не точки появления.',font=small,fill='#e5b765')
 d.text((30,965),'Светлое: проход  •  тёмное: класс 3  •  серо-синее: классы 2/4',font=small,fill='#c9d5df')
 d.text((30,996),'Зелёное: дверь  •  жёлтое: ящик  •  красная точка: узкая клетка',font=small,fill='#c9d5df')
 d.text((30,1027),'Фиолетовое: отдельная область. Динамика TILE учтена не полностью.',font=small,fill='#c9d5df')
 im.save(path)
if __name__=='__main__':main()
