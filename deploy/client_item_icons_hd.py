"""Pure item-catalogue presentation transformation for the HD icon release.

Only image values change. Item IDs, rules and every other value remain owned
by the published catalogue. File I/O and publication belong to release tools.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from xml.etree import ElementTree as ET


def replace_item_images(source: bytes, images: Mapping[int, str]) -> bytes:
    """Replace explicitly selected images, rejecting ambiguous catalogue data."""
    root = ET.fromstring(source)
    if root.tag != 'items':
        raise ValueError('Expected an item catalogue')
    nodes: dict[int, ET.Element] = {}
    for node in root:
        identity = int(node.attrib['id'])
        if identity in nodes:
            raise ValueError(f'Duplicate item ID: {identity}')
        nodes[identity] = node
    for identity, name in images.items():
        if (type(identity) is not int or identity not in nodes
                or not isinstance(name, str) or len(name) >= 32
                or re.fullmatch(r'tio_ii_[1-9][0-9]*\.png', name) is None
                or name != f'tio_ii_{identity}.png'):
            raise ValueError(f'Invalid image mapping for item {identity}')
    changed = False
    for identity, name in images.items():
        node = nodes[identity]
        values = node.findall("value[@key='image']")
        if len(values) > 1:
            raise ValueError(f'Ambiguous image for item {identity}')
        value = values[0] if values else ET.SubElement(node, 'value', key='image')
        if value.get('val') != name:
            value.set('val', name)
            changed = True
    if not changed:
        return source
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def copy_stack_flags(source: bytes, authoritative: bytes,
                     identities: tuple[int, ...]) -> bytes:
    """Copy only selected native stacking flags from the deployed catalogue."""
    root = ET.fromstring(source)
    authority = ET.fromstring(authoritative)
    if root.tag != 'items' or authority.tag != 'items':
        raise ValueError('Expected item catalogues')
    changed = False
    for identity in identities:
        if type(identity) is not int:
            raise ValueError('Expected item IDs')
        path = f"item[@id='{identity}']"
        targets, owners = root.findall(path), authority.findall(path)
        if len(targets) != 1 or len(owners) != 1:
            raise ValueError('Missing or duplicate item')
        flags = owners[0].findall("value[@key='stackable']")
        if len(flags) != 1 or flags[0].get('val') not in ('0', '1'):
            raise ValueError('Missing or ambiguous authoritative stack flag')
        values = targets[0].findall("value[@key='stackable']")
        if len(values) > 1:
            raise ValueError('Ambiguous client stack flag')
        value = values[0] if values else ET.SubElement(targets[0], 'value', key='stackable')
        if value.get('val') != flags[0].get('val'):
            value.set('val', flags[0].get('val'))
            changed = True
    if not changed:
        return source
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)
