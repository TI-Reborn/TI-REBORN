"""Translate legacy effect fields to the native XML tooltip bonus records.

silver.dll a72ac1..a72c1d builds an it_<stat> record at metadata+66c
for generic for/add stats. effect_string/effect_value are not read there.
"""
import xml.etree.ElementTree as ET

EFFECTS = {256: ('melee', '25'),
           262: ('sight', '1'),
           264: ('maxload', '200'), 341: ('armor', '85')}


def normalize(item):
    # Remove descriptions introduced by our earlier six-item patch.
    removed = {254: 'melee', 263: 'maxload'}.get(int(item.get('id')))
    if removed:
        for stats in item.findall('for'):
            for node in list(stats.findall(f"add[@stat='{removed}']")):
                stats.remove(node)
    values={v.get('key'):v for v in item.findall('value')}
    if values.get('itype') is not None and values['itype'].get('val') == 'armor':
        # Loader a7050b reads type separately from itype. a72d5f skips
        # synthesizing an it_armor bonus only when this type is armor.
        node=values.get('type')
        if node is None:node=ET.SubElement(item,'value',key='type')
        node.set('val','armor')
    effect = EFFECTS.get(int(item.get('id')))
    if effect is None:
        return False
    stat, value = effect
    stats = item.find('for')
    if stats is None:
        stats = ET.SubElement(item, 'for')
    nodes = list(stats.findall(f"add[@stat='{stat}']"))
    node = nodes[0] if nodes else ET.SubElement(stats, 'add', stat=stat)
    node.set('val', value)
    for duplicate in nodes[1:]:
        stats.remove(duplicate)
    return True
