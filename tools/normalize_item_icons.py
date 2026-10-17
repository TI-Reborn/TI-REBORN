"""Replace eight missing legacy icon references with installed client assets.

These are compatibility substitutes, not recovered original artwork. Existing
valid/custom icons are preserved. No files in the installed client are edited.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ICONS = Path(r'C:/Program Files (x86)/TIOnline/base/items')
REPLACEMENTS = {
    318: ('itm_smokegrenade.png', 'itm_stungrenade.png'),
    319: ('itm_molotov.png', 'itm_shampagne.png'),
    321: ('itm_landmine.png', 'itm_mine_green.png'),
    223: ('itm_rags_armor.png', 'itm_military_armor_1.png'),
    224: ('itm_rags_legs.png', 'itm_military_legs_1.png'),
    236: ('itm_raider_helmet.png', 'itm_battle_helmet_1.png'),
    237: ('itm_raider_armor.png', 'itm_battle_armor_1.png'),
    238: ('itm_raider_legs.png', 'itm_battle_legs_1.png'),
}


def normalize(fields, icons=ICONS):
    pair = REPLACEMENTS.get(int(fields['item_id']))
    if pair is None or fields.get('image') != pair[0] or (icons / pair[0]).is_file():
        return
    if not (icons / pair[1]).is_file():
        raise ValueError(f'Icon replacement unavailable: {pair[1]}')
    fields['image'] = pair[1]


def main():
    path = ROOT / 'evidence/items_diagnostic.xml'
    tree = ET.parse(path)
    changes = []
    for item in tree.getroot():
        node = next((n for n in item.findall('value') if n.get('key') == 'image'), None)
        if node is None:
            continue
        fields = dict(item_id=item.get('id'), image=node.get('val'))
        normalize(fields)
        if fields['image'] != node.get('val'):
            changes.append(dict(item_id=int(item.get('id')), name=item.get('name'),
                                previous=node.get('val'), replacement=fields['image'],
                                asset_sha256=hashlib.sha256((ICONS / fields['image']).read_bytes()).hexdigest()))
            node.set('val', fields['image'])
    missing = [node.get('val') for item in tree.getroot() for node in item.findall('value')
               if node.get('key') == 'image' and not (ICONS / node.get('val')).is_file()]
    if missing:
        raise ValueError(f'Unresolved image references: {missing}')
    if changes:
        ET.indent(tree)
        tree.write(path, encoding='utf-8', xml_declaration=True)
        (ROOT / 'evidence/sc_icon_replacements.json').write_text(json.dumps(dict(
            status='LOCAL_COMPATIBILITY_SUBSTITUTES_NOT_ORIGINAL_ART',
            missing_references_after=missing, changes=changes), indent=2)+'\n', encoding='utf-8')
    print(f'Updated {len(changes)} icon references; no missing image files in shared item XML')


if __name__ == '__main__':
    main()
