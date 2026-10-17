"""Actor visibility uses per-observer radius and original tile-class sight rays.

Unclassified synthetic fields retain the conservative centre-ray fallback.
Squad sharing/radii are configured separately from the recovered ray geometry.
"""
from dataclasses import replace
from .protocol.battle_soldier import encode_battle_soldier
from .protocol.battle_remove import encode_battle_remove


def clear_sight(start, end, opaque):
    x,y=start;tx,ty=end
    dx,dy=abs(tx-x),abs(ty-y)
    sx=1 if tx>x else -1;sy=1 if ty>y else -1
    ix=iy=0
    while ix<dx or iy<dy:
        a=(1+2*ix)*dy;b=(1+2*iy)*dx
        if a==b:
            if (x+sx,y) in opaque or (x,y+sy) in opaque:return False
            x+=sx;y+=sy;ix+=1;iy+=1
        elif a<b:x+=sx;ix+=1
        else:y+=sy;iy+=1
        if (x,y) in opaque:return False
    return True


def field_sight(field,start,end):
    transparent=getattr(field,'transparent_obstacles',None)
    if transparent is None:return clear_sight(start,end,field.blocked)
    from .shot_geometry import clear_shot
    return clear_shot(start,end,field.blocked-transparent)


def visible_actors(field, owner):
    combat=getattr(field,'combat',None)
    if combat is not None:
        from .battle_item_effects import visible_actors as item_visibility
        return item_visibility(combat,owner,field=field)
    own=[a for a in field._actors.values() if field.allied(a.owner_id,owner)]
    observers=[a for a in own if a.health != 0]
    visible={a.actor_id for a in own}
    for actor in field._actors.values():
        if actor.actor_id in visible:continue
        if any((a.x-actor.x)**2+(a.y-actor.y)**2<=a.sight_radius**2 and
               field_sight(field,(a.x,a.y),(actor.x,actor.y)) for a in observers):
            visible.add(actor.actor_id)
    return frozenset(visible)


class VisibilityView:
    def __init__(self, field, owner, templates):
        self.field,self.owner,self.templates=field,owner,templates
        self.visible=frozenset()
        self.hidden_living={}
        # Corpses are stationary, already disclosed scene objects. Retain their
        # native animation state across LOS changes instead of removing/readding
        # them (3B resets to idle; a subsequent HP transition replays the fall).
        # This is separate from visible: a retained corpse never grants sight.
        self.resident_corpses=set()
        self.loot_states={}
        doors=getattr(field,'doors',None)
        # Original map fragments can draw a closed door over a walkable,
        # transparent cell. Send its initial authoritative 3F state as soon as
        # its surface is observable, including on scene load/reconnect.
        self.door_states={}

    def snapshot(self, actor_id, *, hidden=False, health=None):
        actor=self.field.actor(actor_id)
        template=self.templates[actor_id]
        weights={}
        combat=getattr(self.field,'combat',None)
        if combat is not None and actor_id in combat.inventories:
            weights['0x8c5731']=combat.displayed_armor(actor_id)
            if actor_id in combat.proficiencies:
                from .equipment_bonuses import project
                from .weapon_proficiency import battle_fields
                weights.update(battle_fields(project(combat.proficiencies[actor_id],combat.human[actor_id],combat.inventories[actor_id]),combat.human[actor_id]))
        if combat is not None and actor_id in combat.weight_capacities:
            from .weight import inventory_weight
            weights.update({'0x8c57e7':min(65535,inventory_weight(combat.inventories[actor_id])),
                            '0x8c57d0':combat.weight_capacity(actor_id)})
        return encode_battle_soldier(replace(template,fields={**template.fields,
            '0x8c519b':255 if hidden else actor.x,'0x8c51af':255 if hidden else actor.y,
            '0x8c57bb':actor.health if health is None else health,
            '0x8c566a':actor.max_health,'0x8c571d':actor.action_points,
            '0x8c5694':self.field._turn_points[actor_id],
            '0x8c567f':actor.sight_radius,**weights}))

    def snapshot_packets(self, actor_id):
        # Native 3B always selects idle animation, even with zero HP. Native
        # 4E/status4 invokes DeathAnimation only on a decreasing HP update.
        # For a corpse first discovered by this viewer, initialise death once.
        # A previously displayed corpse keeps its existing scene and animation;
        # never replay this transition on fog return or equipment refresh.
        # Authoritative HP never changes.
        if self.field.actor(actor_id).health==0:
            if actor_id in self.resident_corpses:return ()
            from .protocol.health import encode_health
            self.resident_corpses.add(actor_id)
            return self.snapshot(actor_id,health=1),encode_health(actor_id,0)
        return (self.snapshot(actor_id),)

    def refresh(self,*,visuals=True):
        current=visible_actors(self.field,self.owner)
        self.resident_corpses={i for i in self.resident_corpses | set(self.visible)
                               if i in self.field._actors and self.field.actor(i).health==0}
        replies=tuple(encode_battle_remove(i) for i in sorted(self.visible-current-self.resident_corpses))
        # The native owner-eliminated predicate scans non-removed actor models,
        # not member-list counts. Keep enemies in every game mode registered off-map
        # while hidden. 255/255 is the native absent-position sentinel; only
        # the alive/dead bit is refreshed, never their hidden route or HP.
        if getattr(self.field,'battle_mode',None) is not None:
            hidden={i:bool(a.health) for i,a in self.field._actors.items()
                    if i not in current and i not in self.resident_corpses
                    and not self.field.allied(a.owner_id,self.owner)}
            replies+=tuple(self.snapshot(i,hidden=True,health=int(alive))
                           for i,alive in sorted(hidden.items())
                           if i in self.visible or self.hidden_living.get(i)!=alive)
            self.hidden_living=hidden
        replies+=tuple(p for i in sorted(current-self.visible) for p in self.snapshot_packets(i))
        self.visible=current
        doors=getattr(self.field,'doors',None)
        if doors is not None:replies+=doors.visible_updates(self.owner,self.door_states)
        mining=getattr(self.field,'mining',None)
        if mining is not None:replies+=mining.packets(self.owner)
        loot=getattr(self.field,'loot',None)
        if loot is not None:replies+=loot.visible_updates(self.owner,self.loot_states,field=self.field)
        if visuals and getattr(self.field,'combat',None) is not None:
            from .battle_item_visuals import packets as item_visual_packets
            replies+=item_visual_packets(self.field,self.owner)
        return replies
