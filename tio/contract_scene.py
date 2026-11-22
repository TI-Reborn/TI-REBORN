"""Shared PvE scenes from real account selections and frozen contract policy.

The three new NPC roles use existing human resources and equipment. Their stats
and map composition are explicit provisional balance. NPCs exist only in battle
memory, never as owned pets, persistent accounts or copies of a player's squad.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import xml.etree.ElementTree as ET

from .battle_state import BattleActor
from .map_generation import generate_map
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.pet_info import PetInfo, SCHEMAS, encode_pet_info
from .protocol.battle_soldier import decode_battle_soldier
from .protocol.abilities import encode_abilities
from .visibility import VisibilityView
from .weapon_proficiency import NAMES, SAVED, BASE, bits
from .item_catalog import items_root

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / 'config/contracts_map_profiles.json'
ROLE_ORDER = ('scout', 'rifleman', 'heavy', 'dog', 'mutant', 'raider')
BOT_OWNER = 0x7fffffff
NPC_ACTOR_BASE = 0x71000000


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _asset_rules():
    """Detect incompatible changed resource rules instead of rebuilding silently."""
    paths = ('config/weapon_catalog.json', 'config/weapon_proficiency.json',
             'evidence/items_diagnostic.xml')
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}


def _validate(template, snapshot):
    if not isinstance(template, dict) or template.get('map_profile') not in ('contract_camp', 'contract_depot', 'contract_checkpoint'):
        raise ValueError('Unknown contract template')
    if type(snapshot) is not dict or snapshot.get('version') != 1:
        raise ValueError('Frozen contract scene policy is required')
    profile = snapshot.get('profile')
    if not isinstance(profile, dict) or not profile.get('enabled'):
        raise ValueError('Invalid frozen contract map profile')
    size = template.get('map_size')
    if size != [profile.get('width'), profile.get('height')] or any(type(n) is not int or not 24 <= n <= 64 for n in size):
        raise ValueError('Contract map size differs from its frozen profile')
    if snapshot.get('profile_name') != template.get('map_profile'):
        raise ValueError('Contract profile changed after acceptance')
    enemies = template.get('enemies')
    if (not isinstance(enemies, dict) or not set(enemies).issubset(ROLE_ORDER)
            or not enemies or any(type(n) is not int or not 1 <= n <= 8 for n in enemies.values())
            or not 1 <= sum(enemies.values()) <= 8):
        raise ValueError('Contract requires one to eight supported NPCs')
    from .weapons import WeaponCatalog
    from .armor import ArmorCatalog
    weapons, armor = WeaponCatalog(), ArmorCatalog()
    from .weapons import WeaponStats
    weapons.weapons[353] = WeaponStats(353, 'Sick Miner Attack', 'Melee', 12, 6, 4, None, None, 1, 1, 1)
    weapons.sources[353] = dict(weaponAttack='None', weaponType='Melee', accuracy='100')
    roles = snapshot.get('roles')
    if not isinstance(roles, dict) or set(roles) != set(enemies):
        raise ValueError('Frozen NPC roles differ from contract roster')
    for role in roles.values():
        if (not isinstance(role, dict) or role.get('resource_id') not in (1, 2, 100, 103)
                or not isinstance(role.get('name'), str) or not role['name'] or len(role['name'].encode('cp1251')) > 100):
            raise ValueError('NPC requires an existing human resource and bounded name')
        for key, lo, hi in (('level', 1, 20), ('health', 1, 65535), ('action_points', 1, 255),
                            ('sight_radius', 1, 255), ('carry_capacity', 1, 65535),
                            ('ammunition', 1, 10000), ('weapon_proficiency', 1, 75)):
            if type(role.get(key)) is not int or not lo <= role[key] <= hi:
                raise ValueError('Invalid NPC role statistic: ' + key)
        weapon = weapons.weapons.get(role.get('weapon_id'))
        if (weapon is None or weapon.attack_ap > role['action_points']
                or role['resource_id'] in (1, 2) and weapon.ammo_id is None):
            raise ValueError('NPC requires a verified usable weapon')
        occupied = set()
        if not isinstance(role.get('armor_ids'), list):
            raise ValueError('Invalid NPC armor list')
        for identity in role['armor_ids']:
            rule = armor.items.get(identity)
            if rule is None or rule[1] or rule[0] in occupied:
                raise ValueError('Invalid or duplicate NPC armor slot')
            occupied.add(rule[0])
    return weapons, armor


def freeze_policy(template, *, policy_path=POLICY_PATH):
    """Copy map/NPC choices at acceptance; callers persist this in template JSON."""
    policy = json.loads(Path(policy_path).read_text(encoding='utf-8'))
    if policy.get('version') != 1:
        raise ValueError('Unsupported contract scene policy version')
    name = template['map_profile']
    profile = deepcopy(policy.get('profiles', {}).get(name))
    roles = {name: deepcopy(policy['roles'][name]) for name in template['enemies']}
    snapshot = dict(version=1, profile_name=name, profile=profile, roles=roles)
    _validate(template, snapshot)
    fragments = json.loads((ROOT / 'config/arena_fragments.json').read_text())
    names = {name for pool in profile['pools'].values() for name in pool}
    if not names.issubset(fragments):
        raise ValueError('Contract map references an unverified fragment')
    snapshot['fragments_sha256'] = _digest({name: fragments[name] for name in sorted(names)})
    snapshot['asset_rules'] = _asset_rules()
    snapshot['content_sha256'] = _digest(snapshot)
    return snapshot


def _verify_frozen(template):
    if not isinstance(template, dict):
        raise ValueError('Frozen contract template is required')
    snapshot = deepcopy(template.get('scene_policy'))
    _validate(template, snapshot)
    expected = snapshot.pop('content_sha256', None)
    if expected != _digest(snapshot):
        raise ValueError('Frozen contract scene policy checksum mismatch')
    if snapshot.get('asset_rules') != _asset_rules():
        raise ValueError('Contract resource rules changed; reaccept the contract')
    profile = snapshot['profile']
    fragments = json.loads((ROOT / 'config/arena_fragments.json').read_text())
    names = {name for pool in profile['pools'].values() for name in pool}
    if not names.issubset(fragments) or snapshot.get('fragments_sha256') != _digest({name: fragments[name] for name in sorted(names)}):
        raise ValueError('Contract fragment rules changed; reaccept the contract')
    snapshot['content_sha256'] = expected
    return snapshot


def _profile(actor_id, role, weapon):
    """An explicit in-memory profile, independent of any saved account."""
    human = role['resource_id'] != 103
    fields = {key: (b'' if reader == 'CString' else 0) for key, _, reader in SCHEMAS[(human, False, False)]}
    fields.update({'0x8c43eb': actor_id, '0x8c446f': (1 if human else 3),
                   '0x8c4489': role['name'].encode('cp1251'), '0x8c4aef': role['level'],
                   '0x8c4a07': role['health'], '0x8c4ab1': role['health'],
                   '0x8c4a1b': role['sight_radius'], '0x8c4a2f': role['action_points'],
                   '0x8c4b57': role['carry_capacity']})
    for saved, base in zip(SAVED, BASE):
        fields[saved] = fields[base] = bits(0)
    index = NAMES.index(weapon.weapon_type)
    fields[SAVED[index]] = fields[BASE[index]] = bits(role['weapon_proficiency'])
    return encode_pet_info(PetInfo(human, fields))


def _inventory(actor_id, role, weapons, armor, instance_start, metadata):
    weapon = weapons.weapons[role['weapon_id']]
    choices = [(weapon.template_id, 1, 16), *[(i, 1, armor.items[i][0]) for i in role['armor_ids']]]
    if weapon.ammo_id is not None:
        choices.append((weapon.ammo_id, role['ammunition'], 0))
    items = []
    for offset, (identity, count, slot) in enumerate(choices):
        durability = int(metadata[identity].get('durability', 0))
        items.append(ItemRecord(instance_start + offset, identity, b'\0\0', count, int(slot != 0),
                                slot, (durability,) * 3, b'\0' * 4, None, b'\0' * 3))
    return encode_item_list(actor_id, tuple(items))


def prepare(seats, contract):
    """Return (field, real-owner views, ground packet, skills, transient NPC owner).

    seats use team_scene's (hub_owner, side, path, saved_account, SearchTicket,
    is_bot) format. Only real allied accounts and their selected owned pets are
    admitted. At most four accounts/eight selected actors enter the shared field.
    """
    seats = tuple(seats)
    if not 1 <= len(seats) <= 4 or any(len(s) != 6 for s in seats):
        raise ValueError('Contract requires one to four real account seats')
    owners = set()
    accounts = set()
    for owner, side, path, account, ticket, bot in seats:
        if (type(owner) is not int or not 1 <= owner < BOT_OWNER or owner in owners
                or side != 0 or bot is not False or path is None or not account
                or (str(Path(path).resolve()), account) in accounts
                or ticket.character_id != owner or not 1 <= len(ticket.actors) <= 3
                or len(ticket.actors) != len(ticket.levels) or len(set(ticket.actors)) != len(ticket.actors)):
            raise ValueError('Invalid real account selection for contract')
        owners.add(owner)
        accounts.add((str(Path(path).resolve()), account))
    humans = sum(len(s[4].actors) for s in seats)
    if humans > 8:
        raise ValueError('Contracts admit at most eight real owned actors')
    if not isinstance(contract, dict) or type(contract.get('seed')) is not int or not 0 <= contract['seed'] < 2**64:
        raise ValueError('Contract requires a frozen unsigned 64-bit seed')
    template = deepcopy(contract.get('template'))
    snapshot = _verify_frozen(template)
    enemies = template['enemies']
    count = sum(enemies.values())
    generated = generate_map(snapshot['profile_name'], seed=contract['seed'],
        deployment_size=max(humans, count, 3), mode=7,
        profiles_data={'profiles': {snapshot['profile_name']: snapshot['profile']}})
    from .team_scene import prepare as prepare_team
    # PvE admits a selected mixed-level squad; no PvP wager rewards are enabled.
    field, views, ground, skills = prepare_team(seats, 7, seed=contract['seed'],
        profile=snapshot['profile_name'], arena_map=generated.arena, selected_ids=True, wager=True,
        require_full_health=False)
    field.teams[BOT_OWNER] = 1
    field.combat.rng = random.Random(contract['seed'] ^ 0x434F4E5452414354)
    weapons, armor = _validate(template, snapshot)
    field.combat.catalog.weapons[353] = weapons.weapons[353]
    field.combat.catalog.sources[353] = weapons.sources[353]
    templates = dict(next(iter(views.values())).templates)
    metadata = {int(node.get('id')): {v.get('key'): v.get('val') for v in node.findall('value')}
                for node in items_root()}
    used_item_ids = {item.instance_id for inventory in field.combat.inventories.values()
                     for item in decode_item_list(inventory)[1]}
    item_id = max(0x72000000, field.loot.next_id, max(used_item_ids, default=0) + 1)
    permissions = dict(field.doors.permissions)
    npc_roles = {}
    npc_item_ids = set()
    boss = None
    from tools.battle_actor_fixture import actor_packet
    for role_name in ROLE_ORDER:
        for _ in range(enemies.get(role_name, 0)):
            role = snapshot['roles'][role_name]
            human = role['resource_id'] != 103
            actor_id = NPC_ACTOR_BASE + len(npc_roles) + 1
            if len(npc_roles) == count - 1:
                boss = actor_id
                role = {**role, 'name': role['name'] + ' — босс', 'health': role['health'] * 2}
            x, y = generated.arena.bot_spawns[len(npc_roles)]
            weapon = weapons.weapons[role['weapon_id']]
            if item_id + len(role['armor_ids']) + 1 > 0xffffffff:
                raise ValueError('NPC item ID space exhausted')
            inventory = _inventory(actor_id, role, weapons, armor, item_id, metadata)
            item_id += len(decode_item_list(inventory)[1])
            if item_id > 0xffffffff:
                raise ValueError('NPC item ID space exhausted')
            profile = _profile(actor_id, role, weapon)
            field._actors[actor_id] = BattleActor(actor_id, BOT_OWNER, x, y, role['action_points'],
                role['health'], role['health'], role['sight_radius'], (weapon,))
            field._turn_points[actor_id] = role['action_points']
            field._ability_turns[actor_id] = 0
            field.combat.register(actor_id, inventory, human=human, pet_packet=profile)
            field.combat.resources[actor_id] = role['resource_id']
            native = decode_battle_soldier(actor_packet(profile, BOT_OWNER, inventory, human=human,
                actor_id=actor_id, name=role['name'].encode('cp1251'), x=x, y=y, team=1, color=len(seats)), human_equipment=human)
            templates[actor_id] = replace(native, fields={**native.fields, '0x8c50fb': role['resource_id']})
            permissions[actor_id] = frozenset((True, False)) if human else frozenset()
            # BattleLoot treats temporary_items as transferable corpse loot.
            # NPC equipment must remain battle-local and never become loot.
            npc_item_ids.update(i.instance_id for i in decode_item_list(inventory)[1])
            field.combat.skill_packets(actor_id)
            skills[actor_id] = encode_abilities(actor_id, ())
            npc_roles[actor_id] = role_name
    from .battle_doors import BattleDoors
    from .battle_loot import BattleLoot
    field.doors = BattleDoors(field, generated.arena.doors, permissions)
    field.loot = BattleLoot(field.combat, generated.arena.containers, level=max(l for s in seats for l in s[4].levels),
                           rng=random.Random(contract['seed'] ^ 0x4C4F4F54))
    from .contract_loot import populate_crates
    populate_crates(field.loot)
    field.patrol_waypoints = generated.patrol
    field.scene_metadata = dict(profile=generated.profile, variant=generated.variant, seed=generated.seed,
        width=field.width, height=field.height, objects=deepcopy(generated.layout['objects']),
        crates=len(field.loot.boxes), visual_containers=len(generated.arena.containers), doors=len(generated.arena.doors))
    field.contract_metadata = dict(instance_id=contract.get('id'), template_id=template['id'],
        seed=contract['seed'], policy_sha256=snapshot['content_sha256'], npc_roles=npc_roles,
        human_actors=humans, npc_actors=count, boss=boss, provisional_balance=True)
    field.contract_transient_items = frozenset(npc_item_ids)
    views = {owner: VisibilityView(field, owner, dict(templates)) for owner in sorted(owners)}
    return field, views, ground, skills, BOT_OWNER
