"""68 request (96d568), A7/00 reader (96d7d0), original silver.dll.

League indices are reversed: lg03=bronze, lg00=platinum.
The two 605dc4 calls read u64s; the UI displays the low dword/word.
"""
import struct
from urllib.parse import urlsplit
from .binary import Reader,Writer,PacketError
from .clans import put_string
from .alliances import AllianceInfo


# A7/03 carries eight little-endian u32 counts for places 1 through 8.
EMPTY_TOURNAMENT_STATISTICS = b'\xa7\x03' + bytes(8 * 4)


def encode_tournament_statistics(places: tuple[int, ...]) -> bytes:
    if len(places) != 8:
        raise PacketError('Expected eight tournament placements')
    writer = Writer().u8(0xa7).u8(3)
    for count in places:
        writer.u32(count)
    return writer.build()


def _name(r: Reader, maximum: int) -> bytes:
    end = r.data.find(b'\0', r.offset, r.offset + maximum + 1)
    if end <= r.offset:
        raise PacketError('Некорректное имя для карточки')
    name = r.read(end - r.offset)
    r.read(1)
    return name


def decode_view_request(packet: bytes) -> tuple[int, bytes]:
    r=Reader(packet)
    if r.u8()!=0x68:raise PacketError('Expected profile request')
    kind = r.u8()
    if kind not in (0, 1, 2):
        raise PacketError('Неизвестный раздел карточки')
    name = _name(r, 16 if kind == 0 else 32)
    r.finish()
    if kind == 0 and not name.isalnum():
        raise PacketError('Некорректное имя персонажа')
    return kind, name


def decode_request(packet: bytes) -> bytes:
    kind, name = decode_view_request(packet)
    if kind != 0:
        raise PacketError('Only character profiles are supported')
    return name


def _text(r: Reader, limit: int) -> str:
    value = bytearray()
    while (word := r.read(2)) != b'\0\0':
        if len(value) == 2 * limit:
            raise PacketError('Поле карточки слишком длинное')
        value.extend(word)
    try:
        text = value.decode('utf-16-le')
    except UnicodeError as exc:
        raise PacketError('Некорректный текст карточки') from exc
    if any(ord(c) < 32 and c not in '\r\n\t' or 127 <= ord(c) <= 159 for c in text):
        raise PacketError('Текст карточки содержит недопустимые символы')
    return text


def decode_edit_request(packet: bytes) -> tuple[str, str, str]:
    r = Reader(packet)
    if r.read(2) != b'\x51\0':
        raise PacketError('Неизвестный редактор карточки')
    biography, website, contact = _text(r, 512), _text(r, 255), _text(r, 128)
    r.finish()
    if website:
        try:
            address = urlsplit(website)
        except ValueError as exc:
            raise PacketError('Некорректный адрес сайта') from exc
        if (address.scheme not in ('http', 'https') or not address.hostname or
                address.username is not None or '\\' in website or any(c.isspace() for c in website)):
            raise PacketError('Укажите адрес сайта с http:// или https://')
    return biography, website, contact


def _write_text(w: Writer, *texts: str) -> None:
    for text in texts:
        if '\0' in text:
            raise PacketError('Invalid profile text')
        w.data.extend(text.encode('utf-16-le') + b'\0\0')


def decode_jail_request(packet: bytes) -> bytes:
    r = Reader(packet)
    if r.read(2) != b'\xab\1':
        raise PacketError('Неизвестный запрос о заключённом')
    name = _name(r, 16)
    if not name.isalnum() or r.u32() != 0:
        raise PacketError('Некорректный запрос о заключённом')
    r.finish()
    return name


def encode_jail_info(name: bytes, remaining: int) -> bytes:
    w = put_string(Writer().u8(0xab).u8(2), name)
    # The world sentence clock runs at real online seconds, with no multipliers.
    w.data.extend(struct.pack('<fI', 1.0, remaining))
    _write_text(w, '')
    w.data.extend(struct.pack('<fI', 1.0, remaining))
    return w.build()


