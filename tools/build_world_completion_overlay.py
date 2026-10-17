"""Reviewable world XML overlay; never mutates published or shared zones XML."""
from pathlib import Path
import hashlib
import json
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.world_completion import policy


def main():
    source=ROOT/'evidence/zones_diagnostic.xml';raw=source.read_bytes();existing=ET.fromstring(raw)
    ids={int(t.get('id')) for t in existing};expected=set(range(1,18))
    if ids!=expected:raise ValueError('Review source world IDs before rebuilding overlay')
    root=ET.Element('towns');changes=[]
    records=policy()['locations'];all_bounds={}
    for town in existing:
        values={v.get('key'):v.get('val') for v in town.findall('value')}
        all_bounds[int(town.get('id'))]=tuple(int(values[k]) for k in ('x1','y1','x2','y2'))
    for r in records:
        if r['id']>=18 and r['id'] in ids:raise ValueError('New world ID collision')
        all_bounds[r['id']]=tuple(r['bounds'])
        t=ET.SubElement(root,'town',id=str(r['id']),name=r['name'])
        fields=dict(enabled='1',type=r['kind'],background=r['background'],x1=r['bounds'][0],y1=r['bounds'][1],
            x2=r['bounds'][2],y2=r['bounds'][3],size=r['bounds'][2]-r['bounds'][0],minlevel=r['levels'][0],maxlevel=r['levels'][1],
            drop='false',privateStore='false',arena=str(r['arena']).lower(),equip=str(r['carry_items']).lower())
        if r.get('assault_map'):fields['assaultMap']=r['assault_map']
        if not r['arena']:fields.update(shop='false',market='false',mercShop='false')
        for key,value in fields.items():ET.SubElement(t,'value',key=key,val=str(value))
        changes.append(dict(id=r['id'],kind='amendment' if r['id'] in ids else 'addition',source=r['source'],bounds=r['bounds']))
    # Check every added/moved bounds against all source records. Existing
    # historical overlaps elsewhere are not silently changed by this overlay.
    for r in records:
        if r['id'] in (4,10):continue
        a=tuple(r['bounds'])
        for key,b in all_bounds.items():
            if key!=r['id'] and max(a[0],b[0])<=min(a[2],b[2]) and max(a[1],b[1])<=min(a[3],b[3]):
                raise ValueError(f'World bounds collision {r["id"]}/{key}')
    assert set(ids)|{r['id'] for r in records}==set(range(1,23)), 'Native F0/98 ID-minus-one requires contiguous IDs'
    ET.indent(root);out=ROOT/'config/world_completion_zones.xml'
    out.write_bytes(ET.tostring(root,encoding='utf-8',xml_declaration=True))
    (ROOT/'evidence/world_completion_overlay.json').write_text(json.dumps(dict(source=str(source.relative_to(ROOT)),
        source_sha256=hashlib.sha256(raw).hexdigest(),overlay_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
        contiguous_native_ids=list(range(1,23)),new_ids=list(range(18,23)),changes=changes,
        source_id7_relocated=True,mine14_preserved=True,policy='New ID/coordinates are emulator policy; exact source geometry retained for towns4/10'),indent=2)+'\n',encoding='utf-8')
    base=Path(r'C:\Program Files (x86)\TIOnline\base')
    fragments=json.loads((ROOT/'config/world_completion_maps.json').read_text())['fragments'];assets={}
    def asset(path,expected=None):
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if expected is not None and digest!=expected:raise ValueError('World original asset hash mismatch: '+str(path))
        assets[path.relative_to(base).as_posix()]=dict(sha256=digest,size=path.stat().st_size)
    for name,fragment in fragments.items():
        asset(base/'maps'/name,fragment['sha256'])
        for model in fragment['models']:
            paths=list((base/'setting').rglob(model))
            if len(paths)!=1:raise ValueError('World original model missing/ambiguous: '+model)
            asset(paths[0],fragment['door_models_sha256'][model])
    for r in records:asset(base/'pda'/(r['background']+'.jpg'))
    asset(base/'ground.xml');asset(base/'towns.cfg')
    (ROOT/'evidence/world_completion_assets.json').write_text(json.dumps(dict(
        provenance='Pinned installed original models/maps/backgrounds; textures remain in existing original setting asset tree',
        base=str(base),assets=assets,models_count=len({n for f in fragments.values() for n in f['models']})),indent=2)+'\n',encoding='utf-8')
    print('World overlay IDs18-22 + source4/10 + explicit Base7 relocation: all new/moved rectangles collision-free; Mine14 preserved')


if __name__=='__main__':main()
