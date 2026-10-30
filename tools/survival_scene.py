"""Prepare a local training opponent and full selected squad atomically.

The opponent mirrors the player's resources/equipment/skills. It is transient:
no hires, wallet changes or ability grants are written to the account.
Ground and spawns come from a fresh Reservation scene; AP uses the local profile.
"""
from contextlib import closing
from dataclasses import dataclass, replace
import sqlite3
from tio.owned_pets import OwnedPetStore
from tio.matchmaking import SurvivalQueue, SquadAdmissionError
from tio.ranked_party import MAX_FIGHTERS, is_ranked_level
from tio.passive_stats import project_passives
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.abilities import decode_abilities, encode_abilities
from tio.protocol.battle_ground import encode_battle_ground
from tio.protocol.known_mines import encode_known_mines
from tio.battle_state import BattleActor, BattleField
from tools.battle_actor_fixture import actor_packet


@dataclass(frozen=True)
class PreparedSurvival:
    field: BattleField
    packets: tuple[bytes, ...]
    bot_owner: int
    actor_ids: tuple[int, ...]
    visibility: object = None
    mode: int = 0
    participants: tuple[int, ...] = ()


def prepare_survival(path, account, ticket, catalog, *, arena_map=None, seed=None, mode=0, admitted_prefix=False, selected_ids=False,allow_mixed_levels=False,ranked=False):
    from tio.battle_modes import mode_rules, level_band, BattleMode
    if ranked and (mode!=0 or not selected_ids or allow_mixed_levels):raise ValueError('Invalid ranked scene policy')
    policy = BattleMode(0,2,MAX_FIGHTERS) if ranked else mode_rules(mode)
    policy.validate(len(ticket.actors))
    if ranked and (len(ticket.actors)!=len(ticket.levels) or len(set(ticket.actors))!=len(ticket.actors)
                   or any(type(level) is not int or not is_ranked_level(level) for level in ticket.levels)):
        raise ValueError('Invalid ranked squad')
    if mode and not allow_mixed_levels and len({level_band(level) for level in ticket.levels}) != 1:
        raise ValueError('Team fighters must belong to the same level range')
    per_side = policy.players // 2 * len(ticket.actors)
    from tio.dog_abilities import catalog_for_play as dog_catalog
    from tio.restored_abilities import catalog_with_restored
    catalog=dog_catalog(catalog_with_restored(catalog))
    from tio.weapons import WeaponCatalog
    weapons=WeaponCatalog()
    generated = None
    if arena_map is None:
        from tio.map_generation import generate_map
        generated = generate_map(seed=seed, deployment_size=max(3,per_side),mode=mode)
        arena_map = generated.arena
    if min(len(arena_map.player_spawns),len(arena_map.bot_spawns)) < per_side:
        raise ValueError('Map has insufficient team deployment cells')
    sources = {}
    from tio.db_transaction import connect
    with closing(connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        from tio.ranks import sync
        sync(db,account)
        rows = db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id', (account,)).fetchall()
        saved = tuple((i, bytes(p), bytes(inv)) for i, human, p, inv in rows)
        if selected_ids:
            chosen=[]
            owned={i:(human,p,inv) for i,human,p,inv in rows}
            for i in ticket.actors:
                if i not in owned:raise SquadAdmissionError('Selected fighter no longer owned')
                human,p,inv=owned[i]
                # Recovery persists current HP against the derived maximum;
                # Saved maxHP is the base value; learned/equipment bonuses
                # belong to the city/admission copy, never the saved packet.
                from tio.passive_stats import project_saved_pet
                pet=decode_pet_info(project_saved_pet(db,account,i,bytes(p),bool(human)),human_equipment=bool(human))
                if pet.fields['0x8c4ab1']!=pet.fields['0x8c4a07']:raise SquadAdmissionError('Ranked fighter is wounded')
                chosen.append((i,encode_pet_info(replace(pet,fields={**pet.fields,'0x8c44a6':len(chosen)+1})),bytes(inv)))
            saved=tuple(chosen)
        if admitted_prefix:
            # Shared Wall admits the first selected fighter; Team matchmaking
            # may shorten the squad. Validate that exact current prefix rather
            # than comparing it to all selected reserves. Never rewrite saves.
            selected=[]
            for i,human,p,inv in rows:
                slot=decode_pet_info(p,human_equipment=bool(human)).fields['0x8c44a6']
                if slot in (1,2,3):selected.append((slot,i,bytes(p),bytes(inv)))
            if len({s for s,_,_,_ in selected})!=len(selected):
                raise ValueError('Duplicate selected squad slot')
            saved=tuple((i,p,inv) for _,i,p,inv in sorted(selected)[:len(ticket.actors)])
        if ranked:
            # The original C6 selection is independent of the saved barracks'
            # three slots. Read actual owned packets again; never pad, truncate
            # or rewrite persistent squad selections to admit the fourth pet.
            from tio.matchmaking import SearchTicket
            fresh=SearchTicket(ticket.character_id,tuple(i for i,p,inv in saved),
                              tuple(decode_pet_info(p,human_equipment=bool(owned[i][0])).fields['0x8c4aef'] for i,p,inv in saved),ticket.joined_at)
        else:
            fresh = SurvivalQueue().join(ticket.character_id, saved,mode=1 if allow_mixed_levels else mode if admitted_prefix else 0)
        if (fresh.actors, fresh.levels) != (ticket.actors, ticket.levels):
            raise SquadAdmissionError('Selected squad changed during search')
        has_skills = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_states'").fetchone()
        for i, human, p, inv in rows:
            if i not in ticket.actors: continue
            human = bool(human)
            if OwnedPetStore.validate(p, inv, human) != i:
                raise ValueError('Saved actor identity mismatch')
            learned = ()
            skill = db.execute('SELECT packet FROM ability_states WHERE account=? AND pet_id=?', (account,i)).fetchone() if has_skills else None
            if skill:
                owner, learned, learning = decode_abilities(skill[0])
                if owner != i or learning: raise ValueError('Invalid saved skills')
            if len({e.ability_id for e in learned}) != len(learned) or any((e.ability_id,e.level) not in catalog.by_key for e in learned):
                raise ValueError('Invalid learned skill ranks')
            from tio.weapon_proficiency import ProficiencyRules
            projected = project_passives(ProficiencyRules().normalize(bytes(p),human),human,learned,catalog,inventory=bytes(inv))
            sources[i] = (human, projected, bytes(inv), learned)
    bot_owner = 0x7fffffff
    participants = (ticket.character_id, *(bot_owner-i for i in range(policy.players-1)))
    if len(set(participants)) != len(participants): raise ValueError('Reserved training owner collision')
    teams = {owner:index % 2 for index,owner in enumerate(participants)} if mode else {}
    occupied_ids = {r[0] for r in rows}
    next_id = 0x7ffffffe
    actors, packets, rules = [], [], []
    combat_inventories=[]
    actor_sources={}
    for index, source_id in enumerate(ticket.actors):
        human, p, inv, learned = sources[source_id]
        fields = decode_pet_info(p,human_equipment=human).fields
        for seat, owner in enumerate(participants):
            if seat == 0:
                actor_id, name = source_id, None
            else:
                while next_id in occupied_ids: next_id -= 1
                actor_id = next_id; occupied_ids.add(actor_id); next_id -= 1
                name = b'Training bot' if not mode else (b'Ally ' if seat % 2 == 0 else b'Enemy ') + str(seat//2+1).encode()
            side = seat % 2
            position = (arena_map.player_spawns,arena_map.bot_spawns)[side][(seat//2)*len(ticket.actors)+index]
            actor_sources[actor_id] = source_id
            x,y = position
            # Human radius requested by the user; dogs retain the provisional12.
            miner=fields['0x8c446f']==6
            from tio.equipment_bonuses import bonuses
            sight=(8 if miner else 9 if human else 12)+bonuses(inv,fields['0x8c446f'])['sight']
            actors.append(BattleActor(actor_id,owner,x,y,14 if miner else 15 if human else 17,fields['0x8c4ab1'],fields['0x8c4a07'],sight_radius=sight,
                                      weapons=weapons.equipped(inv,human=human,resource=fields['0x8c446f'])))
            from tio.protocol.item_list import decode_item_list,encode_item_list
            _,combat_items,combat_unknown=decode_item_list(inv)
            combat_inventories.append((actor_id,encode_item_list(actor_id,combat_items,combat_unknown),human,owner==ticket.character_id,p))
            from tio.weapon_effects import battle_skills
            packets.extend((actor_packet(p,owner,inv,human=human,actor_id=actor_id,name=name,x=x,y=y,team=side,color=seat),encode_abilities(actor_id,battle_skills(learned,inv,human))))
            if not human or any(e.ability_id==22 for e in learned): rules.append((owner,actor_id,fields['0x8c446f'],learned))
    field = BattleField(arena_map.ground.width,arena_map.ground.height,actors,blocked=arena_map.blocked,step_cost=1,teams=teams,transparent_obstacles=arena_map.transparent_obstacles)
    field.battle_mode = mode
    field.scene_metadata = {'profile':'fixed_fixture'}
    if generated is not None:
        field.patrol_waypoints = generated.patrol
        field.scene_metadata = dict(profile=generated.profile, variant=generated.variant, seed=generated.seed,
                                    width=arena_map.ground.width, height=arena_map.ground.height,
                                    objects=generated.layout['objects'], crates=len(arena_map.containers))
    from tio.combat import Combat
    field.combat=Combat(field,weapons)
    for actor_id,inventory,human,persistent,p in combat_inventories:
        field.combat.register(actor_id,inventory,human=human,path=path if persistent else None,account=account,pet_packet=p)
        field._actors[actor_id]=replace(field.actor(actor_id),action_points=field.combat.turn_budget(actor_id,field._turn_points[actor_id]))
    from tio.battle_doors import BattleDoors
    permissions={}
    for index,actor in enumerate(actors):
        human,_,_,learned=sources[actor_sources[actor.actor_id]]
        field.combat.configure_accuracy(actor.actor_id,learned,catalog)
        field.combat.skill_packets(actor.actor_id) # Initial list is already in scene packets.
        field.combat.configure_armor_display(actor.actor_id,learned,catalog)
        skills={entry.ability_id for entry in learned if entry.level>0}
        permissions[actor.actor_id]=frozenset(state for state,skill in ((True,14),(False,19)) if human or skill in skills)
    field.doors=BattleDoors(field,arena_map.doors,permissions)
    field.scene_metadata['doors']=len(arena_map.doors)
    for rule in rules:
        if rule[2]==6:field.configure_miner_slash(*rule)
        else:
            from tio.dog_abilities import configure
            configure(field,*rule,catalog)
    from tio.battle_loot import BattleLoot
    field.loot=BattleLoot(field.combat,arena_map.containers,level=max(ticket.levels))
    if generated is not None:
        # Separate RNG stream keeps loot independent of placement retries and
        # opening order. Nothing is written into the persistent account.
        import random
        field.loot.rng = random.Random(generated.seed ^ 0x4C4F4F545F54494F)
        for position in field.loot.boxes:
            field.loot.boxes[position] = field.loot._roll()
    ground = encode_battle_ground(arena_map.ground)
    from tio.visibility import VisibilityView
    from tio.protocol.battle_soldier import decode_battle_soldier
    templates={}
    for index, actor in enumerate(actors):
        source_id=actor_sources[actor.actor_id]
        templates[actor.actor_id]=decode_battle_soldier(packets[index*2],human_equipment=sources[source_id][0])
    view=VisibilityView(field,ticket.character_id,templates)
    visible_packets=view.refresh()
    own_skills=tuple(packets[index*2+1] for index,a in enumerate(actors) if a.owner_id==ticket.character_id)
    # City inventories are discarded on scene entry. Send complete item lists
    # after their actors exist and before the scene-ready marker.
    own_inventories=tuple(field.combat.inventory_packet(i) for i in ticket.actors)
    field.scene_metadata.update(mode=mode,players=policy.players,teams=teams)
    return PreparedSurvival(field,(ground,*visible_packets,*own_skills,*own_inventories,encode_known_mines(()),b'\x41'),bot_owner,ticket.actors,view,mode,participants)
