"""Put the drifted HD equipment atlases back on their meshes' UV layout.

A survey (in-place vs best island correlation, tools/atlas_registration.py)
found these HD atlases shrunk or shifted by the image generator, so their
meshes sampled the wrong pieces and no longer matched the item icons, which
are rendered from the original atlases. armor_battle, armor_military,
armor_tank, armor_fea and the dog atlases are in place and are not touched.

Each output keeps the original's layout and colours (as on the icons) and
takes surface detail from the HD island found for it. armor_combatse is then
rebuilt from the restored armor_combat (tools/build_combat_se_atlas.py).

Usage: python tools/build_registered_atlases.py MODELS_DIR ORIGINALS_DIR OUT_DIR
  MODELS_DIR     installed client base/models (HD atlases and meshes)
  ORIGINALS_DIR  original atlases as atlas-<name>.png (assets/equipment-textures-v1/inputs)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_combat_se_atlas  # noqa: E402
from tools.atlas_registration import restore  # noqa: E402

PARTS = ('head', 'chest', 'legs')
DRIFTED = {
    'armor_battlese': [f'{sex}_armor_battlese_{part}' for sex in ('man', 'woman') for part in PARTS],
    'armor_combat': [f'{sex}_armor_combat_{weight}_{part}' for sex in ('man', 'woman')
                     for weight in ('light', 'medium', 'heavy') for part in PARTS],
    'armor_tankse': ['man_armor_tankse', 'woman_armor_tankse'],
    'armor_suicidjack': ['man_armor_suicidjack', 'woman_armor_suicidjack'],
    'armor_fease': ['woman_armor_fease'],
    'armor_santahat': ['man_armor_santahat', 'woman_armor_santahat'],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(models: Path, originals: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, meshes in DRIFTED.items():
        original = Image.open(originals / f'atlas-{name}.png').convert('RGB')
        hd = Image.open(models / f'{name}.jpg')
        image, islands = restore(original, hd, [models / f'{mesh}.mdjx' for mesh in meshes])
        target = out / f'{name}.jpg'
        image.save(target, format='JPEG', quality=95, subsampling=0)
        report[name] = dict(hd_sha256=digest(models / f'{name}.jpg'), original_sha256=digest(originals / f'atlas-{name}.png'),
                            output_sha256=digest(target), meshes=meshes, islands=islands)
    # armor_combatse has no meshes of its own; it follows the restored combat layout.
    source = out / 'combat-source'
    source.mkdir(exist_ok=True)
    shutil.copyfile(out / build_combat_se_atlas.ATLAS, source / build_combat_se_atlas.ATLAS)
    shutil.copyfile(models / build_combat_se_atlas.MASK, source / build_combat_se_atlas.MASK)
    report['armor_combatse'] = build_combat_se_atlas.build(source, out)
    (out / 'registered-atlases.json').write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models', type=Path)
    parser.add_argument('originals', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    report = build(args.models, args.originals, args.out)
    for name, row in report.items():
        if 'islands' in row:
            kept = sum(i['hd_detail'] for i in row['islands'])
            print(f"{name}: {kept}/{len(row['islands'])} islands with HD detail")


if __name__ == '__main__':
    main()
