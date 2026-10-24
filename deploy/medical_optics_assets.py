"""Bounded metadata/text projection; preserve all unrelated client bytes."""
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from tio.medical_items import medical_items
from .item_effect_descriptions import language_key, load_descriptions


def patch_health_metadata(raw: bytes) -> bytes:
    heal, points = medical_items()[20]
    nodes = [node for node in ET.fromstring(raw).iter('item')
             if node.get('id') == '20']
    if len(nodes) != 1:
        raise ValueError('Expected one Health Injection template')
    values = {node.get('key'): node.get('val') for node in nodes[0].findall('value')}
    if values.get('power') != str(heal) or values.get('weight') != '100':
        raise ValueError('Health Injection metadata differs from the reviewed source')
    if values.get('actionPoints') == str(points):
        return raw
    if values.get('actionPoints') != '10':
        raise ValueError('Unexpected previous Health Injection AP cost')
    matches = list(re.finditer(br'<item\b[^>]*\bid="20"[^>]*>.*?</item>', raw, re.S))
    if len(matches) != 1:
        raise ValueError('Ambiguous Health Injection XML representation')
    match = matches[0]
    block = match.group()
    before = b'<value key="actionPoints" val="10" />'
    after = f'<value key="actionPoints" val="{points}" />'.encode('ascii')
    if block.count(before) != 1:
        raise ValueError('Unexpected Health Injection AP representation')
    return raw[:match.start()]+block.replace(before, after, 1)+raw[match.end():]


def patch_night_vision_language(raw: bytes, language: str, root: Path) -> bytes:
    descriptions = load_descriptions(root)[language][5002]
    if len(descriptions) != 2:
        raise ValueError('Published native NVG adapter has exactly two rows')
    changes = {language_key(5002, index).encode('ascii'): text.encode('cp1251')
               for index, text in enumerate(descriptions)}
    lines = raw.splitlines(keepends=True)
    found = set()
    for index, line in enumerate(lines):
        key, separator, value = line.partition(b'=')
        if not separator or key not in changes:
            continue
        if key in found:
            raise ValueError('Duplicate NVG localization key')
        found.add(key)
        ending = value[len(value.rstrip(b'\r\n')):]
        lines[index] = key+b'='+changes[key]+ending
    if found != set(changes):
        raise ValueError('Published NVG localization keys are missing')
    return b''.join(lines)


def replacements(before: bytes, after: bytes, *, xml: bool) -> list[dict[str, str]]:
    """Return explicit reviewable old/new blocks for remote reconstruction."""
    if xml:
        pattern = br'<item\b[^>]*\bid="20"[^>]*>.*?</item>'
        old = re.findall(pattern, before, re.S)
        new = re.findall(pattern, after, re.S)
    else:
        prefix = b'tio_item_effect_5002_'
        old = [line for line in before.splitlines() if line.startswith(prefix)]
        new = [line for line in after.splitlines() if line.startswith(prefix)]
    if len(old) != (1 if xml else 2) or len(old) != len(new):
        raise ValueError('Unexpected client patch scope')
    restored = before
    result = []
    for original, updated in zip(old, new):
        if restored.count(original) != 1:
            raise ValueError('Client replacement block is not unique')
        restored = restored.replace(original, updated, 1)
        result.append(dict(before=original.hex(), after=updated.hex()))
    if restored != after:
        raise ValueError('Unrelated client resource bytes changed')
    return result
