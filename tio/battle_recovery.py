"""Paid treatment and durable out-of-battle recovery; rates are local policy."""

from .db_transaction import connect
from contextlib import closing
import sqlite3,json,time,math
from pathlib import Path
from .protocol.binary import Reader, PacketError
from .protocol.pet_info import PetInfo, decode_pet_info, encode_pet_info
from .protocol.asset_count import AssetCount
from .passive_stats import project_saved_pet

POLICY=json.loads((Path(__file__).resolve().parents[1]/'config/recovery.json').read_text(encoding='utf-8'))
CREDITS_PER_HP = POLICY['credits_per_hp']
SECONDS_PER_HP = POLICY['seconds_per_hp']
if type(CREDITS_PER_HP) is not int or CREDITS_PER_HP<=0:raise ValueError('Invalid treatment tariff')
if type(SECONDS_PER_HP) is not int or SECONDS_PER_HP<=0:raise ValueError('Invalid recovery interval')


def decode_treatment(data):
    # Native Finish callback719f60 ->8c3d84: 7C, byte count, u32 pet IDs.
    r=Reader(data)
    if r.u8()!=0x7c:raise PacketError('Expected treatment request')
    count=r.u8()
    if not 1<=count<=31:raise PacketError('Invalid treatment count')
    ids=tuple(r.u32() for _ in range(count));r.finish()
    if len(set(ids))!=count:raise PacketError('Duplicate treatment pet')
    return ids


def save_wounds(db,account,health):
    for owner,hp in health.items():
        row=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        if row is None:raise ValueError('Battle pet missing')
        human,raw=row;pet=decode_pet_info(raw,human_equipment=bool(human))
        if not 0<=hp<=65535:raise ValueError('Invalid battle health')
        packet=encode_pet_info(PetInfo(bool(human),{**pet.fields,'0x8c4ab1':hp}))
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,account,owner))
        # Invalidate the clock after a new wound or paid full heal. The next
        # refresh starts a fresh interval; older databases need no clock table.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='pet_recovery'").fetchone():
            db.execute('DELETE FROM pet_recovery WHERE account=? AND pet_id=?',(account,owner))


def treat(path,account,ids,*,blocked=False):
    """Atomic charge and recovery; retries for healthy pets cost nothing."""
    if blocked:raise ValueError('Leave battle or matchmaking before treatment')
    if not account or not 1<=len(ids)<=31 or len(set(ids))!=len(ids):raise ValueError('Invalid treatment recipients')
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        updates={};cost=0
        for owner in ids:
            row=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
            if row is None:raise ValueError('Unknown treatment pet')
            human,raw=row
            pet=decode_pet_info(project_saved_pet(db,account,owner,raw,bool(human)),human_equipment=bool(human))
            hp=pet.fields['0x8c4ab1'];maximum=pet.fields['0x8c4a07']
            cost+=max(0,maximum-hp)*CREDITS_PER_HP
            updates[owner]=max(hp,maximum)
        wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
        if wallet is None or wallet[0]<cost:raise ValueError('Insufficient treatment credits')
        save_wounds(db,account,updates)
        db.execute('UPDATE wallets SET credits=credits-? WHERE account=?',(cost,account))
        return AssetCount(wallet[0]-cost,wallet[1]),cost


class RecoveryStore:
    """Wall-clock HP recovery with persisted remainders and battle suspension.

    Full health does not bank time. Changed HP/maxHP starts a fresh interval;
    time before learning a health perk cannot heal its newly granted capacity.
    A missing clock row (old save/new wound) starts now, never retroactively.
    """
    def __init__(self,path,*,clock=time.time,seconds_per_hp=SECONDS_PER_HP):
        if not math.isfinite(seconds_per_hp) or seconds_per_hp<=0:raise ValueError('Invalid recovery interval')
        self.path=path;self.clock=clock;self.interval=seconds_per_hp
        with closing(connect(path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS pet_recovery (account TEXT NOT NULL,pet_id INTEGER NOT NULL,stamp REAL NOT NULL,hp INTEGER NOT NULL,maximum INTEGER NOT NULL,paused INTEGER NOT NULL,PRIMARY KEY(account,pet_id))')

    def refresh(self,account,*,blocked=False):
        if not isinstance(account,str) or not account:raise ValueError('Account required')
        now=self.clock()
        if not math.isfinite(now):raise ValueError('Invalid recovery time')
        changed=[]
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            rank_changed=set()
            if not blocked:
                before={i:bytes(p) for i,p in db.execute('SELECT pet_id,pet_packet FROM owned_pets WHERE account=?',(account,))}
                from .ranks import sync
                sync(db,account,now=now)
                rank_changed={i for i,p in db.execute('SELECT pet_id,pet_packet FROM owned_pets WHERE account=?',(account,)) if p!=before[i]}
            rows=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(account,)).fetchall()
            for owner,human,raw in rows:
                packet=project_saved_pet(db,account,owner,raw,bool(human))
                pet=decode_pet_info(packet,human_equipment=bool(human))
                hp=pet.fields['0x8c4ab1'];maximum=pet.fields['0x8c4a07']
                old=db.execute('SELECT stamp,hp,maximum,paused FROM pet_recovery WHERE account=? AND pet_id=?',(account,owner)).fetchone()
                stamp=now
                if not blocked and old and not old[3] and old[1:3]==(hp,maximum) and now>=old[0] and hp<maximum:
                    points=int((now-old[0])//self.interval)
                    stamp=old[0]+points*self.interval
                    recovered=min(maximum,hp+points)
                    if recovered!=hp:
                        hp=recovered
                        base=decode_pet_info(raw,human_equipment=bool(human))
                        base.fields['0x8c4ab1']=hp
                        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(encode_pet_info(base),account,owner))
                        pet.fields['0x8c4ab1']=hp;changed.append(encode_pet_info(pet))
                        rank_changed.discard(owner)
                if owner in rank_changed:changed.append(encode_pet_info(pet))
                if hp>=maximum:stamp=now
                db.execute('INSERT INTO pet_recovery VALUES (?,?,?,?,?,?) ON CONFLICT(account,pet_id) DO UPDATE SET stamp=excluded.stamp,hp=excluded.hp,maximum=excluded.maximum,paused=excluded.paused',
                           (account,owner,stamp,hp,maximum,int(blocked)))
        return tuple(changed)
