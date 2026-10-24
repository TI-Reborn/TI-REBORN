"""Local physical mitigation; p_def values come from the delivered client XML.

Damage after armor = floor(raw * 100 / (100 + sum(p_def))), minimum one
for a positive hit. This is emulator balance, not a recovered server formula.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
from .protocol.item_list import decode_item_list


class ArmorCatalog:
    def __init__(self):
        from .enhancement import EnhancementRules
        self.enhancement = EnhancementRules()
        from .equipment import armor_rules
        rules=armor_rules()
        self.slot_rules = rules
        self.items={}
        for item in ET.parse(Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml').getroot().iter('item'):
            v={x.get('key'):x.get('val') for x in item.findall('value')}
            slot={'head':1,'chest':4,'legs':8}.get(v.get('bodypart'))
            identity=int(item.get('id'))
            if identity in rules:slot=rules[identity]['slot']
            if v.get('itype')!='armor' or not slot or identity>=65500:continue
            defense=int(v.get('p_def','0'))
            if defense<0:raise ValueError('Negative armor defense')
            self.items[identity]=(slot,v.get('dogs_only')=='1',defense)

    def defense(self,inventory,*,human):
        if inventory is None:return 0
        total=0;occupied=set();slots=set()
        from .equipment import armor_coverage
        # Older saves can contain the previously permitted Exo+helmet pair.
        # Full suits take precedence without deleting/moving saved items.
        ordered = sorted(decode_item_list(inventory)[1],
                         key=lambda item: -len(armor_coverage(item.template_id, item.client_slot, self.slot_rules)))
        for item in ordered:
            rule=self.items.get(item.template_id)
            if not item.equipped or rule is None:continue
            slot,dog,value=rule
            if dog==human or item.client_slot!=slot:continue
            if slot in slots:raise ValueError('Multiple armor pieces in one slot')
            slots.add(slot)
            coverage = armor_coverage(item.template_id, slot, self.slot_rules)
            if occupied & coverage:
                continue
            occupied.update(coverage)
            total += value + self.enhancement.bonus(item.unknown_bytes_02[0], armor=True)
        # Freak Shield only protects while selected as the active weapon.
        from .equipment_bonuses import bonuses
        if human:total+=bonuses(inventory,6)['armor']
        return total


def mitigate(raw,defense):
    if raw<0 or defense<0:raise ValueError('Negative damage or defense')
    damage=max(1,raw*100//(100+defense)) if raw else 0
    return damage,raw-damage
