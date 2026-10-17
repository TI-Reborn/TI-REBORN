"""Bind decorative city surroundings after authoritative map validation.

The native scene is rendered from one named GroundEntry at 0,0. Its models
may have signed positions outside the field, but no server objects, collision
cells, dimensions or player coordinates are derived from the decorative art.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from .protocol.battle_ground import GroundEntry, encode_battle_ground


ROOT = Path(__file__).resolve().parents[1]
CITY_RESOURCES = {
    'reservation': ('rv', 'R'),
    'denver': ('de', 'D'),
    'new_york': ('ny', 'N'),
    'military_zone': ('mz', 'M'),
}
SIZES = (38, 57)


def load_surroundings_policy(path=None):
    """Read the current policy, including callers' temporary config fixtures."""
    source = ROOT/'config/arena_surroundings.json' if path is None else Path(path)
    policy = json.loads(source.read_text(encoding='utf-8'))
    if type(policy.get('version')) is not int or policy['version'] != 1:
        raise ValueError('Unsupported arena surroundings policy')
    profiles = policy.get('profiles')
    if not isinstance(profiles, dict) or set(profiles) != set(CITY_RESOURCES):
        raise ValueError('Arena surroundings require the four city profiles')
    for profile, (code, prefix) in CITY_RESOURCES.items():
        row = profiles[profile]
        if not isinstance(row, dict) or type(row.get('enabled', True)) is not bool:
            raise ValueError('Invalid arena surroundings profile')
        variants = row.get('variants')
        if not isinstance(variants, list) or len(variants) != 3:
            raise ValueError('Arena surroundings require three city variants')
        for number, variant in enumerate(variants, 1):
            if not isinstance(variant, dict) or variant.get('id') != prefix+str(number):
                raise ValueError('Invalid city surroundings variant')
            scenes = variant.get('scene_by_size')
            expected = {str(size): f'as_{code}_{number}_{size}' for size in SIZES}
            if scenes != expected:
                # A config typo must not silently bind another city's art or
                # an unbounded path to the native basename resource index.
                raise ValueError('City surroundings scene does not match its city/variant/size')
    return policy


def select_surroundings(profile, seed, width, height, *, mode=0, config_path=None):
    """Use a domain-separated seed digest without consuming gameplay RNG."""
    if profile not in CITY_RESOURCES:
        return None
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Expected unsigned 64-bit surroundings seed')
    if type(mode) is not int or mode not in (0, 1, 4, 7):
        raise ValueError('Unsupported city surroundings mode')
    if type(width) is not int or type(height) is not int or width != height or width not in SIZES:
        raise ValueError('Unsupported city surroundings dimensions')
    row = load_surroundings_policy(config_path)['profiles'][profile]
    if not row.get('enabled', True):
        return None
    material = f'tio-arena-surroundings-v1\0{profile}\0{seed}\0{width}\0{height}'.encode('ascii')
    index = int.from_bytes(hashlib.sha256(material).digest()[:8], 'little') % len(row['variants'])
    selected = row['variants'][index]
    return dict(profile=profile, variant=selected['id'], scene=selected['scene_by_size'][str(width)],
                width=width, height=height)


def add_arena_surroundings(arena, profile, seed, *, mode=0, config_path=None):
    """Append one visual scene; retain every authoritative ArenaMap field."""
    selected = select_surroundings(profile, seed, arena.ground.width, arena.ground.height,
                                   mode=mode, config_path=config_path)
    if selected is None:
        return arena, None
    entry = GroundEntry(selected['scene'].encode('ascii'), 0, 0)
    existing = tuple(e for e in arena.ground.entries if e.name.startswith(b'as_'))
    if existing:
        if existing != (entry,):
            raise ValueError('Arena already contains a different or duplicate surroundings scene')
        return arena, selected
    ground = replace(arena.ground, entries=(*arena.ground.entries, entry))
    # Enforce the real transport limit after the additional resource name.
    encode_battle_ground(ground)
    return replace(arena, ground=ground), selected
