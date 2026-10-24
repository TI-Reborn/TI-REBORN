"""Restore face/hands hidden by native armor body replacement, preserving stats."""
import json,hashlib,sys,urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/armor-missing-parts-20261021';ASSET=ROOT/'assets/armor-missing-parts-v1'
OUT.mkdir(exist_ok=True);ASSET.mkdir(exist_ok=True)
def edits(raw):
 result={208:{'showface':'1'}}
 for item in ET.fromstring(raw).iter('item'):
  v={n.get('key'):n.get('val') for n in item.findall('value')};identity=int(item.get('id'))
  if v.get('itype')!='armor' or identity>=65000 or v.get('dogs_only')=='1' or v.get('freaks_only')=='1':continue
  if v.get('bodypart')=='chest' or identity in (263,264):
   assert 'model_2' not in v and 'w_model_2' not in v
   result[identity]={'model_2':'chr_woman_hands' if identity in (263,264) else 'chr_man_hands','texture_2':'chr_woman_body.jpg' if identity in (263,264) else 'chr_man_body.jpg',
                     'w_model_2':'chr_woman_hands','w_texture_2':'chr_woman_body.jpg'}
 return result
def patch(raw):
 for identity,fields in edits(raw).items():
  start=raw.index(('<item id="'+str(identity)+'" ').encode());end=raw.index(b'</item>',start);block=raw[start:end];newline=b'\r\n' if b'\r\n' in block else b'\n'
  for key,value in fields.items():
   old=next((line for line in block.splitlines(keepends=True) if ('key="'+key+'"').encode() in line),None)
   new=('    <value key="'+key+'" val="'+value+'" />').encode()+newline
   if old:block=block.replace(old,new)
   else:block=block.rstrip()+newline+new+b'  '
  raw=raw[:start]+block+raw[end:]
 return raw
def validate(before,after):
 def structure(node):return None if node is None else (node.tag,dict(node.attrib),tuple(structure(c) for c in node))
 a={i.get('id'):i for i in ET.fromstring(before).iter('item')};b={i.get('id'):i for i in ET.fromstring(after).iter('item')};expected=edits(before);assert a.keys()==b.keys()
 changed=[]
 for identity,old in a.items():
  values=lambda node:{n.get('key'):n.get('val') for n in node.findall('value')}
  av,bv=values(old),values(b[identity]);assert bv=={**av,**expected.get(int(identity),{})},identity
  assert structure(old.find('for'))==structure(b[identity].find('for'))
  if av!=bv:changed.append(int(identity))
 assert set(changed)==set(expected) and patch(before)==after
 return dict(passed=True,changed_items=sorted(changed),stats_slots_restrictions_unchanged=True,helmet208_face_visible=True,hands_included_for_all_human_chest_and_female_exo=True)
if __name__=='__main__':
 raw=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read();baseline=OUT/'manifest-before.json'
 if baseline.exists():assert baseline.read_bytes()==raw
 else:baseline.write_bytes(raw)
 m=json.loads(raw);assert m['version']=='2026.10.21.4';row=next(r for r in m['files'] if r['path']=='base/shared config/items.xml')
 before=urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+row['sha256'],timeout=30).read();assert hashlib.sha256(before).hexdigest()==row['sha256']
 (OUT/'items-before.xml').write_bytes(before);after=patch(before);result=validate(before,after);(ASSET/'items.xml').write_bytes(after);(OUT/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
