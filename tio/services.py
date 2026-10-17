"""Original B1 services; permanent personal upgrades confirmed by the manual.

services.cfg confirms IDs/powers; current silver.dll reads services.xml.
Clan services and services without recovered prices are not offered.
"""

from .db_transaction import connect
from contextlib import closing
import sqlite3
from .protocol.binary import Reader,Writer,PacketError
from .protocol.city_catalogs import ServiceOffer,ServiceOption,encode_service_shop

from .roster_progression import roster_expansion
OFFERS={1:((8,5000),(16,15000)),2:roster_expansion()}


def level(db,account,service):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='paid_services'").fetchone():return 0
    row=db.execute('SELECT level FROM paid_services WHERE account=? AND service=?',(account,service)).fetchone()
    return row[0] if row else 0


def power(db,account,service):
    value=level(db,account,service)
    return OFFERS[service][value-1][0] if value else 0


def shared_xml():
    from xml.etree.ElementTree import Element,SubElement,tostring
    root=Element('services')
    for identity,options in OFFERS.items():
        node=SubElement(root,'service',id=str(identity),name=f'se{identity:02}',target='self',expireType='never',canSellBack='false')
        for number,(value,_) in enumerate(options,1):SubElement(node,'level',val=str(number),power=str(value))
    return tostring(root,encoding='utf-8',xml_declaration=True)


def status(service,level,target=1):
    # B1/01: action=0 add/update, service ID, recipient, level, expiry u64.
    w=Writer().u8(0xb1).u8(1).u8(0).u32(service).u32(target).u8(level)
    w.data.extend(bytes(8));return w.build()


def snapshots(path,account):
    with closing(connect(path)) as db:
        return tuple(status(i,n) for i in OFFERS if (n:=level(db,account,i)))


def catalog(path,account):
    with closing(connect(path)) as db:
        offers=[]
        for identity,options in OFFERS.items():
            owned=level(db,account,identity)
            if owned<len(options):
                # Only next level: no downgrade, duplicate charge or skipped prerequisite.
                offers.append(ServiceOffer(identity,0,(ServiceOption(owned+1,0,options[owned][1]),)))
        return encode_service_shop(tuple(offers))


def purchase(path,account,packet):
    r=Reader(packet)
    if (r.u8(),r.u8())!=(0xb1,4):raise PacketError('Expected B1/04')
    action,service,wanted,target=r.u8(),r.u32(),r.u8(),r.u32();r.finish()
    if action!=0 or service not in OFFERS or target!=1 or wanted<1:raise ValueError('Недоступный сервис или получатель')
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS paid_services(account TEXT NOT NULL,service INTEGER NOT NULL,level INTEGER NOT NULL,PRIMARY KEY(account,service))')
        owned=level(db,account,service)
        if wanted!=owned:  # An identical retried purchase is free and idempotent.
            if wanted!=owned+1 or wanted>len(OFFERS[service]):raise ValueError('Сначала оплатите предыдущий уровень сервиса')
            cost=OFFERS[service][wanted-1][1]
            if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',(cost,account,cost)).rowcount!=1:raise ValueError('Недостаточно кредитов')
            db.execute('INSERT INTO paid_services VALUES (?,?,?) ON CONFLICT(account,service) DO UPDATE SET level=excluded.level',(account,service,wanted))
    from .wallets import WalletStore
    from .protocol.asset_count import encode_asset_count
    return (status(service,wanted),encode_asset_count(WalletStore(path).ensure(account)),catalog(path,account))
