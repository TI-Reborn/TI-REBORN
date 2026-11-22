"""Rebuild armor_combatse.jpg on the Heavy Combat mesh UV layout.

Heavy Combat SE (items 248/249/250) has no meshes of its own in the client:
the catalog binds the ordinary man/woman_armor_combat_heavy_* meshes. Those
meshes are unwrapped for armor_combat.jpg, while the shipped SE atlas belongs
to the absent SE meshes, so every SE piece rendered fragments of other parts
(the helmet showed chest plates). The SE atlas is therefore derived from the
matching armor_combat.jpg: same islands, SE palette (weathered silver steel
plates over dark cloth). The camo/metal mask follows the same layout.

Usage: python tools/build_combat_se_atlas.py MODELS_DIR OUT_DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ATLAS = 'armor_combat.jpg'
MASK = 'armor_combat_mask.png'
SE_ATLAS = 'armor_combatse.jpg'
SE_MASK = 'armor_combatse_mask.png'

_D65 = np.array([0.95047, 1.0, 1.08883])
_RGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                        [0.2126729, 0.7151522, 0.0721750],
                        [0.0193339, 0.1191920, 0.9503041]])


def _to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = _to_linear(rgb / 255.0) @ _RGB_TO_XYZ.T / _D65
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack((116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])), -1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    f = np.stack((fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200), -1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * _D65
    return np.round(_to_srgb(xyz @ np.linalg.inv(_RGB_TO_XYZ).T) * 255).astype(np.uint8)


def se_palette(rgb: np.ndarray) -> np.ndarray:
    """Turn the brown-leather Heavy Combat finish into SE weathered steel.

    Mid and light tones (leather plates, straps, steel) become cool silver;
    the darkest tones (cloth between plates) keep a little brown, as in the
    SE set. Saturated red/cyan details (visor, status lights) are kept.
    """
    lab = rgb_to_lab(rgb.astype(np.float64))
    light, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(a, b)
    # Red visor and cyan lights; warm skin/leather (b close to a) is not an accent.
    accent = (chroma > 38) & (((a > 30) & (a > 1.3 * b)) | (b < -15))
    darkness = np.clip((38 - light) / 22, 0, 1)  # 1 for cloth shadows, 0 for plates
    keep = 0.12 + 0.43 * darkness  # fraction of original colourfulness
    lifted = 100 * (light / 100) ** 0.82  # brighter, steel-like plates
    new_light = np.where(darkness >= 1, light, lifted * (1 - darkness) + light * darkness)
    out = np.stack((new_light, a * keep - 0.6, b * keep - 2.5 * (1 - darkness)), -1)
    out[accent] = lab[accent]
    return lab_to_rgb(out)


def build(models: Path, out: Path) -> dict:
    atlas = Image.open(models / ATLAS).convert('RGB')
    result = Image.fromarray(se_palette(np.asarray(atlas)), 'RGB')
    out.mkdir(parents=True, exist_ok=True)
    result.save(out / SE_ATLAS, format='JPEG', quality=95, subsampling=0)
    mask = (models / MASK).read_bytes()
    (out / SE_MASK).write_bytes(mask)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(source_atlas=ATLAS, source_atlas_sha256=digest(models / ATLAS),
                  source_mask=MASK, source_mask_sha256=digest(models / MASK),
                  outputs={n: digest(out / n) for n in (SE_ATLAS, SE_MASK)}, size=list(result.size))
    (out / 'combat-se-atlas.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.models, args.out)))


if __name__ == '__main__':
    main()
