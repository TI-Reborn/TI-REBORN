"""Original native mine UI: C8/3D deployment and C8/3F acknowledgement.

95b943 reads the selected TSItem instance at ad05f8+28, then9595f0 writes
actor/instance/x/y.658e70 reads actor/x/y/template/state;95c0e4 branches
on state1 (deployed),3 (removed),4 (failure). No new packet numbers.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError


@dataclass(frozen=True)
class MineDeploy:
    actor_id: int
    instance_id: int
    x: int
    y: int


@dataclass(frozen=True)
class MineDeployed:
    actor_id: int
    x: int
    y: int
    template_id: int
    state: int = 1


def encode_mine_deploy(value):
    return Writer().u8(0xc8).u8(0x3d).u32(value.actor_id).u32(value.instance_id).u32(value.x).u32(value.y).build()


def decode_mine_deploy(packet):
    r=Reader(packet)
    if (r.u8(),r.u8())!=(0xc8,0x3d):raise PacketError('Expected mine deployment C8/3D')
    value=MineDeploy(r.u32(),r.u32(),r.u32(),r.u32());r.finish();return value


def encode_mine_deployed(value):
    if not 0<=value.state<=255:raise PacketError('Mine state exceeds native byte')
    return Writer().u8(0xc8).u8(0x3f).u32(value.actor_id).u32(value.x).u32(value.y).u32(value.template_id).u32(value.state).build()


def decode_mine_deployed(packet):
    r=Reader(packet)
    if (r.u8(),r.u8())!=(0xc8,0x3f):raise PacketError('Expected mine deployment result C8/3F')
    value=MineDeployed(r.u32(),r.u32(),r.u32(),r.u32(),r.u32())
    if value.state>255:raise PacketError('Mine state exceeds native byte')
    r.finish();return value
