"""Authoritative medical-item data shared by combat and client export."""
from functools import lru_cache
import json
from pathlib import Path
from types import MappingProxyType
from collections.abc import Mapping


@lru_cache(maxsize=1)
def medical_items() -> Mapping[int, tuple[int, int]]:
    path = Path(__file__).resolve().parents[1]/'config/medical_items.json'
    policy = json.loads(path.read_text(encoding='utf-8'))
    if policy['version'] != 1:
        raise ValueError('Unsupported medical-item policy')
    result = {}
    for key, row in policy['items'].items():
        if not key.isdecimal() or not 1 <= int(key) < 65500:
            raise ValueError('Invalid medical-item template')
        values = row['heal'], row['ap']
        if any(type(value) is not int or not 1 <= value <= 255 for value in values):
            raise ValueError('Invalid medical-item effect')
        result[int(key)] = values
    if not result:
        raise ValueError('Empty medical-item policy')
    return MappingProxyType(result)
