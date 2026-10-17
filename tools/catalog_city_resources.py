"""Inventory resource families; deliberately do not infer city ownership from paths."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(r'C:\Program Files (x86)\TIOnline\base')


def main():
    families = {}
    for path in sorted((BASE / 'setting').rglob('*')):
        if path.is_file():
            relative = path.relative_to(BASE / 'setting')
            family_name = relative.parts[0] if len(relative.parts) > 1 else '_root'
            family = families.setdefault(family_name, {'models': [], 'textures': []})
            key = 'models' if path.suffix.lower() == '.t' else 'textures' if path.suffix.lower() in ('.png', '.tga', '.jpg', '.dds', '.bmp') else None
            if key:
                family[key].append(path.relative_to(BASE).as_posix())
    grounds = []
    for ground in ET.parse(BASE / 'ground.xml').getroot():
        brushes = [dict(item.attrib) for item in ground]
        grounds.append(dict(ground.attrib, brushes=brushes,
                            families=sorted({b['filename'].strip('\\').split('\\')[0] for b in brushes})))
    towns = []
    for body in re.findall(r'\{([^}]+)\}', (BASE / 'towns.cfg').read_text()):
        towns.append(dict(line.strip().split('=', 1) for line in body.splitlines() if '=' in line))
    result = dict(note='Resource families and explicit configuration references, not exclusive city ownership.',
                  sources={name: hashlib.sha256((BASE / name).read_bytes()).hexdigest()
                           for name in ('towns.cfg', 'ground.xml')}, towns=towns, grounds=grounds, families=families)
    out = ROOT / 'evidence/city-resource-catalog.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(towns)} town records; {len(grounds)} grounds; {len(families)} resource families')
    for name, family in families.items():
        print(name, len(family['models']), 'models;', len(family['textures']), 'texture files')


if __name__ == '__main__':
    main()
