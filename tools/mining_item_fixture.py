"""Restore missing mining bindings from native IDs and installed model assets.

These four records are not present in the legacy items.cfg. Numeric mining
rules come from the manual/native pickup dialog; animation/model bindings
use existing assets. See MINING.md for the provisional fields.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

RECORDS = {
    51: ('Crystals', dict(weight='1', durability='1')),
    52: ('Mining Drill', dict(weight='100', durability='1', containedItem='51',
        containedItemId='51', image='itm_gasdrill.png', actionPoints='1',
        equipable='true', canSplit='false')),
    353: ('Sick Miner Attack', dict(weaponType='Melee', weaponAttack='None',
        actionPoints='5', p_dam='57', rnd_dam='22', minRange='1', maxRange='1',
        weight='0', durability='1', empty='1', accuracy='100',
        anim_idle='mob_sickminer_idle', anim_run='mob_sickminer_walk',
        anim_fire='mob_sickminer_attack')),
    65513: ('Sick Miner Body', dict(itype='armor', bodypart='chest',
        model_1='mob_sickminer', texture_1='mob_sickminer.jpg',
        anim_idle='mob_sickminer_idle', anim_run='mob_sickminer_walk',
        anim_fire='mob_sickminer_attack')),
}


def append_records(root):
    for identity, (name, fields) in RECORDS.items():
        for old in list(root):
            if old.get('id') == str(identity): root.remove(old)
        item = ET.SubElement(root, 'item', id=str(identity), name=name)
        values = {**fields, 'cant_buy_in_private_store':'1'}
        for key, value in values.items(): ET.SubElement(item, 'value', key=key, val=value)
        if __package__:
            from .normalize_weapon_xml import normalize
        else:
            from normalize_weapon_xml import normalize
        normalize(item, values)


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml'
    tree = ET.parse(target); append_records(tree.getroot()); ET.indent(tree)
    tree.write(target, encoding='utf-8', xml_declaration=True)
    print('Mining crystal, drill, NPC weapon and body bindings restored')
