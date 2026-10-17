"""Prepare a reviewable catalog overlay; never modify shared/client files.

All additions clone delivered supported item classes. New IDs are explicit
server policy, verified unused in the installed CFG and diagnostic XML.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r'C:\Program Files (x86)\TIOnline\base\items.cfg')


def build():
    rules = json.loads((ROOT/'config/battle_item_effects.json').read_text(encoding='utf-8'))
    old = ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()
    templates = {int(n.get('id')): n for n in old}
    raw = SOURCE.read_bytes()
    cfg_ids = {int(i) for i in re.findall(r'^\s*item_id=(\d+)\s*$', raw.decode('cp1251'), re.M)}
    new_ids = set(range(5001, 5012))
    if new_ids & (set(templates) | cfg_ids): raise ValueError('New item ID collision')
    output = ET.Element('items'); defs = []; weapons = {}; assets = set()
    names = ('Flare', 'Night Vision Goggles', 'Light Trainer', 'Improved Trainer', 'Ultra Trainer',
             'Light Tactic Advisor', 'Improved Tactic Advisor', 'Ultra Tactic Advisor',
             'Light Blocking Exp', 'Improved Blocking Exp', 'Ultra Blocking Exp')
    images = ('itm_flare.png', 'itm_nightvision.png', 'item_light_trainer.png', 'item_improved_trainer.png',
              'item_ultra_trainer.png', 'item_light_advisor.png', 'item_improved_advisor.png',
              'item_ultra_advisor.png', 'itm_buff_sight.png', 'itm_buff_sight.png', 'itm_buff_sight.png')
    for identity, name, image in zip(sorted(new_ids), names, images):
        prototype = 317 if identity == 5001 else 33
        node = deepcopy(templates[prototype]); node.set('id', str(identity)); node.set('name', name)
        values = {v.get('key'): v for v in node.findall('value')}
        fields = {key: v.get('val') for key, v in values.items()}
        def set_field(key, value):
            value = str(value); fields[key] = value
            if key not in values: values[key] = ET.SubElement(node, 'value', key=key)
            values[key].set('val', value)
        row = rules['items'][str(identity)]
        set_field('image', image); set_field('weight', 50 if identity == 5002 else 20 if identity == 5001 else 1)
        set_field('actionPoints', row.get('ap', 0)); set_field('power', 0)
        set_field('durability', 300 if identity <= 5002 else 1)
        set_field('level_required', row.get('level', 1)); set_field('cant_buy_in_private_store', 1)
        if identity == 5001:
            for key, value in dict(p_dam=0, rnd_dam=0, radius=3, spread=2, minRange=4,
                                   maxRange=10, accuracy=60).items(): set_field(key, value)
            for operation in node.findall('for'):
                for child in list(operation):
                    if child.tag == 'consume': child.set('id', str(identity))
                    elif child.get('stat') == 'patk': child.set('val', '0')
            fields.update(item_id=str(identity), name=name)
            weapons[str(identity)] = dict(name=name, weapon_type='Throwing', damage_base=0, damage_random=0,
                attack_ap=5, reload_ap=None, ammo_id=None, bullets_count=1, min_range=4, max_range=10,
                source_fields=fields)
        output.append(node); defs.append(dict(id=identity, name=name, clone_template=prototype,
            class_policy='existing Grenade' if identity == 5001 else 'existing medkit native33 use',
            fields=fields, gold=row.get('gold', 10 if identity == 5002 else None)))
        assets.add('base/items/'+image)
    for identity in (318, 320):
        fields = {v.get('key'): v.get('val') for v in templates[identity].findall('value')}
        row = rules['items'][str(identity)]
        weapons[str(identity)] = dict(name=templates[identity].get('name'), weapon_type='Throwing',
            damage_base=0, damage_random=0, attack_ap=row['ap'], reload_ap=None, ammo_id=None,
            bullets_count=1, min_range=int(fields['minRange']), max_range=row['range'], source_fields=fields)
    assets.update(('base/items/binoculars.tga', 'base/items/itm_buff_sight.png'))
    missing = sorted(p for p in assets if not (SOURCE.parent.parent/p).is_file())
    if missing: raise ValueError('Missing installed item assets: '+repr(missing))
    ET.indent(output)
    (ROOT/'config/battle_item_catalog_extension.xml').write_bytes(ET.tostring(output, encoding='utf-8', xml_declaration=True))
    report = dict(version=1, provenance='Explicit emulator catalog policy; no historical ID claim',
        source_cfg_sha256=hashlib.sha256(raw).hexdigest(), source_cfg_count=len(cfg_ids),
        diagnostic_count=len(templates), source_diagnostic_ids=sorted(templates), new_ids=sorted(new_ids), unused_in_both_catalogs=True,
        items=defs, assets=sorted(assets), weapon_catalog_entries=weapons,
        amendments={'24':{'radius':'5','durability':'900'},
                    '35':{'actionPoints':'10','weight':'1','power':'0','image':'itm_buff_sight.png'}},
        client_adapter={'binocular':'Selected instance: native33 option255; clicked cell: native49; server recon_selection guards routing',
                        'status':'Original GUI-to-request binocular route unverified; client adapter is required before native gameplay acceptance',
                        'smoke_flare_rendering':'Native49/4B transport supported. Persistent cloud/light visual renderer still needs client acceptance; no invented map-effect packet.'})
    (ROOT/'config/battle_item_catalog_extension.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print('Prepared 11 collision-free item definitions, 3 weapon overlays and existing asset list')


if __name__ == '__main__': build()
