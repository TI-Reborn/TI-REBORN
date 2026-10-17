"""Import original local CFG records and build a local-priced ordinary shop."""
import hashlib,json,re
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(r'C:\Program Files (x86)\TIOnline\base\items.cfg')

# Legacy noob_*/woman_* meshes no longer ship in this client. Local compatibility
# mapping to the matching chr_* meshes that are present; source CFG is untouched.
BODY_MODELS={65500:('chr_man_head',),65501:('chr_man_body','chr_man_hands'),
             65502:('chr_man_legs',),65505:('chr_woman_head',),
             65506:('chr_woman_body','chr_woman_hands'),65507:('chr_woman_legs',)}

def main():
    raw=SOURCE.read_bytes(); text=raw.decode('cp1251'); records=[]; source_records={}
    for match in re.finditer(r'Section\s+(\d+):[^\r\n]*\s*\{([^}]*)\}',text):
        fields={}
        for line in match[2].splitlines():
            if '=' in line:
                key,value=line.strip().split('=',1);fields[key]=value
        source_records[fields['item_id']]=dict(fields)
        # Legacy CFG infers clothing from bodypart; XML loader defaults missing
        # itype to weapon1. Its explicit armor branch sets type9 at a715da.
        if 'itype' not in fields and fields.get('bodypart') in {'head','chest','legs','complexarmor'}:
            fields['itype']='armor'
        if int(fields['item_id']) in BODY_MODELS:
            meshes=BODY_MODELS[int(fields['item_id'])]
            fields={k:v for k,v in fields.items() if not re.match(r'(model|texture|mask)_\d+$',k)}
            texture=('chr_man' if int(fields['item_id'])<65505 else 'chr_woman')+('_head.jpg' if fields['bodypart']=='head' else '_body.jpg')
            for n,mesh in enumerate(meshes,1):
                assert (SOURCE.parent/'models'/f'{mesh}.mdjx').is_file()
                assert (SOURCE.parent/'models'/texture).is_file()
                fields[f'model_{n}']=mesh;fields[f'texture_{n}']=texture
        from normalize_armor_models import normalize as normalize_armor
        normalize_armor(fields)
        from normalize_item_icons import normalize as normalize_icons
        normalize_icons(fields)
        from normalize_item_stacking import normalize as normalize_stacking
        normalize_stacking(fields)
        records.append(fields)
    assert len({r['item_id'] for r in records})==len(records)
    root=ET.Element('items'); report=[]
    for fields in records:
        item=ET.SubElement(root,'item',id=fields['item_id'],name=fields['name'])
        for key,value in fields.items():
            if key not in {'item_id','name'}:ET.SubElement(item,'value',key=key,val=value)
        # Native shop clothing filters require nonzero metadata+0x690.
        # XML loader a7138e/a72435/a72ab5 reads for/add stat=pdef, not CFG p_def.
        if 'p_def' in fields:
            stats=ET.SubElement(item,'for')
            ET.SubElement(stats,'add',stat='pdef',val=fields['p_def'])
        from normalize_weapon_xml import normalize
        normalize(item,fields)
        from normalize_equipment_effects import normalize as normalize_effects
        normalize_effects(item)
        original=source_records[fields['item_id']]
        report.append({'id':fields['item_id'],'included':{k:v for k,v in fields.items() if k not in {'item_id','name'}},
                       'source_fields':original,
                       'omitted':{k:v for k,v in original.items() if k not in fields},
                       'changed':{k:{'source':original.get(k),'local':v} for k,v in fields.items() if original.get(k)!=v}})
    from mining_item_fixture import append_records
    append_records(root)
    ET.indent(root)
    (ROOT/'evidence/items_diagnostic.xml').write_bytes(ET.tostring(root,encoding='utf-8',xml_declaration=True))
    (ROOT/'evidence/items_diagnostic_provenance.json').write_text(json.dumps({'source':str(SOURCE),'source_sha256':hashlib.sha256(raw).hexdigest(),'status':'LOCAL_CFG_CATALOG_WITH_XML_ARMOR_NORMALIZATION','normalization':'Missing itype becomes armor for bodypart head/chest/legs/complexarmor; p_def also emitted as for/add stat=pdef val=source value; six default human body records use verified existing chr_man/chr_woman meshes and textures in place of missing legacy files; armor meshes/textures normalized to installed man_armor/woman_armor assets, female XML w_model/w_texture bindings added, dog originals retained; generic208/222 use local fallback models; per-record changes listed.','records':report},indent=2)+'\n')
    # Preserve stable IDs for existing offers and saved purchase probes.
    config_path=ROOT/'config/city_catalogs.json'
    config=json.loads(config_path.read_text(encoding='utf-8'))
    eligible=[r for r in records if int(r['item_id'])>2 and int(r['item_id'])<65000
              and r.get('image') and r.get('durability')
              and r.get('cant_buy_in_private_store','0')!='1']
    eligible.sort(key=lambda r: (0 if r['item_id']=='301' else 1 if r['item_id']=='326' else 2,int(r['item_id'])))
    config['item_categories']={'0':[dict(unknown_u32_01=n,unknown_u32_02=int(r.get('packamount','1')),
        item_id=int(r['item_id']),unknown_u32_03=100,durability=int(r['durability']),unknown_u8=0)
        for n,r in enumerate(eligible,1)]}
    config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'evidence/shop_catalog_provenance.json').write_text(json.dumps(dict(
        source=str(SOURCE),source_sha256=hashlib.sha256(raw).hexdigest(),
        price_policy='LOCAL_TEST_PRICE_100_CREDITS_PER_OFFER_PACK_NOT_SOURCE_PRICES',
        selection='image + durability; excludes currency, service models >=65000 and cant_buy_in_private_store=1',
        offers=[dict(id=int(r['item_id']),name=r['name'],bodypart=r.get('bodypart'),weapon_type=r.get('weaponType'),item_type=r.get('itype')) for r in eligible]),indent=2)+'\n',encoding='utf-8')
    print(f'Built {len(records)} source records and {len(eligible)} shop offers.')

if __name__=='__main__':main()

