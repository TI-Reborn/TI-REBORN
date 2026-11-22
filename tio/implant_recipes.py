"""Native recipe aliases for the source templates actually carried by an account.

All 55 families are available; publishing every extra-template pairing at once
exceeds the client's fixed 50,000-byte compressed configuration buffer.
Aliases are previews only and are never issued or accepted as owned items.
"""
from collections.abc import Iterable
from copy import deepcopy
from itertools import combinations
from xml.etree import ElementTree as ET

from .implants import catalog, combo_recipes, family, policy, variant
from .protocol.item_list import decode_item_list


def available_pairs(inventories: Iterable[bytes]) -> tuple[tuple[int, int], ...]:
    result = set()
    bases = set(policy()['combo']['families'])
    for inventory in inventories:
        templates = sorted({i.template_id for i in decode_item_list(inventory)[1]
                            if i.template_id in catalog() and family(i.template_id) in bases})
        for first, second in combinations(templates, 2):
            if family(first) != family(second) and (first not in bases or second not in bases):
                result.add((first, second))
    return tuple(sorted(result))


def items_xml(source: bytes, pairs: tuple[tuple[int, int], ...]) -> bytes:
    if not pairs:
        return source
    root = ET.fromstring(source)
    nodes = {int(n.get('id')): n for n in root}
    recipes = combo_recipes()
    effects = tuple(map(int, policy()['extra']['effects']))
    width = len(effects)+1
    indices = {template: index for base in policy()['combo']['families']
               for index, template in enumerate((base, *(variant(base, e) for e in effects)))}
    for node in root.iter():
        if len(node) and node.text and not node.text.strip():
            node.text = None
        if node.tail and not node.tail.strip():
            node.tail = None
    aliases = {}
    for first, second in pairs:
        ordered = sorted((first, second), key=family)
        parents = tuple(family(t) for t in ordered)
        result = recipes[parents]
        identity = (policy()['combo']['alias_start']
                    + (result-policy()['combo']['template_start'])*width*width
                    + indices[ordered[0]]*width+indices[ordered[1]])
        if identity in nodes:
            raise ValueError('Recipe alias collision')
        node = deepcopy(nodes[result])
        node.set('id', str(identity))
        parent_ids = node.find("value[@key='parentIds']")
        parent_ids.set('val', ','.join(map(str, ordered)))
        node.remove(parent_ids)
        node.insert(0, parent_ids)
        aliases[identity] = node
    # Adjacent aliases share the same preview fields within the DEFLATE window.
    root.extend(aliases[identity] for identity in sorted(aliases))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True).replace(b' />', b'/>')
