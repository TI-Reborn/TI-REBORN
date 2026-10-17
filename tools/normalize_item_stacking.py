"""Publish the user's stacking policy through native item metadata."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tio.item_stacking import STACKABLE


def normalize(fields):
    identity = int(fields['item_id'])
    if identity in STACKABLE:
        fields['stackable'] = '1'
    elif identity == 8:  # RPG Missile: explicitly keep individual rockets.
        fields['stackable'] = '0'


def main():
    path = ROOT / 'evidence/items_diagnostic.xml'
    tree = ET.parse(path)
    changed = []
    for item in tree.getroot():
        values = {v.get('key'): v.get('val') for v in item.findall('value')}
        fields = dict(values, item_id=item.get('id'))
        normalize(fields)
        if fields.get('stackable') == values.get('stackable'):
            continue
        node = next((v for v in item.findall('value') if v.get('key') == 'stackable'), None)
        if node is None:
            node = ET.SubElement(item, 'value', key='stackable')
        node.set('val', fields['stackable'])
        changed.append(int(item.get('id')))
    if changed:
        ET.indent(tree)
        tree.write(path, encoding='utf-8', xml_declaration=True)
    print('Stack metadata updated:', changed)


if __name__ == '__main__':
    main()
