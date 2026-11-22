"""can_observe rejects before tracing rays, with unchanged results."""
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tio import battle_item_effects as effects
from tio.battle_item_effects import clear_item_sight, initialize, is_dark, normal_sight
from tio.visibility import field_sight


def reference(combat, observer, target, *, field=None):
    """Trace all rays before applying the current rounded tile distance."""
    if not observer.health: return False
    field = combat.field if field is None else field
    end = (target.x, target.y); start = (observer.x, observer.y)
    if not clear_item_sight(combat, start, end): return False
    state = initialize(combat); distance = (observer.x-target.x)**2 + (observer.y-target.y)**2
    ordinary = distance < (observer.sight_radius + .5)**2
    illuminated = (not ordinary and is_dark(combat)
        and distance < (normal_sight(combat, observer.actor_id) + .5)**2
        and any(a['kind'] == 'flare' and (target.x-a['center'][0])**2 + (target.y-a['center'][1])**2 <= a['radius']**2
                for a in state['areas'].values()))
    if (ordinary or illuminated) and field_sight(field, start, end): return True
    for recon in state['recon'].values():
        source = field._actors.get(recon['source'])
        if source is None or not source.health or not field.allied(source.owner_id, observer.owner_id): continue
        x, y = recon['center']
        from tio.recon_geometry import contains
        if (contains(recon, target.x, target.y)
            and clear_item_sight(combat, (x, y), end) and field_sight(field, (x, y), end)):
            return True
    return False


def scene(rng):
    width, height = rng.randint(8, 30), rng.randint(8, 30)
    blocked = frozenset((rng.randrange(width), rng.randrange(height)) for _ in range(rng.randint(0, width*height//4)))
    actors = {}
    for identity in range(1, rng.randint(2, 7)):
        actors[identity] = SimpleNamespace(actor_id=identity, owner_id=identity % 2, x=rng.randrange(width),
                                           y=rng.randrange(height), health=rng.choice((0, 50, 100)),
                                           sight_radius=rng.randint(0, 12))
    field = SimpleNamespace(width=width, height=height, blocked=blocked, _actors=actors,
                            item_darkness=rng.random() < .5, allied=lambda a, b: a == b)
    combat = SimpleNamespace(field=field)
    state = initialize(combat)
    for n in range(rng.randint(0, 4)):
        state['areas'][n] = dict(kind=rng.choice(('smoke', 'flare', 'fire')),
                                 center=(rng.randrange(width), rng.randrange(height)), radius=rng.randint(1, 4))
    for n in range(rng.randint(0, 3)):
        state['recon'][n] = dict(source=rng.choice(tuple(actors) + (99,)), shape=rng.choice(('square', 'circle')),
                                 center=(rng.randrange(width), rng.randrange(height)), radius=rng.randint(1, 5))
    for identity in actors:
        if rng.random() < .3: state['vision'][identity] = 1
        if rng.random() < .3: state['night_vision'][identity] = 1
        if rng.random() < .2: state['flash'][identity] = 1
    return combat


class SightFastPathTests(unittest.TestCase):
    def test_matches_previous_implementation_on_random_scenes(self):
        rng = random.Random(20261024); checked = positives = 0
        for _ in range(250):
            combat = scene(rng); field = combat.field
            for observer in field._actors.values():
                for y in range(field.height):
                    for x in range(field.width):
                        target = SimpleNamespace(x=x, y=y)
                        expected = reference(combat, observer, target)
                        self.assertEqual(effects.can_observe(combat, observer, target), expected,
                                         (observer, x, y, combat.item_effects))
                        checked += 1; positives += expected
        self.assertGreater(positives, checked // 20)  # Not a vacuous all-False comparison.

    def test_weather_prefilter_keeps_the_same_rain_cells(self):
        from tio import weather
        from tio.protocol.weather import decode_weather, MAX_CELLS
        rng = random.Random(7); compared = 0
        for _ in range(120):
            combat = scene(rng); field = combat.field; field.combat = combat
            field.scene_metadata = {'profile': next(iter(weather.policy()['profiles'])), 'seed': 0, 'objects': []}
            while not weather.raining(field): field.scene_metadata['seed'] += 1
            for owner in (0, 1):
                observers = [a for a in field._actors.values() if a.health and field.allied(a.owner_id, owner)]
                roofs = weather.sheltered(field)
                expected = [(x, y) for y in range(field.height) for x in range(field.width)
                            if (x, y) not in roofs and (x, y) not in field.blocked and not (x+2*y) % 3
                            and any(reference(combat, a, SimpleNamespace(x=x, y=y), field=field) for a in observers)]
                self.assertEqual(decode_weather(weather.packet(field, owner))[2], tuple(expected[:MAX_CELLS]))
                compared += bool(expected)
        self.assertGreater(compared, 50)

    def test_far_cells_trace_no_rays(self):
        combat = scene(random.Random(1)); field = combat.field
        state = initialize(combat); state['recon'].clear(); state['areas'].clear()
        observer = SimpleNamespace(actor_id=1, owner_id=1, x=0, y=0, health=100, sight_radius=2)
        field.item_darkness = False
        with patch.object(effects, 'clear_item_sight', side_effect=AssertionError('traced')):
            self.assertFalse(effects.can_observe(combat, observer, SimpleNamespace(x=7, y=7)))


if __name__ == '__main__':
    unittest.main()
