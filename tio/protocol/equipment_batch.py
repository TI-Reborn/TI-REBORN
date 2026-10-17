"""TIO emulator extension F6/v1; this is not an original game opcode.

Original action33 remains unchanged. The released client extension sends only
battle weapon/armor actions here; native medical/city actions keep their ABI.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError, uint
from .item_action import ItemAction

OPCODE = 0xf6
VERSION = 1
STAGE, COMMIT, CANCEL = 0, 1, 2


@dataclass(frozen=True)
class EquipmentBatchRequest:
    operation: int
    batch_id: int
    action: ItemAction | None = None


def encode_equipment_batch(request):
    if request.operation not in (STAGE, COMMIT, CANCEL):
        raise PacketError('Unknown equipment batch operation')
    if not uint(request.batch_id, 32):raise PacketError('Equipment batch ID required')
    w = Writer().u8(OPCODE).u8(VERSION).u8(request.operation).u32(request.batch_id)
    if request.operation == STAGE:
        if not isinstance(request.action, ItemAction):raise PacketError('Equipment stage action required')
        action = request.action
        if not uint(action.pet_id, 32) or not uint(action.instance_id, 32):
            raise PacketError('Equipment actor and item required')
        action.target_mask  # Reject unrecognized explicit targets.
        w.u32(action.pet_id).u32(action.instance_id).u8(action.option)
    elif request.action is not None:
        raise PacketError('Unexpected equipment confirmation action')
    return w.build()


def decode_equipment_batch(packet):
    r = Reader(packet)
    if r.u8() != OPCODE or r.u8() != VERSION:raise PacketError('Expected emulator equipment batch F6/v1')
    operation, batch_id = r.u8(), r.u32()
    if operation not in (STAGE, COMMIT, CANCEL) or not batch_id:
        raise PacketError('Invalid equipment batch request')
    action = ItemAction(r.u32(), r.u32(), r.u8()) if operation == STAGE else None
    r.finish()
    request = EquipmentBatchRequest(operation, batch_id, action)
    encode_equipment_batch(request)
    return request
