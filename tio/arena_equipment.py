"""Authenticated client extension for staged battle equipment.

Validation failures are replies inside the enclosing journal transaction: an
invalid batch must remain cancelled when that transaction is checkpointed.
Storage failures retain the normal battle recovery path.
"""
from functools import wraps


def action(arena, owner, packet, *, view=None):
    from .protocol.equipment_batch import decode_equipment_batch, STAGE, COMMIT, CANCEL
    from .equipment_batch import EquipmentBatchRejected
    from .protocol.system_message import encode_shop_error
    room = next((r for r in arena.rooms.snapshot() if owner in r.members), None)
    field = None if room is None else arena._fields.get(room.room_id)
    combat = getattr(field, 'combat', None)
    if combat is None:
        return (encode_shop_error('Смена экипировки доступна только в бою'),)
    try:
        request = decode_equipment_batch(packet)
        if request.operation == CANCEL:
            return combat.cancel_equipment_batch(owner, batch_id=request.batch_id)
        turn = arena._turns.get(room.room_id)
        if turn is None or turn[0] != owner or arena._clock() >= turn[2]:
            raise ValueError('Смена экипировки доступна только в свой ход')
        if request.operation == STAGE and request.action.pet_id not in turn[1]:
            raise ValueError('Боец не участвует в текущем ходе')
        # Battle inventories already carry shared actor IDs. Never resolve an
        # account-local ID here: it could alias another account's actor.
        key = (owner, tuple((i, field._ability_turns.get(i, 0)) for i in sorted(turn[1])))
        if request.operation == STAGE:
            return combat.stage_equipment_batch(owner, request, key)
        if request.operation == COMMIT:
            pending = getattr(combat, 'equipment_batches', {}).get(owner)
            if pending is not None and not set(pending['actors']).issubset(turn[1]):
                raise ValueError('Состав текущего хода изменился')
            replies=combat.commit_equipment_batch(owner, request, key, view=view)
            from .battle_item_effects import refresh_sight
            return (*replies,*refresh_sight(combat))
    except ValueError as error:
        restores = error.restores if isinstance(error, EquipmentBatchRejected) else combat.cancel_equipment_batch(owner)
        # Restore before error, so the UI cannot keep a rejected preview.
        return (*restores, encode_shop_error(str(error)[:180]))


def inventory_mutation(method):
    """Accepted inventory actions discard any older private preview."""
    @wraps(method)
    def wrapped(arena, owner, *args, **kwargs):
        result = method(arena, owner, *args, **kwargs)
        room = next((r for r in arena.rooms.snapshot() if owner in r.members), None)
        field = None if room is None else arena._fields.get(room.room_id)
        combat = getattr(field, 'combat', None)
        from .battle_item_effects import refresh_sight
        effects=() if combat is None else refresh_sight(combat)
        restores = () if combat is None else combat.cancel_equipment_batch(owner)
        if not restores and not effects:
            return result
        replies = (result,) if isinstance(result, bytes) else tuple(result or ())
        return (*restores, *replies,*effects)
    return wrapped
