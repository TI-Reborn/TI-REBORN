"""Restore native leg rendering for the existing head-mounted joke item 206.

Keep its original equipment slot, stats, hat geometry and textures. Native armor
replaces the selected body part, so the legs must be an explicit second model.
"""
import json,sys
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/armor-fit-20261021';ASSET=ROOT/'assets/armor-fit-fixes-v1'
FIELDS={'model_2':'chr_man_legs','texture_2':'chr_man_body.jpg','w_model_2':'chr_woman_legs','w_texture_2':'chr_woman_body.jpg'}
def patch(raw):
 start=raw.index(b'<item id="206" ');end=raw.index(b'</item>',start);block=raw[start:end]
 assert b'<value key="bodypart" val="legs"' in block
 assert all(('key="'+k+'"').encode() not in block for k in FIELDS)
 newline=b'\r\n' if b'\r\n' in block else b'\n'
 marker=b'    <for>';assert block.count(marker)==1
 addition=b''.join(('    <value key="'+k+'" val="'+v+'" />').encode()+newline for k,v in FIELDS.items())
 return raw[:start]+block.replace(marker,addition+marker)+raw[end:]
def validate(before,after):
 a=ET.fromstring(before);b=ET.fromstring(after);aa={i.get('id'):ET.tostring(i) for i in a.iter('item')};bb={i.get('id'):ET.tostring(i) for i in b.iter('item')}
 assert aa.keys()==bb.keys() and {k for k in aa if aa[k]!=bb[k]}=={'206'}
 old=next(i for i in a.iter('item') if i.get('id')=='206');new=next(i for i in b.iter('item') if i.get('id')=='206')
 av={v.get('key'):v.get('val') for v in old.findall('value')};bv={v.get('key'):v.get('val') for v in new.findall('value')}
 assert bv=={**av,**FIELDS} and ET.tostring(old.find('for'))==ET.tostring(new.find('for'))
 assert patch(before)==after
 return dict(passed=True,only_changed_item=206,added_fields=FIELDS,original_slot_and_stats_preserved=True,original_hat_preserved=True,body_replacement_corrected=True)
if __name__=='__main__':
 before=(OUT/'source/base/shared config/items.xml').read_bytes();after=patch(before);r=validate(before,after)
 ASSET.mkdir(exist_ok=True);(ASSET/'items.xml').write_bytes(after);(OUT/'fix-validation.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
