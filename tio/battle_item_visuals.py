"""Project persistent smoke/light/recon cells for one real battle recipient.

This presentation never grants gameplay vision; battle_item_effects remains
authoritative. Cloud surfaces can be drawn on a visible line even when that
cloud itself blocks combat LOS. Far/covered cells and enemy recon are omitted.
"""
from .battle_item_effects import initialize, normal_sight, is_dark
from .visibility import field_sight
from .protocol.battle_item_visuals import encode_item_visuals, SMOKE, FLARE, RECON, FIRE, LIGHT, MAX_CELLS
from .protocol.night_vision_state import encode_night_vision_state


def visible_cells(field, owner):
    combat = getattr(field, 'combat', None)
    if combat is None: return ()
    state = initialize(combat)
    observers = [a for a in field._actors.values() if a.health and field.allied(a.owner_id, owner)]
    cells = {}
    for effect in state['areas'].values():
        if effect['kind'] not in ('smoke', 'flare'): continue
        cx, cy = effect['center']; radius = effect['radius']
        for y in range(max(0, cy-radius), min(field.height, cy+radius+1)):
            for x in range(max(0, cx-radius), min(field.width, cx+radius+1)):
                if (x-cx)**2+(y-cy)**2 > radius**2 or (x, y) in field.blocked: continue
                if any((a.x-x)**2+(a.y-y)**2 <=
                       (normal_sight(combat, a.actor_id) if effect['kind']=='flare' and is_dark(combat) else a.sight_radius)**2
                       and field_sight(field, (a.x, a.y), (x, y)) for a in observers):
                    # A cloud conceals light in an overlapping cell.
                    kind = SMOKE if effect['kind']=='smoke' else (FLARE if (x,y)==(cx,cy) else LIGHT)
                    cells[x, y] = min(cells.get((x, y), kind), kind)
    from .battle_hazards import fire_areas, fire_cells
    for effect in fire_areas(combat).values():
        for x,y in fire_cells(combat,effect):
            if any((a.x-x)**2+(a.y-y)**2 <= a.sight_radius**2
                   and field_sight(field,(a.x,a.y),(x,y)) for a in observers):
                if cells.get((x,y)) not in (SMOKE,FLARE):cells[x,y]=FIRE
    for effect in state['recon'].values():
        source = field._actors.get(effect['source'])
        if source is None or not source.health or not field.allied(source.owner_id, owner): continue
        cx, cy = effect['center']; radius = effect['radius']
        for y in range(max(0, cy-radius), min(field.height, cy+radius+1)):
            for x in range(max(0, cx-radius), min(field.width, cx+radius+1)):
                if ((x-cx)**2+(y-cy)**2 <= radius**2 and (x, y) not in field.blocked
                    and field_sight(field, (cx, cy), (x, y))):
                    cells.setdefault((x, y), RECON)
    # The fixed native extension buffer is bounded. Prefer nearest visible
    # cells, then stable coordinates; no truncation changes server mechanics.
    order = sorted(cells, key=lambda p: (min(((a.x-p[0])**2+(a.y-p[1])**2 for a in observers), default=0), p[1], p[0]))
    return tuple((x, y, cells[x, y]) for x, y in order[:MAX_CELLS])


def packets(field, owner):
    """Always send the full current snapshot, including empty to clear TTL."""
    combat = getattr(field, 'combat', None)
    active = () if combat is None else tuple(sorted(
        actor.actor_id for actor in field._actors.values()
        if actor.owner_id == owner and actor.health
        and actor.actor_id in initialize(combat)['night_vision']))
    from .weather import packet as weather_packet
    result=(encode_item_visuals(visible_cells(field, owner)), encode_night_vision_state(active),weather_packet(field,owner))
    if hasattr(field,'avatar_ids'):
        from .avatars import encode_assignments
        from .visibility import visible_actors
        result+=(encode_assignments((i,field.avatar_ids.get(i,0)) for i in sorted(visible_actors(field,owner))[:31]),)
    return result
