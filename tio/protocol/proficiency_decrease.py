"""Original GUI decrease routes through chat21's /decreaseability command.

Original UI9B8554/9AB108 passes mercenary NAME, not actor ID, to9FF3E4.
There is no invented numeric decrease opcode. Ambiguous names are rejected
by the authoritative store rather than selecting another owned mercenary.
"""
from dataclasses import dataclass
from .chat import decode_send
from .binary import PacketError

SKILLS={'melee':0,'light':1,'heavy':2,'distance':3,'automatic':4,'throwing':5,'mines':7}


@dataclass(frozen=True)
class ProficiencyDecrease:
    mercenary_name:str
    skill:str


def parse_command(text):
    if not isinstance(text,str) or len(text)>200 or any(ord(c)<32 for c in text):
        raise PacketError('Invalid decrease command')
    prefix,separator,rest=text.partition(' ')
    if prefix.casefold()!='/decreaseability' or not separator:
        raise PacketError('Expected /decreaseability name skill')
    name,separator,skill=rest.strip().rpartition(' ')
    skill=skill.casefold()
    if not separator or not name.strip() or skill not in SKILLS:
        raise PacketError('Unknown mercenary or weapon skill')
    return ProficiencyDecrease(name.strip(),skill)


def decode_proficiency_decrease(packet):
    channel,text,recipient=decode_send(packet)
    if channel!=0 or recipient:raise PacketError('Decrease command requires native channel0')
    return parse_command(text)


def encode_proficiency_decrease(request):
    text=f'/decreaseability {request.mercenary_name} {request.skill}'
    parse_command(text)
    return b'\x21\0'+text.encode('utf-16-le')+b'\0\0'
