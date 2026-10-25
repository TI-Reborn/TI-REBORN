"""Write assets/item-icons-hd-v1/manifest.json from the delivered catalogue.

    python -m tools.item_icons_hd.build_manifest [--client "C:/Program Files (x86)/TIOnline"]

With --client every referenced model and texture is checked to exist.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import ROOT, load, manifest

OUT = ROOT / 'assets/item-icons-hd-v1/manifest.json'


def missing_files(items, client: Path) -> list[str]:
    models = client / 'base/models'
    problems = []
    for item in items:
        for name in item.models:
            if not (models / f'{name}.mdjx').is_file():
                problems.append(f'{item.item_id}: model {name}.mdjx')
        for name in item.textures:
            if name and not (models / name).is_file():
                problems.append(f'{item.item_id}: texture {name}')
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', type=Path)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    items = load()
    if args.client:
        problems = missing_files(items, args.client)
        if problems:
            raise SystemExit('Missing client files:\n' + '\n'.join(problems))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest(items), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(args.out, len(items), 'items')


if __name__ == '__main__':
    main()
