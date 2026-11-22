"""Read-only balance model: exact damage rolls and expected attacks per kill."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tio.armor import mitigate
from tio.enhancement import EnhancementRules
from tio.enhancement_limits import enhancement_cap
from tio.weapon_proficiency import ProficiencyRules, damage_endpoint
from tio.weapons import WeaponCatalog


def expected_attacks(hp: int, outcomes: dict[int, float]) -> float:
    """Exact recurrence, including misses; each attack is independent."""
    if abs(sum(outcomes.values()) - 1) > 1e-9:
        raise ValueError('Outcome probabilities must sum to one')
    positive = [(damage, p) for damage, p in outcomes.items() if damage > 0]
    hit_probability = sum(p for _, p in positive)
    if not hit_probability:
        raise ValueError('An attack must be able to cause damage')
    expected = [0.0] * (hp + 1)
    for health in range(1, hp + 1):
        expected[health] = (1 + sum(
            p * expected[max(0, health - damage)] for damage, p in positive
        )) / hit_probability
    return expected[hp]


def measure(catalog: WeaponCatalog, rules: EnhancementRules, weapon_id: int,
            skill: int, upgrade: int, armor: int, hp: int, distance: int) -> dict:
    weapon = catalog.weapons[weapon_id]
    low, high = catalog.distance_damage(
        weapon_id, distance, rules.bonus(upgrade))
    low, high = damage_endpoint(low, skill), damage_endpoint(high, skill)
    rolls = range(low, high + 1)
    hits = Counter(mitigate(raw, armor)[0] for raw in rolls)
    normal = {damage: count / len(rolls) for damage, count in hits.items()}
    accuracy = catalog.accuracy(weapon_id, distance) / 100
    critical = int(catalog.sources[weapon_id].get('critical', 0)) / 100
    outcomes = Counter({0: 1 - accuracy})
    for raw in rolls:
        outcomes[mitigate(raw, armor)[0]] += accuracy * (1 - critical) / len(rolls)
        outcomes[mitigate(2 * raw, armor)[0]] += accuracy * critical / len(rolls)
    attacks = expected_attacks(hp, dict(outcomes))
    return dict(
        weapon_id=weapon_id, weapon=weapon.name, skill=skill, upgrade=upgrade,
        armor=armor, hp=hp, distance=distance, raw_min=low, raw_max=high,
        damage_min=min(hits), damage_max=max(hits),
        damage_mean=sum(damage * p for damage, p in normal.items()),
        successful_noncritical_hits=expected_attacks(hp, normal),
        baseline_accuracy=accuracy, baseline_critical=critical,
        expected_clicks=attacks, attack_ap=weapon.attack_ap,
        expected_attack_ap=attacks * weapon.attack_ap,
        expected_ammunition=attacks * weapon.bullets_count,
    )


def main() -> None:
    assert expected_attacks(100, {25: 1.0}) == 4
    assert expected_attacks(100, {0: 0.5, 25: 0.5}) == 8
    assert abs(expected_attacks(2, {1: 0.5, 2: 0.5}) - 1.5) < 1e-12
    catalog, proficiency = WeaponCatalog(), ProficiencyRules()
    rules = EnhancementRules()
    policy = json.loads((ROOT / 'config/mining.json').read_text(encoding='utf-8'))
    rows = []
    for minimum, maximum, _, hp, armor, *_ in policy['bands']:
        for level in (minimum, maximum):
            for skill in (35, proficiency.caps(level, True)[0]):
                for upgrade in (0, enhancement_cap(level)):
                    for weapon in (301, 303, 304, 306, 311, 312, 330, 336, 338):
                        stats = catalog.weapons[weapon]
                        for distance in (stats.min_range, stats.max_range):
                            rows.append(dict(
                                mine=f'{minimum}-{maximum}', level=level,
                                **measure(catalog, rules, weapon, skill, upgrade,
                                          armor, hp, distance)))
    aug = measure(catalog, rules, 311, 140, 20, 270, 249, 4)
    assert (aug['damage_min'], aug['damage_max']) == (38, 47)
    zero = measure(catalog, rules, 311, 140, 0, 270, 249, 4)
    assert (zero['damage_min'], zero['damage_max']) == (20, 30)
    variants = [measure(catalog, rules, 311, 140, upgrade, armor, 249, 4)
                for armor in (270, 216, 200, 180, 160, 135, 0)
                for upgrade in (0, 20)]
    files = ('tio/combat.py', 'tio/combat_rolls.py', 'tio/armor.py',
             'tio/weapons.py', 'tio/weapon_proficiency.py', 'tio/enhancement.py',
             'tio/enhancement_limits.py', 'config/weapon_catalog.json',
             'config/mining.json', 'config/weapon_proficiency.json')
    report = dict(
        assumptions=[
            'One target, stationary attacks, full health at start.',
            'Baseline accuracy and critical chance only: no cover, buffs, implants or learned bonuses.',
            'No movement, healing, incoming damage, reload or equipment wear costs.',
            'Expected hits use the full roll distribution, not HP divided by average damage.',
            'Matrix compares the weapon-specific skill at 35 and the level cap.',
            'All calculations are isolated; no accounts, gameplay or configuration changed.',
        ],
        hashes={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files},
        bands=policy['bands'], scenarios=len(rows), armor_variants=variants,
        common_distance_comparison=[
            measure(catalog, rules, weapon, 140, 20, 270, 249, 4)
            for weapon in (304, 306, 311, 330)
        ],
        proposed_armor_trial=[dict(
            mine=f'{minimum}-{maximum}', level=level,
            **measure(catalog, rules, 311, proficiency.caps(level, True)[0],
                      enhancement_cap(level), armor, hp, 4))
            for minimum, maximum, hp, armor in (
                (4, 6, 150, 128), (7, 10, 249, 180),
                (11, 15, 249, 200), (16, 20, 300, 240))
            for level in (minimum, maximum)])
    output = ROOT / 'reports/mine-damage-balance-20261117'
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'matrix.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
