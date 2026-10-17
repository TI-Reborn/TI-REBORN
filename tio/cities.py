"""City rules from manual pp11–16; map composition remains emulator policy."""
from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    name: str
    bounds: tuple
    levels: tuple
    profile: str
    pool: str
    profit: int
    influence: int
    kill_bonus: int


CITIES = {
    3: City('Reservation', (-171,-335,-136,-300), (1,3), 'reservation', 'starter', 1,0,0),
    2: City('Denver', (-390,-447,-345,-402), (4,20), 'denver', 'equipped', 4,1,10),
    5: City('New York', (140,-70,240,30), (4,20), 'new_york', 'equipped', 4,1,10),
    8: City('Military Zone', (286,-265,366,-185), (4,20), 'military_zone', 'equipped', 4,1,10),
}
from .world_completion import extra_cities
CITIES.update(extra_cities())


def require_arena(town, levels):
    city = CITIES.get(town)
    if city is None:
        raise ValueError('В этой локации обычные бои не проводятся')
    levels=tuple(levels)
    if town in (4,18):
        from .world_completion import require_location
        require_location(town,levels)
    low, high = city.levels
    if any(type(level) is not int or not low <= level <= high for level in levels):
        raise ValueError(f'{city.name}: нужны бойцы уровней {low}–{high}')
    return city


def town_in(db, account):
    row = db.execute('SELECT town_id FROM character_locations WHERE account=?', (account,)).fetchone()
    return row[0] if row else 3
