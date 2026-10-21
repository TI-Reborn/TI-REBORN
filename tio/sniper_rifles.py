"""SVD catalog extension: explicit emulator ID; manual printed p60.

The shipped legacy CFG has no SVD record. Range15, reference7, AP9, ammo6,
one bullet, accuracy90, level5, weight200 and price1650 come from the manual.
The base55+20 and AWP120% fade are an explicit compatible reconstruction;
the manual's illustrated damage endpoints do not fit one native fade factor.
Other presentation/durability defaults inherit the existing AWP record.
"""
from copy import deepcopy

SVD = 5013
PRICE = 1650


def weapon(awp):
    row=deepcopy(awp)
    row.update(name='SVD',damage_base=55,damage_random=20,min_range=7,max_range=15)
    row['source_fields'].update(item_id=str(SVD),name='SVD',p_dam='55',rnd_dam='20',
        minRange='7',maxRange='15',accuracy='90',level_required='5',
        image='item_svd.png',model_1='weapon_svd',sound='svd')
    return row


def append_item(root):
    """Clone only the compatible AWP metadata; normalize native stat bindings."""
    import xml.etree.ElementTree as ET
    from tools.normalize_weapon_xml import normalize
    if root.find(f"item[@id='{SVD}']") is not None:raise ValueError('SVD ID already used')
    source=root.find("item[@id='312']")
    if source is None:raise ValueError('AWP metadata required')
    node=deepcopy(source);node.set('id',str(SVD));node.set('name','SVD')
    overrides=dict(p_dam='55',rnd_dam='20',minRange='7',maxRange='15',accuracy='90',
        level_required='5',image='item_svd.png',model_1='weapon_svd',sound='svd')
    for key,value in overrides.items():
        entry=node.find(f"value[@key='{key}']")
        if entry is None:entry=ET.SubElement(node,'value',key=key)
        entry.set('val',value)
    fields={v.get('key'):v.get('val') for v in node.findall('value')}
    fields['item_id']=str(SVD);normalize(node,fields);root.append(node)
    return node


def append_offer(catalog):
    rows=catalog['item_categories']['0']
    if any(r['item_id']==SVD for r in rows):raise ValueError('SVD shop offer already used')
    identity=max(r['unknown_u32_01'] for category in catalog['item_categories'].values() for r in category)+1
    rows.append(dict(unknown_u32_01=identity,unknown_u32_02=1,item_id=SVD,
        unknown_u32_03=PRICE,durability=300,unknown_u8=0))
