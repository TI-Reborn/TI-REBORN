"""Native C2S92 customization; catalog and credit prices from the client XML."""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
import sqlite3
from xml.etree import ElementTree

from .protocol.binary import Reader, Writer, PacketError
from .protocol.pet_info import decode_pet_info, encode_pet_info
from .protocol.system_message import encode_shop_error
from .protocol.asset_count import encode_asset_count
from .wallets import WalletStore

# Wire order in 6d0268 / 6d01f8 differs from the model's word order.
FIELDS = ('0x6d0213','0x6d0221','0x6d022e','0x6d023c','0x6d024a','0x6d0258')
TYPES = ('HeadModel','HeadHairType','FacialHairType','HairColor','BodyModel','LegsModel')
CATALOG = Path(__file__).resolve().parents[1]/'evidence/customization_diagnostic.xml'


@lru_cache(maxsize=1)
def catalog():
    return {(group.attrib['type'], int(ver.attrib['id']), int(resource)): int(ver.attrib['price'])
            for group in ElementTree.parse(CATALOG).getroot() for ver in group
            for resource in ver.text.split()}


def appearance_bytes(pet):
    return bytes(pet.fields.get(key,0) for key in FIELDS)


def with_appearance(pet, values):
    if len(values)!=6:raise PacketError('Expected six appearance bytes')
    return replace(pet,fields={**pet.fields,'0x6d0203':1,**dict(zip(FIELDS,values))})


def starter(pet, resource):
    # Initial look is free; subsequent changes use native displayed credit prices.
    pet=replace(pet,fields={**pet.fields,'0x8c446f':resource})
    return with_appearance(pet,bytes((resource,0 if resource==1 else 8,0,1,0,0)))


def decode_request(packet):
    r=Reader(packet)
    if r.u8()!=0x92:raise PacketError('Expected customization92')
    owner=r.u32();values=r.read(6);r.finish()
    return owner,values


def encode_request(owner,values):
    w=Writer().u8(0x92).u32(owner);w.data.extend(values)
    result=w.build();decode_request(result);return result


def change(path,account,packet,*,allowed=True,finish_creation=False):
    """Validate ownership/options and debit changed components in one transaction."""
    owner,values=decode_request(packet)
    try:
        with closing(connect(path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',
                           (account,owner)).fetchone()
            if not row:raise ValueError('Боец не принадлежит вашему отряду')
            if finish_creation and owner!=1:raise ValueError('Выберите создаваемого персонажа')
            human,raw=row
            pet=decode_pet_info(bytes(raw),human_equipment=bool(human))
            resource=pet.fields['0x8c446f']
            if not allowed:raise ValueError('Изменение внешности доступно в городе вне очереди и боя')
            if not human or resource not in (1,2):raise ValueError('Внешность этого бойца не редактируется')
            before=appearance_bytes(pet)
            # 6d1d04 leaves the final two stack words uninitialized when the
            # original catalog has no BodyModel/LegsModel entries. Preserve
            # these unavailable components instead of accepting stack garbage.
            values=bytearray(values)
            for index in (4,5):
                if not any(kind==TYPES[index] and model==resource for kind,_,model in catalog()):
                    values[index]=before[index]
            values=bytes(values)
            cost=0
            for kind,old,new in zip(TYPES,before,values):
                # Native UI has no head selector, nor body/legs entries in this
                # original catalog. Allow keeping defaults, never arbitrary IDs.
                if old==new:continue
                price=catalog().get((kind,new,resource))
                if price is None:raise ValueError('Недоступный вариант внешности')
                cost+=price
            if finish_creation:
                cost=0
            if values!=before:
                if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',
                              (cost,account,cost)).rowcount!=1:
                    raise ValueError('Недостаточно кредитов для изменения внешности')
                changed=encode_pet_info(with_appearance(pet,values))
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',
                           (changed,account,owner))
            else:changed=bytes(raw)
            if finish_creation:
                if db.execute('UPDATE character_onboarding SET completed=1 WHERE account=? AND completed=0',(account,)).rowcount!=1:
                    raise ValueError('Создание персонажа уже завершено')
        # 66 refreshes the native model; F0/138 is the original haircut message.
        from .owned_pets import OwnedPetStore
        changed=next(pet for pet_id,pet,_ in OwnedPetStore(path).list(account) if pet_id==owner)
        return (changed,encode_asset_count(WalletStore(path).ensure(account)),
                Writer().u8(0xf0).u32(138).u32(0).build())
    except ValueError as error:
        # Undo native preview even on rejection; do not leave an unpaid look.
        with closing(connect(path)) as db:
            row=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        if row:
            from .owned_pets import OwnedPetStore
            restored=next(pet for pet_id,pet,_ in OwnedPetStore(path).list(account) if pet_id==owner)
        return (*((restored,) if row else ()),encode_shop_error(str(error)))
