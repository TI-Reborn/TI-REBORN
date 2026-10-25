"""Import legacy client combat values without inventing missing reload costs."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SOURCE=Path(r'C:\Program Files (x86)\TIOnline\base\items.cfg')


def build(raw):
    records={}
    for match in re.finditer(r'Section\s+(\d+):[^\r\n]*\s*\{([^}]*)\}',raw.decode('cp1251')):
        fields=dict(re.findall(r'^\s*(\w+)=(.*)$',match[2],re.M))
        fields={k:v.strip() for k,v in fields.items()}
        item=int(fields['item_id'])
        # User's gameplay rule, 2026-10-19: M60 reaches twelve cells.
        if item==314:fields['maxRange']='12'
        if item in records:raise ValueError('Duplicate item')
        records[item]=fields
    ammo={str(i):{'name':r['name'],'pack_amount':int(r.get('packamount',1)),
                 'source_fields':r} for i,r in records.items() if r.get('itype')=='ammo'}
    weapons={}
    for i,r in records.items():
        if 'weaponType' not in r or 'p_dam' not in r:continue
        ammo_id=int(r['ammo_id']) if 'ammo_id' in r else None
        if ammo_id is not None and str(ammo_id) not in ammo:raise ValueError('Missing ammunition')
        weapons[str(i)]={'name':r['name'],'weapon_type':r['weaponType'],
            'damage_base':int(r['p_dam']),'damage_random':int(r.get('rnd_dam',0)),
            'attack_ap':int(r['actionPoints']),'reload_ap':None,'ammo_id':ammo_id,
            'bullets_count':int(r.get('bulletsCount',1)),
            'min_range':int(r.get('minRange',0)),'max_range':int(r.get('maxRange',0)),
            'source_fields':r}
    from tio.sniper_rifles import SVD,weapon
    if '312' in weapons:weapons[str(SVD)]=weapon(weapons['312'])  # SVD derives from the source sniper rifle.
    return {'source':str(SOURCE),'sha256':hashlib.sha256(raw).hexdigest(),
        'status':'Original legacy CFG values; not confirmed final server balance',
        'unknowns':['reload_ap absent','random damage distribution not recovered',
                    'missing ammo_id is not proof of unlimited ammunition',
                    'ammo actionPoints and packamount are not reload AP or magazine size'],
        'weapons':weapons,'ammunition':ammo}


if __name__=='__main__':
    data=build(SOURCE.read_bytes())
    (ROOT/'config/weapon_catalog.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Imported {len(data['weapons'])} weapons and {len(data['ammunition'])} ammunition types")
