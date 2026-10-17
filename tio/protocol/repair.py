"""Native repair writers 9905FC (7E) and 99F218 (C2/03)."""
from .binary import Reader,Writer,PacketError


def decode_repair(packet):
    r=Reader(packet)
    opcode=r.u8()
    if opcode==0xc2:
        if r.u8()!=3:raise PacketError('Expected C2/03 repair')
    elif opcode!=0x7e:raise PacketError('Expected 7E repair')
    owner,target=r.u32(),r.u32();r.finish()
    if not owner or not target:raise PacketError('Invalid repair identity')
    return owner,target


def repair_message(command):
    if command not in (110,112):raise PacketError('Unknown repair message')
    return Writer().u8(0xf0).u32(command).u32(0).build()
