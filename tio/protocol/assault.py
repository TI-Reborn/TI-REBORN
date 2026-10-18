"""Assault4 room ABI, original Silver 63916c..63b690.

This module deliberately excludes the incompatible classic assault side API.
Native room capacity is configurable through C8/37, not a protocol constant.
"""
from dataclasses import dataclass
import math
import struct
from .binary import Reader, Writer, PacketError

CREATE_ROOM, JOIN_ROOM, REQUEST_ROOMS = 0x1d, 0x1e, 0x1f
SELECT_PET, SET_READY, START_ROOM, DISBAND_ROOM = 0x20, 0x21, 0x22, 0x23
# Original957b44 selects game_Assault_v4's78d404 HUD only for this mode.
BATTLE_MODE = 21


def _cstring(w, value):
    if not isinstance(value, bytes) or b'\0' in value or len(value) > 255:
        raise PacketError('Expected bounded encoded string')
    # Saved character/clan names use the legacy CP1251 representation. The
    # generated Assault4 reader6297ac/writer629abc use u16 byte length + UTF8,
    # unlike the handwritten CString readers used by older lobby packets.
    try:raw=value.decode('cp1251').encode('utf-8')
    except UnicodeError:raise PacketError('Invalid legacy character name') from None
    w.u16(len(raw));w.data.extend(raw)


def decode_request(data: bytes):
    r = Reader(data)
    if r.u8() != 0xc8:
        raise PacketError('Expected Assault4 C8 request')
    operation = r.u8()
    if operation not in range(CREATE_ROOM, DISBAND_ROOM + 1):
        raise PacketError('Unsupported Assault4 room operation')
    value = None
    if operation in (JOIN_ROOM, SELECT_PET):
        value = r.u32()
    elif operation == SET_READY:
        value = r.u8()
        if value not in (0, 1):
            raise PacketError('Expected readiness boolean')
    r.finish()
    return operation, value


def encode_request(operation, value=None):
    w = Writer().u8(0xc8).u8(operation)
    if operation in (JOIN_ROOM, SELECT_PET):
        w.u32(value)
    elif operation == SET_READY:
        w.u8(value)
    elif value is not None:
        raise PacketError('Unexpected Assault4 request value')
    result = w.build()
    decode_request(result)
    return result


@dataclass(frozen=True)
class RoomPet:
    level: int
    npc_id: int
    avatar_id: int
    name: bytes
    max_hp: int
    armor: int
    soldier_rank: int
    military_rank: int
    equip_status: int


@dataclass(frozen=True)
class RoomCell:
    player_id: int
    name: bytes
    level: int
    crest: int
    creator: int
    pets: tuple[RoomPet, ...]
    ready: int


@dataclass(frozen=True)
class RoomListItem:
    id: int
    creator: bytes
    clan_crest: int | None
    alliance_crest: int | None
    max_players: int
    players: int
    ready: int


def _bool(w, value):
    if type(value) is not int or value not in (0, 1):
        raise PacketError('Expected boolean byte')
    return w.u8(value)


def encode_room_info(room_id, cells, ready):
    cells = tuple(cells)
    w = Writer().u8(0xc8).u8(0x24).u32(room_id).u32(len(cells))
    for cell in cells:
        w.u32(cell.player_id)
        _cstring(w, cell.name)
        w.u8(cell.level).u32(cell.crest)
        _bool(w, cell.creator)
        w.u32(len(cell.pets))
        for pet in cell.pets:
            w.u8(pet.level).u32(pet.npc_id).u32(pet.avatar_id)
            _cstring(w, pet.name)
            for value in (pet.max_hp, pet.armor, pet.soldier_rank, pet.military_rank, pet.equip_status):
                w.u32(value)
        _bool(w, cell.ready)
    _bool(w, ready)
    return w.build()


def encode_room_deleted(room_id):
    return Writer().u8(0xc8).u8(0x25).u32(room_id).build()


def encode_room_list(rows, *, update=False):
    rows = tuple(rows)
    w = Writer().u8(0xc8).u8(0x27 if update else 0x26).u32(len(rows))
    for row in rows:
        w.u32(row.id)
        _cstring(w, row.creator)
        for crest in (row.clan_crest, row.alliance_crest):
            w.u8(int(crest is not None))
            if crest is not None:
                w.u32(crest)
        w.u8(row.max_players).u8(row.players)
        _bool(w, row.ready)
    return w.build()


def encode_room_list_deleted(ids):
    ids = tuple(ids)
    w = Writer().u8(0xc8).u8(0x28).u32(len(ids))
    for identity in ids:
        w.u32(identity)
    return w.build()