def encode_clan_profile(clan: dict, members: tuple[dict, ...], alliance: dict | None,
                        place: int, ranked_place: int, skill: int) -> bytes:
    """A7/01, Silver 96EE62. The alliance block is conditional on its ID."""
    w = Writer().u8(0xa7).u8(1).u32(clan['id'])
    put_string(w, clan['name']).u8(clan['level']).u32(clan['crest_id']).u32(clan['influence'])
    w.u32(alliance['id'] if alliance else 0)
    if alliance:
        put_string(w, alliance['name']).u8(alliance['level']).u32(alliance['crest_id'])
    w.u32(place).u32(ranked_place).u32(0).u32(0)
    _write_text(w, '', '', '')
    w.u8(len(members))
    for member in members:
        put_string(w, member['name']).u8(member['level']).u8(int(member['leader']))
        w.u32(0).u8(int(member['online']))
    return w.u32(skill).build()


def encode_alliance_profile(alliance: AllianceInfo, place: int) -> bytes:
    """A7/02, Silver 96F8BC. A7 lists clans and their leaders, not member rows."""
    leading = next(clan for clan in alliance.clans if clan.id == alliance.leading_clan)
    w = Writer().u8(0xa7).u8(2).u32(alliance.id).u32(alliance.crest_id)
    put_string(w, alliance.name).u8(alliance.level).u32(alliance.influence)
    put_string(w, leading.name).u8(leading.level).u32(leading.crest_id)
    w.u8(0).u8(0).u32(place).u32(0)
    _write_text(w, '', '', '')
    w.u32(0).u8(len(alliance.clans))
    for clan in alliance.clans:
        w.u32(clan.id)
        put_string(w, clan.name).u8(clan.level).u32(clan.crest_id).u32(clan.influence)
        leader_level = next((member.level for member in clan.members if member.name == clan.leader), 0)
        put_string(w, clan.leader).u8(leader_level).u8(len(clan.members)).u8(0).u32(0)
    return w.u32(0).build()


def encode_profile(identity,name,level,biography,*,online=True,in_battle=False,
                   rating=0,wins=0,losses=0,kills=0,deaths=0,damage_dealt=0,damage_received=0,
                   online_hours=0,squad_rank=0,squad_icon=0,mercenaries=(),
                   skill=0,league=3,place=0,streak=0,contact='',website='',clan_name=b'',clan_crest_id=0,
                   alliance_name=b'',alliance_crest_id=0, avatar_id: int = 0, town: int = 0,
                   jailed: bool = False, assault_place: int = 0, assault_bonus: int = 0):
    if not name or len(name)>16 or not name.isalnum():raise PacketError('Invalid name')
    w=Writer().u8(0xa7).u8(0).u32(identity)
    w.data.extend(name+b'\0');w.u8(level).u32(avatar_id)
    # Original96d958/96d965 call68a094(id,0/1). These are crest IDs,
    # not persistent clan/alliance entity identifiers.
    if not isinstance(clan_name,bytes) or len(clan_name)>32 or b'\0' in clan_name:raise PacketError('Invalid clan name')
    if not isinstance(alliance_name,bytes) or len(alliance_name)>32 or b'\0' in alliance_name:raise PacketError('Invalid alliance name')
    w.data.extend(clan_name+b'\0');w.u32(clan_crest_id);w.data.extend(alliance_name+b'\0');w.u32(alliance_crest_id)
    w.u8(int(in_battle)).u8(town)
    for v in (0,online_hours,rating,wins,losses,kills,deaths,damage_dealt,damage_received,squad_icon,squad_rank):
        if type(v) is not int or not -(1<<31)<=v<(1<<32):raise PacketError('Invalid profile statistic')
        w.u32(v&0xffffffff)
    _write_text(w, biography, website, contact)
    mercenaries=tuple(mercenaries)
    if len(mercenaries)>20:raise PacketError('Too many profile soldiers')
    w.u8(len(mercenaries))
    for nick,lvl,xp,rank in mercenaries:
        if not nick or b'\0' in nick or len(nick)>64:raise PacketError('Invalid soldier name')
        w.data.extend(nick+b'\0');w.u8(lvl).u32(0).u32(xp).u32(0).u32(rank).u32(0).u32(0)
    w.u8(int(jailed)).u32(assault_place).u32(assault_bonus).u32(0).u8(0).u8(int(online))
    if league not in (0,1,2,3):raise PacketError('Invalid league')
    w.u32(skill).u32(league)
    w.data.extend(struct.pack('<QQ',place,streak));w.u8(0)
    return w.build()
