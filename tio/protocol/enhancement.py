"""C8/2A item enhancement, original builder99f25c / writer6419a8."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class EnhancementRequest:
    instance_id: int
    kit_id: int | None


def decode_enhancement_request(packet):
    r = Reader(packet)
    if r.read(2) != b'\xc8\x2a':
        raise PacketError('Expected enhancement C8/2A')
    target, present = r.u32(), r.u8()
    if present not in (0, 1):
        raise PacketError('Noncanonical kit flag')
    kit = r.u32() if present else None
    r.finish()
    if not target or kit == 0:
        raise PacketError('Invalid enhancement item ID')
    return EnhancementRequest(target, kit)


def encode_enhancement_result(outcome, template_id, level):
    """151/152 resolve arg0 through a75f24; SE failure157 has no arguments."""
    command = {'success': 151, 'destroyed': 152, 'reset': 157, 'weakened': 157}[outcome]
    w = Writer().u8(0xf0).u32(command).u32(0 if outcome in ('reset','weakened') else 2)
    if outcome not in ('reset','weakened'):
        w.u32(1).u32(template_id).u32(1).u32(level)
    return w.build()
