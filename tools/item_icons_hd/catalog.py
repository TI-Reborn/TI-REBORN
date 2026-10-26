"""Decide how each inventory item gets a high-resolution icon.

Pure data: reads the catalogue the server sends to clients and classifies
each item into one pipeline. No client files, network or Blender are needed.

* ``existing`` - weapon icons already drawn in high resolution
  (assets/weapon-icons-v1 on the owner's machine, release 2026.10.20.5).
* ``render`` - a native 3D model exists: Blender renders a reference, which
  is then painted over in the shared illustration style.
* ``redraw`` - no model: drawn from scratch in the same style.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

from tio.item_presentation import ORIGINAL, items_xml

ROOT = Path(__file__).resolve().parents[2]

# Weapon catalogue entries released with high-resolution sources on 2026-10-20.
EXISTING_WEAPON_ICONS = frozenset((*range(300, 342), 5001, 5013, 65489))

# Engine records for fighter/dog/mob bodies, never inventory items.
BODY_PARTS = frozenset((*range(65490, 65500), *range(65500, 65514)))
MOB_ATTACKS = frozenset((353,))  # Sick Miner Attack: a monster template
NOT_ITEMS = frozenset((0, 1, 2)) | BODY_PARTS | MOB_ATTACKS  # null record, Credits, Gold

# Native models present in the client but not named by the catalogue entry.
MODEL_OVERRIDES = {
    5002: ('man_item_nightvision',),  # Night Vision Goggles
    52: ('item_gasdrill',),  # Mining Drill
}

# The second model of a human armour piece is the bare hand mesh.
SKIN_MODELS = frozenset(('chr_man_hands', 'chr_woman_hands', 'tio_vet_hands', 'tio_vet_legs'))

STYLE = ('Объёмная рисованная предметная иллюстрация в стиле набора weapon-icons-v1: '
         'потёртый металл, ткань и кожа, сдержанные тёплые блики, мягкая тень снизу, '
         'прозрачный фон, без подписей, рамок и галочек, предмет целиком в кадре.')


@dataclass(frozen=True)
class ItemIcon:
    item_id: int
    name: str
    kind: str
    slot: str
    pipeline: str
    models: tuple[str, ...] = ()
    textures: tuple[str, ...] = ()
    masks: tuple[str, ...] = ()
    current_image: str = ''
    canvas: tuple[int, int] = (1024, 1024)
    notes: tuple[str, ...] = field(default=())

    def to_json(self) -> dict:
        data = asdict(self)
        for key in ('models', 'textures', 'masks', 'canvas', 'notes'):
            data[key] = list(data[key])
        return data


def slot_of(model: str, kind: str) -> str:
    name = model.lower()
    if kind == 'weapon':
        return 'weapon'
    if name.endswith(('_head', '_helmet')) or 'santahat' in name or name.endswith('_helm'):
        return 'head'
    if name.endswith(('_legs', '_longies')):
        return 'legs'
    if name.startswith('dog_'):
        return 'dog'
    if kind == 'armor':
        return 'body'
    return 'device'


def kind_of(values: dict[str, str]) -> str:
    if 'weaponType' in values:
        return 'weapon'
    return values.get('itype') or values.get('type') or 'other'


def classify(item_id: int, name: str, values: dict[str, str]) -> ItemIcon | None:
    if item_id in NOT_ITEMS:
        return None
    kind = kind_of(values)
    numbered = sorted((k for k in values if k.startswith('model_')), key=lambda k: int(k.split('_')[1]))
    models = tuple(values[k] for k in numbered if values[k] not in SKIN_MODELS)
    textures = tuple(values.get('texture_' + k.split('_')[1], '') for k in numbered if values[k] not in SKIN_MODELS)
    masks = tuple(values.get(k.replace('model_', 'mask_')) or values.get(k.replace('model_', 'w_mask_')) or ''
                  for k in numbered if values[k] not in SKIN_MODELS)
    notes: list[str] = []
    if not models and item_id in MODEL_OVERRIDES:
        models = MODEL_OVERRIDES[item_id]
        textures = ('',) * len(models)
        masks = ('',) * len(models)
        notes.append('Модель найдена в base/models вручную; текстуру подобрать по имени модели.')
    if kind == 'weapon' and item_id in EXISTING_WEAPON_ICONS:
        pipeline = 'existing'
    elif models:
        pipeline = 'render'
    else:
        pipeline = 'redraw'
    slot = slot_of(models[0], kind) if models else ('weapon' if kind == 'weapon' else 'device')
    canvas = (2048, 1024) if slot == 'weapon' else (1024, 1024)
    return ItemIcon(item_id, name, kind, slot, pipeline, models, textures, masks,
                    values.get('image', ''), canvas, tuple(notes))


def load(path: Path | None = None) -> tuple[ItemIcon, ...]:
    """Classify a catalogue; by default the original-interface art it replaces."""
    root = ET.parse(path).getroot() if path is not None else ET.fromstring(items_xml(ORIGINAL))
    result = []
    seen: set[int] = set()
    for node in root:
        item_id = int(node.get('id'))
        if item_id in seen:
            raise ValueError(f'Duplicate catalogue item {item_id}')
        seen.add(item_id)
        values = {v.get('key'): v.get('val') for v in node.findall('value')}
        icon = classify(item_id, node.get('name', ''), values)
        if icon is not None:
            result.append(icon)
    return tuple(sorted(result, key=lambda i: i.item_id))


def manifest(items: tuple[ItemIcon, ...]) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.pipeline] = counts.get(item.pipeline, 0) + 1
    return {'version': 1, 'source': 'evidence/items_diagnostic.xml', 'style': STYLE,
            'counts': dict(sorted(counts.items())), 'items': [i.to_json() for i in items]}
