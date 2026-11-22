"""Free portraits using the native AC catalog and durable FC assignment."""
import json,struct
from pathlib import Path
from functools import lru_cache
from contextlib import closing
from typing import TYPE_CHECKING
from .db_transaction import connect,transaction
from .protocol.binary import Reader,Writer,PacketError

ROOT=Path(__file__).resolve().parents[1]

if TYPE_CHECKING:
    from .battle_state import BattleField


@lru_cache(maxsize=1)
def catalog():
    data=json.loads((ROOT/'config/avatars.json').read_text(encoding='utf-8'))
    assert data['version']==1 and data['price']==0
    return {row['id']:row for row in data['avatars']}


def ensure(db):
    db.execute('CREATE TABLE IF NOT EXISTS pet_avatars(account TEXT NOT NULL,pet_id INTEGER NOT NULL,avatar_id INTEGER NOT NULL,PRIMARY KEY(account,pet_id))')


def selections(path,account):
    with closing(connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='pet_avatars'").fetchone():return {}
        return dict(db.execute('SELECT pet_id,avatar_id FROM pet_avatars WHERE account=?',(account,)))


def project_city_pet(path: str | Path, account: str, packet: bytes) -> bytes:
    """Keep the selected portrait in native66 without changing saved pet data."""
    from .protocol.pet_info import decode_pet_info, encode_pet_info

    owner = int.from_bytes(packet[1:5], 'little')
    with closing(connect(path)) as db:
        row = db.execute('SELECT human FROM owned_pets WHERE account=? AND pet_id=?',
                         (account, owner)).fetchone()
    if row is None:
        return packet
    avatar = selections(path, account).get(owner, 0)
    pet = decode_pet_info(packet, human_equipment=bool(row[0]))
    if pet.fields['0x8c4ba9'] == avatar:
        return packet
    pet.fields['0x8c4ba9'] = avatar
    return encode_pet_info(pet)


def assign(path,account,pet_id,avatar_id,*,allowed):
    if type(pet_id) is not int or pet_id<=0 or type(avatar_id) is not int or avatar_id not in (0,*catalog()):
        raise ValueError('Недоступный аватар')
    from .services_completion import ServicesCompletion
    with transaction(path) as db:
        ServicesCompletion._gate(db,account,allowed)
        row,pet=ServicesCompletion._pet(db,account,pet_id)
        if pet.fields['0x8c446f'] not in (1,2,3,4,5,6):raise ValueError('Аватар недоступен для этого типа бойца')
        ensure(db)
        db.execute('INSERT INTO pet_avatars VALUES (?,?,?) ON CONFLICT(account,pet_id) DO UPDATE SET avatar_id=excluded.avatar_id',(account,pet_id,avatar_id))


def encode_catalog():
    # Original 6ac038 reads signed count, premium category, ID, price, CRC32.
    # 6aff04 routes category0 to the ordinary list, category1 to premium.
    w=Writer().u8(0xac).u8(8).u32(len(catalog()))
    for identity,row in catalog().items():w.u8(int(row.get('premium',True))).u32(identity).u32(0).u32(row['crc32'])
    return w.build()


def encode_assignments(rows):
    rows=tuple(rows)
    if len(rows)>31 or len({r[0] for r in rows})!=len(rows):raise PacketError('Invalid avatar assignments')
    w=Writer().u8(0xfc).u8(1).u16(len(rows))
    for pet,avatar in rows:
        if type(pet) is not int or pet<=0 or type(avatar) is not int or avatar not in (0,*catalog()):raise PacketError('Invalid avatar assignment')
        w.u32(pet).u32(avatar)
    return w.build()


def snapshot(path,account):
    selected=selections(path,account)
    with closing(connect(path)) as db:
        return encode_assignments((pet,selected.get(pet,0)) for pet, in db.execute('SELECT pet_id FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)))


# Native RECV_BattleSoldierAdd 8c5044 copies this BattleSoldier field into
# model+60DC, the same portrait slot FC assigns.
SOLDIER_AVATAR = '0x8c581d'


def soldier_avatar(field: 'BattleField', actor_id: int, fields: dict, *, hidden: bool = False) -> dict:
    """Return 3B fields carrying the scene avatar; a hidden model discloses none."""
    if SOLDIER_AVATAR not in fields or not hasattr(field, 'avatar_ids'):
        return fields
    return {**fields, SOLDIER_AVATAR: 0 if hidden else field.avatar_ids.get(actor_id, 0)}


def battle_assignments(field: 'BattleField', owner: int) -> tuple[bytes, ...]:
    """Use scene actor IDs and disclose only this recipient's visible actors."""
    if not hasattr(field, 'avatar_ids'):
        return ()
    from .visibility import visible_actors
    return (encode_assignments((i, field.avatar_ids.get(i, 0))
                               for i in sorted(visible_actors(field, owner))[:31]),)


def image_packet(identity):
    row=catalog().get(identity)
    if row is None:raise ValueError('Аватар не найден')
    import base64
    raw=base64.b64decode(row['jpeg_b64'],validate=True)
    import zlib
    if len(raw)>4096 or zlib.crc32(raw)!=row['crc32']:raise ValueError('Повреждённый ресурс аватара')
    return b'\xac\x06'+struct.pack('<IH',identity,len(raw))+raw


def request(path,account,packet,*,allowed):
    r=Reader(packet)
    if r.u8()!=0xac:raise PacketError('Expected avatar request')
    action=r.u8()
    if action in (1,2,4):
        identity=r.u32();r.finish()
        if action==2:return (image_packet(identity),)
        if action==4 and identity not in catalog():raise ValueError('Аватар не найден')
        return (encode_catalog(),snapshot(path,account))
    if action==5:
        pet,avatar=r.u32(),r.u32();r.finish();assign(path,account,pet,avatar,allowed=allowed)
        return (snapshot(path,account),)
    raise ValueError('Загрузка и редактирование аватаров не поддерживаются')
