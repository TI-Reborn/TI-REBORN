"""Original C8/3A subscription purchase, C8/39 status, account-bound benefits."""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import time
from .protocol.binary import Reader,Writer,PacketError

POLICY=json.loads((Path(__file__).resolve().parents[1]/'config/premium.json').read_text())
OFFERS={i:(24 if i%2 else POLICY['month_days']*24,
           POLICY['daily_gold'] if i%2 else POLICY['monthly_gold']) for i in range(1,5)}
if any(type(v) is not int or v<=0 for v in POLICY.values() if not isinstance(v,str)):
    raise ValueError('Invalid premium policy')


def state(db,account,now=None):
    stamp=int(time.time() if now is None else now)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='premium_accounts'").fetchone():return 0,0
    row=db.execute('SELECT kind,expires FROM premium_accounts WHERE account=?',(account,)).fetchone()
    return (row[0],row[1]-stamp) if row and row[1]>stamp else (0,0)


def current(path,account,now=None):
    with closing(connect(path)) as db:return state(db,account,now)


def project(db,account,assets,now=None):
    kind,remaining=state(db,account,now)
    return replace(assets,optional_raw=(remaining,kind) if kind else None)


def project_packet(path,account,packet):
    from .protocol.asset_count import decode_asset_count,encode_asset_count
    with closing(connect(path)) as db:
        return encode_asset_count(project(db,account,decode_asset_count(packet)))


def decode_purchase(packet):
    r=Reader(packet)
    if (r.u8(),r.u8())!=(0xc8,0x3a):raise PacketError('Expected premium C8/3A')
    offer,quote=r.u32(),r.u32();r.finish()
    if offer not in OFFERS:raise PacketError('Unknown premium offer')
    return offer,quote


def encode_purchase(offer,quote):
    packet=Writer().u8(0xc8).u8(0x3a).u32(offer).u32(quote).build()
    decode_purchase(packet);return packet


def purchase(path,account,packet,*,now=None):
    if not isinstance(account,str) or not account:raise ValueError('Account required')
    offer,quote=decode_purchase(packet);hours,cost=OFFERS[offer]
    if quote!=cost:raise ValueError('Цена премиума изменилась: войдите в игру заново')
    stamp=int(time.time() if now is None else now);kind=1 if offer<=2 else 3
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS premium_accounts (account TEXT PRIMARY KEY,kind INTEGER NOT NULL CHECK(kind IN (1,3)),expires INTEGER NOT NULL,last_offer INTEGER NOT NULL,last_purchase INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS premium_purchases (id INTEGER PRIMARY KEY,account TEXT NOT NULL,offer INTEGER NOT NULL,gold INTEGER NOT NULL,purchased INTEGER NOT NULL,expires INTEGER NOT NULL)')
        if 'credits' not in {r[1] for r in db.execute('PRAGMA table_info(premium_purchases)')}:
            db.execute('ALTER TABLE premium_purchases ADD COLUMN credits INTEGER NOT NULL DEFAULT 0')
        wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
        if wallet is None:raise ValueError('Кошелёк аккаунта отсутствует')
        prior=db.execute('SELECT kind,expires,last_offer,last_purchase FROM premium_accounts WHERE account=?',(account,)).fetchone()
        # C8/3A has no nonce. Suppress immediate duplicate clicks/retransmission.
        duplicate=prior and prior[2]==offer and 0<=stamp-prior[3]<5
        if not duplicate:
            if wallet[0]<cost:raise ValueError('Недостаточно кредитов для премиума')
            expires=max(stamp,prior[1] if prior else stamp)+hours*3600
            db.execute('UPDATE wallets SET credits=credits-? WHERE account=?',(cost,account))
            db.execute('INSERT INTO premium_accounts VALUES (?,?,?,?,?) ON CONFLICT(account) DO UPDATE SET kind=excluded.kind,expires=excluded.expires,last_offer=excluded.last_offer,last_purchase=excluded.last_purchase',
                (account,kind,expires,offer,stamp))
            db.execute('INSERT INTO premium_purchases(account,offer,gold,purchased,expires,credits) VALUES (?,?,?,?,?,?)',(account,offer,0,stamp,expires,cost))
    from .wallets import WalletStore
    return WalletStore(path).ensure(account)


def shared_xml():
    from xml.etree.ElementTree import Element,SubElement,tostring
    root=Element('PremiumAccount')
    for i,(hours,cost) in OFFERS.items():
        attrs=dict(id=str(i),hours=str(hours),goldCost=str(cost))
        if i==1:attrs.update(expBonus='0.5',creditsBonus='0.5',militaryRankBonus='0.5',abilityBonus='0.5',shopDiscount='0.2')
        if i==3:attrs.update(creditsBonus='0.5',influenceBonus='0.5',durabilityLossDiscount='2',shopDiscount='0.2')
        SubElement(root,'premium',attrs)
    return tostring(root,encoding='utf-8',xml_declaration=True)


def discount(db,account,price,now=None):
    return (price*4+4)//5 if state(db,account,now)[0] else price


def experience_multiplier(db,account,now=None):
    kind,_=state(db,account,now)
    if kind==1:return 3,2
    if kind==3:
        row=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='character_locations'").fetchone() else None
        if row and row[0]!=3:return 0,1
    return 1,1
