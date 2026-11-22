"""Item catalogue sent to a session, by the interface its launcher chose.

The interfaces differ only in presentation `image` values. Items and rules
come from one catalogue (evidence/items_diagnostic.xml), which the client
replaces at every login, so the server, not a local file, selects the art.
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from .clans import REPAIR_TEMPLATE

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'evidence/items_diagnostic.xml'
ORIGINAL_IMAGES = ROOT / 'config/original_item_images.json'
NEW = 'new'
ORIGINAL = 'original'
# The native image loader keeps names in a 32-character buffer.
_NAME = re.compile(r'[A-Za-z0-9_.-]{1,31}')


def validate(interface: str) -> str:
    if interface not in (NEW, ORIGINAL):
        raise ValueError(f'Unsupported interface: {interface!r}')
    return interface


def apply_item_images(source: bytes, images: Mapping[int, str | None]) -> bytes:
    """Set each selected item's image; None removes an image it never had."""
    root = ET.fromstring(source)
    if root.tag != 'items':
        raise ValueError('Expected an item catalogue')
    changed = False
    for identity, name in images.items():
        if name is not None and _NAME.fullmatch(name) is None:
            raise ValueError(f'Invalid image name for item {identity}')
        nodes = root.findall(f"item[@id='{identity}']")
        if type(identity) is not int or len(nodes) != 1:
            raise ValueError(f'Missing or duplicate item: {identity}')
        values = nodes[0].findall("value[@key='image']")
        if len(values) > 1:
            raise ValueError(f'Ambiguous image for item {identity}')
        if name is None:
            if values:
                nodes[0].remove(values[0])
                changed = True
            continue
        value = values[0] if values else ET.SubElement(nodes[0], 'value', key='image')
        if value.get('val') != name:
            value.set('val', name)
            changed = True
    if not changed:
        return source
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def original_images(path: Path = ORIGINAL_IMAGES) -> dict[int, str | None]:
    raw = json.loads(path.read_text(encoding='utf-8'))
    images = raw.get('images') if isinstance(raw, dict) else None
    if not isinstance(images, dict):
        raise ValueError('Expected an images object')
    result: dict[int, str | None] = {}
    for key, name in images.items():
        if not key.isdigit() or not (name is None or isinstance(name, str)):
            raise ValueError(f'Invalid original image entry: {key!r}')
        result[int(key)] = name
    return result


@lru_cache(maxsize=2)
def _original_catalogue(source: bytes, images: bytes) -> bytes:
    # Static for a server process, like the parsed catalogue in item_catalog.
    selected = {int(key): name for key, name in json.loads(images)['images'].items()}
    return apply_item_images(source, selected)


@lru_cache(maxsize=2)
def _with_repair_points(source: bytes, interface: str) -> bytes:
    root = ET.fromstring(source)
    points = ET.SubElement(root, 'item', id=str(REPAIR_TEMPLATE), name='Repair Points')
    image = 'itm_repairkit.png' if interface == ORIGINAL else 'tio_ii_17.png'
    # Native HideRepairPoints filters this type from backpacks and item lists.
    for key, value in (('image', image), ('itype', 'repairpoints'), ('durability', '1'), ('stackable', '1')):
        ET.SubElement(points, 'value', key=key, val=value)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def items_xml(interface: str) -> bytes:
    """Return the client item catalogue for one session's interface."""
    validate(interface)
    source = CATALOGUE.read_bytes()
    if interface == ORIGINAL:
        original_images()  # validate the data before caching its transformation
        source = _original_catalogue(source, ORIGINAL_IMAGES.read_bytes())
    return _with_repair_points(source, interface)
