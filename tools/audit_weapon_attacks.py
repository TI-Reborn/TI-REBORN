"""Attack once with every catalog weapon on the real Combat engine.

Each weapon gets its own temporary field: attacker at (1,1), one enemy at the
nearest legal distance, matching ammunition. Weapons with a dedicated path
(mines, the suicide jacket, the Groza subgrenade) are expected to refuse the
ordinary attack. No database, network or hosted state is touched.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT)]

from tio.battle_hazards import rules as hazard_rules
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.protocol.battle_attack import AttackRequest, decode_attack_result
from tio.protocol.item_list import encode_item_list
from tio.weapons import WeaponCatalog
from test_combat import FixedRandom, item

DEDICATED_PATH = {321: 'mine deploy', 325: 'mine deploy', 334: 'item use', 340: 'Groza ability 27'}
STACKED = (317, 319, 321, 325)
NATURAL = (333, 65489)


def attack(catalog, weapon_id):
    w, source = catalog.weapons[weapon_id], catalog.sources[weapon_id]
    distance = max(w.min_range, 1)
    if source.get('weaponAttack') in ('Grenade', 'Rocket', 'Subgrenade'):
        distance = max(distance, 4)
    target = (1+distance, 1)
    field = BattleField(30, 30, [BattleActor(1, 7, 1, 1, 60, 100, 100),
                                 BattleActor(2, 8, *target, 40, 500, 500)], step_cost=1)
    combat = Combat(field, WeaponCatalog(), rng=FixedRandom()); field.combat = combat
    items = [item(100, weapon_id, equipped=True, count=5 if weapon_id in STACKED else 1)]
    ammo = hazard_rules()['grenade_launcher_ammo'] if weapon_id == 323 else w.ammo_id
    if ammo:
        items.append(item(101, ammo, 100))
    combat.register(1, encode_item_list(1, items), human=weapon_id not in NATURAL)
    try:
        result = decode_attack_result(combat.attack(7, AttackRequest(1, *target))[0])
    except ValueError as error:
        return distance, False, str(error)
    return distance, True, ','.join(f'{h.actor_id}:{h.damage}' for h in result.hits)


def main():
    catalog = WeaponCatalog(); broken = []
    for weapon_id in sorted(catalog.weapons):
        distance, ok, detail = attack(catalog, weapon_id)
        expected = weapon_id in DEDICATED_PATH
        status = 'OK' if ok else 'DEDICATED' if expected else 'BROKEN'
        if status == 'BROKEN' or (ok and expected):
            broken.append(weapon_id)
        note = DEDICATED_PATH.get(weapon_id, '')
        print(f'{weapon_id:>5} {catalog.weapons[weapon_id].name[:20]:20} d={distance:<2} {status:9} {detail} {note}')
    print(f'{len(catalog.weapons)} weapons; unexpected results: {broken or "none"}')
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())
