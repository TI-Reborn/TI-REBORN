"""Persistent per-battle doors; one AP, original cost_moves_opendoor default."""
from dataclasses import replace
from .protocol.battle_door import encode_door_state
from .protocol.battle_door import DoorRequest
from .protocol.action_points import encode_action_points
from .visibility import clear_sight


class BattleDoors:
    def __init__(self,field,positions,permissions):
        self.field=field
        self.states={(x,y):opened for x,y,opened in positions}
        if len(self.states)!=len(positions) or any(not field.inside(*p) for p in self.states):
            raise ValueError('Invalid door positions')
        self.permissions=permissions
        self.solid=field.blocked-frozenset(self.states)
        self._sync()

    def _sync(self):
        self.field.blocked=self.solid|frozenset(p for p,opened in self.states.items() if not opened)

    def visible_updates(self,owner,remembered):
        observers=[a for a in self.field._actors.values() if self.field.allied(a.owner_id,owner) and a.health!=0]
        replies=[]
        for p,opened in self.states.items():
            if remembered.get(p)==opened:continue
            # Adjacent door surfaces are interactive even across a wall corner.
            # This exposes only the door state; actor/terrain sight is unchanged.
            if any((a.x-p[0])**2+(a.y-p[1])**2<=a.sight_radius**2 and
                   (max(abs(a.x-p[0]),abs(a.y-p[1]))<=1 or
                    clear_sight((a.x,a.y),p,self.field.blocked-{p})) for a in observers):
                replies.append(encode_door_state(DoorRequest(0,opened,*p)))
                remembered[p]=opened
        return tuple(replies)

    def change(self,owner,request,*,view=None):
        actor=self.field._actors.get(request.actor_id)
        p=(request.x,request.y)
        if actor is None or actor.owner_id!=owner or not actor.health:raise ValueError('Living owned actor required')
        if p not in self.states:raise ValueError('No door at this cell')
        if request.opened not in self.permissions.get(actor.actor_id,()):raise ValueError('Actor cannot operate this door')
        if max(abs(actor.x-p[0]),abs(actor.y-p[1]))>1:
            raise ValueError('Move next to the door')
        # All eight neighboring cells can operate a door. Corner collision
        # still applies to movement and sight, not this adjacent interaction.
        if self.states[p]==request.opened:
            return (encode_door_state(request),encode_action_points(actor.actor_id,actor.action_points))
        if not request.opened and any((a.x,a.y)==p and a.health!=0 for a in self.field._actors.values()):
            raise ValueError('Doorway is occupied')
        if actor.action_points<1:raise ValueError('Insufficient AP for door')
        self.states[p]=request.opened
        self._sync()
        actor=replace(actor,action_points=actor.action_points-1)
        self.field._actors[actor.actor_id]=actor
        if view is not None:view.door_states[p]=request.opened
        return (encode_door_state(request),encode_action_points(actor.actor_id,actor.action_points),
                *(() if view is None else view.refresh()))
