"""Map legacy weapon stats into the bindings used by the original XML reader."""
from pathlib import Path
import xml.etree.ElementTree as ET


def normalize(item,fields):
    if 'weaponType' in fields and 'p_dam' in fields:
        stats=item.find('for')
        if stats is None:stats=ET.SubElement(item,'for')
        # Native XML: set/patk -> base132, add/patk -> random134.
        # a7a4de displays base..base+random. power is a different effect field.
        for operation,key in (('set','p_dam'),('add','rnd_dam')):
            nodes=[n for n in stats.findall(operation) if n.get('stat')=='patk']
            node=nodes[0] if nodes else ET.SubElement(stats,operation,stat='patk')
            node.set('val',fields.get(key,'0'))
            for duplicate in nodes[1:]:stats.remove(duplicate)
        # a72a17 / a72a59: fractional XML stat times 100, then x87 Round.
        for stat,key,default in (('accuracy','accuracy','100'),('accuracyGain','accuracy_gain_amount','0')):
            nodes=[n for n in stats.findall('add') if n.get('stat')==stat]
            node=nodes[0] if nodes else ET.SubElement(stats,'add',stat=stat)
            node.set('val',format(int(fields.get(key,default))/100,'.2f'))
            for duplicate in nodes[1:]:stats.remove(duplicate)
            for invalid in list(stats.findall(f"set[@stat='{stat}']")):stats.remove(invalid)
    if 'weaponAttack' not in fields:return
    values={e.get('key'):e for e in item.findall('value')}
    attack=values.get('attackType')
    if attack is None:attack=ET.SubElement(item,'value',key='attackType')
    attack.set('val',fields['weaponAttack'])
    # a71ca2 reads integer value damageFade (default 100) into metadata+136.
    fade=values.get('damageFade')
    if fade is None:fade=ET.SubElement(item,'value',key='damageFade')
    fade.set('val',fields.get('damage_fade','100'))
    ammo=fields.get('ammo_id')
    amount=fields.get('bulletsCount','1')
    if fields.get('item_id') in ('317','340'):ammo,amount=fields['item_id'],'1'
    if ammo is not None:
        stats=item.find('for')
        if stats is None:stats=ET.SubElement(item,'for')
        consume=stats.find('consume')
        if consume is None:consume=ET.SubElement(stats,'consume')
        consume.set('id',ammo);consume.set('amount',amount)


if __name__=='__main__':
    path=Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml'
    tree=ET.parse(path)
    for item in tree.getroot():
        fields={e.get('key'):e.get('val') for e in item.findall('value')}
        fields['item_id']=item.get('id')
        normalize(item,fields)
    ET.indent(tree)
    tree.write(path,encoding='utf-8',xml_declaration=True)
    print('Native patk, range damage/accuracy, attackType and ammo bindings updated in client XML fixture')
