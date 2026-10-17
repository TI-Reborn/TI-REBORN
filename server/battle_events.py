"""Project authoritative action events to each client, without teleport snapshots.

Called under TeamArena.lock. Replays visibility on a copy of the field so hidden
parts of a movement route are never disclosed to opponents.
"""
from copy import copy
from dataclasses import replace

from tio.visibility import VisibilityView, visible_actors
from tio.protocol.battle_move import BattleMove, decode_battle_move, encode_battle_move
from tio.protocol.battle_attack import decode_attack_result, encode_attack_result
from tio.protocol.action_points import encode_action_points
from tio.protocol.health import encode_health
from tio.protocol.battle_soldier import decode_battle_soldier


def movement_packets(view, before, packet):
    move=decode_battle_move(packet);actor=before[move.actor_id]
    if actor.owner_id==view.owner:
        # Owned actors predict the first step. Keep the original complete path.
        return (packet,encode_action_points(actor.actor_id,view.field.actor(actor.actor_id).action_points),*view.refresh(visuals=False))
    replay=copy(view.field);replay._actors=dict(before)
    shadow=VisibilityView(replay,view.owner,view.templates)
    shadow.visible=view.visible;shadow.door_states=dict(view.door_states)
    shadow.hidden_living=dict(view.hidden_living)
    shadow.resident_corpses=set(view.resident_corpses)
    shadow.loot_states=dict(view.loot_states)
    replies=[]
    for x,y in move.path:
        old=shadow.visible
        replay._actors[actor.actor_id]=replace(replay.actor(actor.actor_id),x=x,y=y)
        current=visible_actors(replay,view.owner)
        if actor.actor_id in old & current:
            replies.append(encode_battle_move(BattleMove(actor.actor_id,((x,y),))))
        replies.extend(shadow.refresh(visuals=False))
    view.visible=shadow.visible;view.door_states=shadow.door_states
    view.hidden_living=shadow.hidden_living
    view.resident_corpses=shadow.resident_corpses
    view.loot_states=shadow.loot_states
    if actor.actor_id in view.visible:
        replies.append(encode_action_points(actor.actor_id,view.field.actor(actor.actor_id).action_points))
    return tuple(replies)


def project_action(view, owner, before, visible_before, packets, *, visuals=True):
    movement=next((p for p in packets if p[:1]==b'\x3d'),None)
    replies=list(movement_packets(view,before,movement)) if movement is not None else []
    # A stopped movement can include an immediate mine explosion. Keep that
    # damage/owned-inventory event after the actual animated path.
    packets=tuple(p for p in packets if p is not movement)
    hit_updates=set()
    for packet in packets:
        opcode=packet[0]
        identity=int.from_bytes(packet[1:5],'little')
        if opcode==0x4b:
            attack=decode_attack_result(packet)
            if attack.actor_id in visible_before:
                hits=tuple(h for h in attack.hits if h.actor_id in visible_before)
                replies.append(encode_attack_result(replace(attack,hits=hits)))
                hit_updates.update(h.actor_id for h in hits)
        elif opcode==0x3b:
            # Service replies include the acting owner's fog transitions. A
            # bot can hide a human's own soldiers here (255/255, HP=1).
            # Those transitions belong only to that view; each recipient's
            # refresh below computes its own fog. Real equipment/proficiency
            # changes must likewise use the recipient's authoritative model.
            resource=int.from_bytes(packet[9:13],'little')
            snapshot=decode_battle_soldier(packet,human_equipment=view.field.combat.human.get(identity,resource in (1,2,6)))
            if (snapshot.position!=(255,255) and identity in visible_before
                    and identity in visible_actors(view.field,view.owner)):
                replies.extend(view.snapshot_packets(identity))
        elif opcode==0x4e:
            if identity in visible_before:replies.append(packet)
        elif opcode==0x3f:
            if view.owner==owner:
                replies.append(packet)
                view.door_states[(packet[5],packet[6])]=bool(packet[7])
        elif opcode in (0x43,0x44,0x45):
            # Visibility transitions and door state are computed for this viewer.
            continue
        elif opcode==0x30:
            actor=view.field._actors.get(identity)
            if actor is not None and actor.owner_id==view.owner:replies.append(packet)
        elif view.owner==owner:
            # Inventory, cooldowns, loot and turn control remain owner-private.
            replies.append(packet)
    for identity in sorted(visible_before):
        actor=view.field._actors.get(identity)
        if actor is not None and identity in before and actor.health!=before[identity].health and identity not in hit_updates:
            replies.append(encode_health(identity,actor.health))
    replies.extend(view.refresh(visuals=visuals))
    own_snapshots={int.from_bytes(p[1:5],'little') for p in replies if p[0]==0x3b
                   and int.from_bytes(p[5:9],'little')==view.owner}
    described={int.from_bytes(p[1:5],'little') for p in replies if p[0]==0x3b}
    # Mine/burn kills occur outside the killer's own action and carry no
    # equipment view. Refresh changed sight from this recipient's state;
    # never disclose an unseen killer's coordinates or replay a corpse fall.
    current=visible_actors(view.field,view.owner)
    for identity in sorted(visible_before & current):
        actor=view.field._actors.get(identity)
        previous=before.get(identity)
        if (actor is not None and actor.health and previous is not None
                and actor.sight_radius!=previous.sight_radius and identity not in described):
            replies.extend(view.snapshot_packets(identity))
            if actor.owner_id==view.owner:own_snapshots.add(identity)
    replies.extend(view.field.combat.inventory_packet(i) for i in sorted(own_snapshots))
    return tuple(replies)


class BotEventArena:
    """Keep the existing AI, but publish each committed action before the next."""
    def __init__(self,hub,battle):self.hub,self.battle=hub,battle

    def __getattr__(self,name):return getattr(self.battle['arena'],name)

    def move(self,owner,packet):return self.hub.perform_action(self.battle,owner,packet)
    def end_turn(self,owner,packet):return self.hub.perform_action(self.battle,owner,packet)
    def begin_turn_packets(self,owner,actor_ids,seconds):return self.hub.begin_shared_turn(self.battle,owner,seconds,actor_ids=actor_ids)
    def attack(self,owner,packet,**kwargs):return self.hub.perform_action(self.battle,owner,packet)
    def door_action(self,owner,packet,**kwargs):return self.hub.perform_action(self.battle,owner,packet)
    def loot_action(self,owner,packet,**kwargs):return self.hub.perform_action(self.battle,owner,packet)
    def equip(self,owner,packet,**kwargs):return self.hub.perform_action(self.battle,owner,packet)
