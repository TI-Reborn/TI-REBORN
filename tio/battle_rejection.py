"""Finish a refused native action queue without moving or charging an actor.

F0 resets the city wait flag only. ti.exe6dc9be skips the first3D point for
an owned actor (the client has already predicted that step). Repeat the
authoritative position so the second point actually reaches the scene queue
and corrects that prediction. A single point only updates the model, leaving
the rendered actor and its door interaction position out of sync.
"""
from .protocol.battle_move import BattleMove,encode_battle_move
from .protocol.action_points import encode_action_points


def restore_actor(field,owner,packet):
    if field is None:return ()
    offset=5 if packet[:1]==b'\x81' else 1
    if len(packet)<offset+4:return ()
    actor=field._actors.get(int.from_bytes(packet[offset:offset+4],'little'))
    if actor is None or actor.owner_id!=owner:return ()
    return (encode_battle_move(BattleMove(actor.actor_id,((actor.x,actor.y),)*2)),
            encode_action_points(actor.actor_id,actor.action_points))
