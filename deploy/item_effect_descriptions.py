"""Client presentation derived from the existing authoritative effect policy."""
import json
from pathlib import Path
from typing import Any

Descriptions = dict[int, tuple[str, ...]]


def effect_lines(effect: dict[str, Any], language: str) -> tuple[str, ...]:
    if language not in ('ru', 'en'):
        raise ValueError('Unsupported description language')
    russian = language == 'ru'
    kind = effect['kind']
    if kind == 'booster':
        value, family = effect['value'], effect['family']
        hours, remainder = divmod(effect['seconds'], 3600)
        if remainder or not 1 <= hours <= 24:
            raise ValueError('Expected whole-hour booster duration')
        labels = {
            'trainer': f'Получаемый опыт: +{value}%' if russian else f'Experience gained: +{value}%',
            'advisor': f'Получаемые очки звания: +{value}' if russian else f'Rank points earned: +{value}',
            'block_xp': 'Блокирует получение опыта' if russian else 'Blocks experience gain',
        }
        duration = ('Время действия: 1 час.' if hours == 1 else f'Время действия: {hours} ч.') if russian else f'Duration: {hours} h'
        return labels[family], duration
    if kind == 'night_vision':
        bonus, ap = effect['sight_bonus'], effect['ap']
        armor = effect['armor']
        return ((f'Броня: {armor}; обзор в темноте: +{bonus} клетки',
                 f'Расход при включении: {ap} AP за ход') if russian else
                (f'Armor: {armor}; sight in darkness: +{bonus} cells',
                 f'While active: {ap} AP per turn'))
    if kind == 'vision':
        bonus = effect['sight_bonus']
        title = f'Дальность обзора: +{bonus} клетка' if russian else f'Sight range: +{bonus} cell'
    elif kind == 'health_capacity':
        title = f"Максимальное здоровье: +{effect['bonus_percent']}%" if russian else f"Maximum health: +{effect['bonus_percent']}%"
    else:
        raise ValueError('Unsupported effect description')
    return ((title, f"Цена применения: {effect['ap']} AP", f"Действует {effect['turns']} ходов",
             f"Восстанавливается {effect['cooldown']} ходов") if russian else
            (title, f"Use cost: {effect['ap']} AP", f"Duration: {effect['turns']} turns",
             f"Cooldown: {effect['cooldown']} turns"))


def load_descriptions(root: Path) -> dict[str, Descriptions]:
    effects = json.loads((root/'config/battle_item_effects.json').read_text(encoding='utf-8'))['items']
    selected = {int(identity): effect for identity, effect in effects.items()
                if effect['kind'] in ('booster', 'vision', 'night_vision')}
    health = json.loads((root/'config/combat_completion.json').read_text(encoding='utf-8'))['health']
    selected[health['template']] = dict(health, kind='health_capacity')
    if set(selected) != {35, *range(5002, 5013)}:
        raise ValueError('Effect description scope changed; review native routing')
    return {language: {identity: effect_lines(effect, language)
                       for identity, effect in sorted(selected.items())}
            for language in ('ru', 'en')}


def language_key(identity: int, line: int) -> str:
    return f'tio_item_effect_{identity}_{line}'


def extend_language(raw: bytes, language: str, descriptions: Descriptions) -> bytes:
    if language not in ('ru', 'en'):
        raise ValueError('Unsupported description language')
    text = raw.decode('cp1251')
    sections = {line.strip().lower() for line in text.splitlines() if line.startswith('[')}
    if sections != {'[language]'}:
        raise ValueError('Unexpected language resource structure')
    existing = {}
    for line in text.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in existing:
                raise ValueError('Duplicate localization key')
            existing[key] = value
    additions = []
    for identity, lines in sorted(descriptions.items()):
        if not 1 <= len(lines) <= 4:
            raise ValueError('Unbounded tooltip description')
        for index, value in enumerate(lines):
            key = language_key(identity, index)
            if any(c in value for c in '\r\n\0') or len(value) > 100:
                raise ValueError('Unbounded localization line')
            if key in existing:
                if existing[key] != value:
                    raise ValueError('Conflicting effect localization')
            else:
                additions.append(key+'='+value)
    if not additions:
        return raw
    separator = b'' if raw.endswith((b'\n', b'\r')) else b'\r\n'
    return raw+separator+('\r\n'.join(additions)+'\r\n').encode('cp1251')