def _float(w, value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise PacketError('Expected finite native float')
    try:
        w.data.extend(struct.pack('<f', value))
    except (OverflowError, struct.error):
        raise PacketError('Native float out of range') from None
    return w


@dataclass(frozen=True)
class FlagPoints:
    team_id: int
    value: int
    last_increment: int


def encode_flag_status(x, y, team_id):
    """C8/2E: original64ba14, TANetPoint then owner team u32."""
    w = Writer().u8(0xc8).u8(0x2e)
    return _float(_float(w, x), y).u32(team_id).build()


def encode_flag_points(rows):
    """C8/2F: original64be30/64bb50; RTTI61be48 field names."""
    rows = tuple(rows)
    w = Writer().u8(0xc8).u8(0x2f).u32(len(rows))
    for row in rows:
        w.u32(row.team_id).u32(row.value).u32(row.last_increment)
    return w.build()


def encode_flag_increment(x, y, increment, team_id):
    """C8/31: 64c118; 794090 consumes increment first, team second."""
    w = Writer().u8(0xc8).u8(0x31)
    return _float(_float(w, x), y).u32(increment).u32(team_id).build()


def encode_battle_count(total, completed):
    """C8/38: original657da0, consumer793fb0 stores total-completed."""
    return Writer().u8(0xc8).u8(0x38).u32(total).u32(completed).build()


@dataclass(frozen=True)
class ClanOwner:
    id: int
    name: bytes
    leader: bytes
    crest_id: int


@dataclass(frozen=True)
class ZoneInfo:
    phase: int
    current_utc: int
    start_utc: int | None
    end_utc: int
    min_level: int
    max_level: int
    next_min_level: int
    next_max_level: int
    drag_in_max_enhance: int
    next_start_utc: int | None = None
    last_clan_owner: ClanOwner | None = None


def encode_zone_body(zone):
    """TownInfo C8/2D seventh optional branch; original649a44/649b34.

    Phase enum60688a: 0WAIT,1REGISTRATION,2TOUR1,3TOUR2_PAUSE,
    4TOUR2,5TOUR3_PAUSE,6TOUR3. This is a body, without C8/2D.
    """
    if type(zone.phase) is not int or not 0 <= zone.phase <= 6:
        raise PacketError('Unsupported Assault4 phase')
    w = Writer().u32(zone.phase).u32(zone.current_utc)
    w.u8(int(zone.start_utc is not None))
    if zone.start_utc is not None:
        w.u32(zone.start_utc)
    w.u32(zone.end_utc)
    for value in (zone.min_level, zone.max_level, zone.next_min_level,
                  zone.next_max_level, zone.drag_in_max_enhance):
        w.u8(value)
    w.u8(int(zone.next_start_utc is not None))
    if zone.next_start_utc is not None:
        w.u32(zone.next_start_utc)
    w.u8(int(zone.last_clan_owner is not None))
    if zone.last_clan_owner is not None:
        owner = zone.last_clan_owner
        w.u32(owner.id)
        _cstring(w, owner.name)
        _cstring(w, owner.leader)
        w.u32(owner.crest_id)
    return w.build()


@dataclass(frozen=True)
class PlayerResult:
    name: bytes
    kills: int
    deaths: int
    assault_points: float


@dataclass(frozen=True)
class ClanResult:
    name: bytes
    clan_crest_id: int
    alliance_crest_id: int
    assault_points: float


@dataclass(frozen=True)
class TeamResult:
    result: int
    flag_points: int
    assault_points: float
    players: tuple[PlayerResult, ...] = ()
    clans: tuple[ClanResult, ...] = ()


def _team_result(w, row):
    if type(row.result) is not int or not 0 <= row.result <= 3:
        raise PacketError('Expected native result enum')
    # Original64f3bc reads result as u32, then casts to enum byte.
    w.u32(row.result).u32(row.flag_points)
    _float(w, row.assault_points)
    w.u32(len(row.players))
    for player in row.players:
        _cstring(w, player.name)
        w.u32(player.kills).u32(player.deaths)
        _float(w, player.assault_points)
    w.u32(len(row.clans))
    for clan in row.clans:
        _cstring(w, clan.name)
        w.u32(clan.clan_crest_id).u32(clan.alliance_crest_id)
        _float(w, clan.assault_points)


def encode_battle_over(town_zone_id, self_team, other_team):
    """C8/32 original64fb88/64fbbc, with two team results64f3bc."""
    w = Writer().u8(0xc8).u8(0x32).u32(town_zone_id)
    _team_result(w, self_team)
    _team_result(w, other_team)
    return w.build()
