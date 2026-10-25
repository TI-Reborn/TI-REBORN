"""Account achievements: transactional counters, once-only awards and prize queue.

Gameplay callers use their existing transaction. Delivery happens in the city,
so it cannot interfere with battle inventory CAS. A full warehouse keeps prizes
pending; it never drops them or prevents credit/other prize delivery.
"""

from .db_transaction import connect
from . import warehouse_completion as completion
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from .protocol.achievements import decode_request,encode_list,encode_awards
from .item_catalog import items_root
from .item_ids import next_item_id

ROOT=Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def catalog():
    rows=json.loads((ROOT/'config/achievements.json').read_text(encoding='utf-8'))['records']
    if len(rows)!=58 or len({r['id'] for r in rows})!=58:raise ValueError('Invalid achievement catalog')
    return tuple(rows)


def schema(db):
    # No executescript: it would commit the caller's transaction prematurely.
    for sql in (
        'CREATE TABLE IF NOT EXISTS achievement_counters(account TEXT,metric TEXT,value INTEGER NOT NULL,PRIMARY KEY(account,metric))',
        'CREATE TABLE IF NOT EXISTS achievement_awards(account TEXT,id INTEGER,body TEXT NOT NULL,notified INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(account,id))',
        'CREATE TABLE IF NOT EXISTS achievement_prizes(account TEXT,id INTEGER,position INTEGER,delivered INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(account,id,position))',
        'CREATE TABLE IF NOT EXISTS achievement_upgrades(account TEXT,instance_id INTEGER,PRIMARY KEY(account,instance_id))',
        'CREATE TABLE IF NOT EXISTS achievement_events(account TEXT,event_id TEXT,body TEXT NOT NULL,PRIMARY KEY(account,event_id))',
    ):db.execute(sql)


def update(db,account,*,add=None,maximum=None):
    schema(db)
    for values,operation in ((add or {},'value+excluded.value'),(maximum or {},'MAX(value,excluded.value)')):
        for metric,value in values.items():
            if not isinstance(metric,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',metric) or type(value) is not int or value<0:raise ValueError('Invalid achievement progress')
            db.execute('INSERT INTO achievement_counters VALUES (?,?,?) ON CONFLICT(account,metric) '
                       f'DO UPDATE SET value=MIN(4294967295,{operation})',(account,metric,min(value,0xffffffff)))
    counters=dict(db.execute('SELECT metric,value FROM achievement_counters WHERE account=?',(account,)))
    for r in catalog():
        if counters.get(r['metric'],0)<r['goal']:continue
        body=json.dumps(r,ensure_ascii=False)
        if db.execute('INSERT OR IGNORE INTO achievement_awards(account,id,body) VALUES (?,?,?)',
                      (account,r['id'],body)).rowcount:
            for n in range(len(r['prizes'])+bool(r.get('temporary_credits'))):
                db.execute('INSERT INTO achievement_prizes(account,id,position) VALUES (?,?,?)',(account,r['id'],n))


def event(db,account,event_id,*,add=None,maximum=None):
    """Persist accepted shared event once, inside its authoritative transaction."""
    if not db.in_transaction:raise RuntimeError('Achievement event requires the gameplay transaction')
    if not isinstance(account,str) or not account or not isinstance(event_id,str) or not 1<=len(event_id)<=160 or any(ord(c)<32 for c in event_id):raise ValueError('Invalid achievement event identity')
    body=json.dumps(dict(add=add or {},maximum=maximum or {}),sort_keys=True,allow_nan=False)
    schema(db);old=db.execute('SELECT body FROM achievement_events WHERE account=? AND event_id=?',(account,event_id)).fetchone()
    if old:
        if old[0]!=body:raise ValueError('Conflicting achievement event')
        return False
    update(db,account,add=add,maximum=maximum)
    db.execute('INSERT INTO achievement_events VALUES (?,?,?)',(account,event_id,body));return True


def assault_result(db,account,event_id,*,captured=False,defended=False,place=None):
    """Caller verifies clan membership and actual final shared assault result."""
    if type(captured) is not bool or type(defended) is not bool or captured and defended:raise ValueError('Invalid clan assault outcome')
    if place is not None and (type(place) is not int or not 1<=place<=0xffffffff):raise ValueError('Invalid assault competition place')
    add={k:1 for k,yes in (('clan_capture',captured),('clan_defense',defended),('assault_top20',place is not None and place<=20)) if yes}
    return event(db,account,_event_identity('assault',event_id),add=add)


def influence_received(db,account,event_id,amount):
    """Actual contribution after successful clan debit/credit, never a preview."""
    return event(db,account,_event_identity('influence',event_id),add={'clan_influence':amount})


def _event_identity(prefix,identity):
    if not isinstance(identity,str) or not identity:raise ValueError('Invalid achievement event identity')
    return prefix+':'+identity


def ranked_result(db,account,event_id,*,result,league_before,league_after,streak):
    """Original league index3 bronze,2 silver,1 gold,0 platinum; ties do not win."""
    if type(result) is not int or result not in (0,1,2) or type(league_before) is not int or league_before not in (0,1,2,3) or type(league_after) is not int or league_after not in (0,1,2,3) or type(streak) is not int or not 0<=streak<=0xffffffff:raise ValueError('Invalid accepted league result')
    if result!=1 and streak:raise ValueError('A loss or draw cannot preserve a winning streak')
    maximum={k:1 for k,threshold in (('silver_league',2),('gold_league',1),('platinum_league',0)) if league_after<=threshold}
    maximum['league_streak']=streak
    return event(db,account,_event_identity('ranked',event_id),add={'bronze_win':1} if result==1 and league_before==3 else {},maximum=maximum)


def upgraded(db,account,identity):
    schema(db)
    if db.execute('INSERT OR IGNORE INTO achievement_upgrades VALUES (?,?)',(account,identity)).rowcount:
        update(db,account,add={'upgraded_items':1})


def snapshots(db,account):
    from .protocol.pet_info import decode_pet_info
    maximum={}
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'wallets' in tables:
        row=db.execute('SELECT credits FROM wallets WHERE account=?',(account,)).fetchone()
        if row:maximum['credits_peak']=row[0]
    if 'clan_members' in tables:
        row=db.execute('SELECT contribution FROM clan_members WHERE account=?',(account,)).fetchone()
        if row:maximum['clan_influence']=row[0]
    if 'owned_pets' in tables:
        for human,packet in db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=?',(account,)):
            f=decode_pet_info(packet,human_equipment=bool(human)).fields
            level=f['0x8c4aef'];resource=f['0x8c446f']
            if human:maximum['merc_level']=max(maximum.get('merc_level',0),level)
            key='dog_level' if resource in (3,4,5) else 'miner_level' if resource==6 else None
            if key:maximum[key]=max(maximum.get(key,0),level)
    if 'ranked_players' in tables:
        row=db.execute('SELECT league,streak,wins+losses+draws FROM ranked_players WHERE account=?',(account,)).fetchone()
        if row and row[2]:
            league,streak,_=row
            if league not in (0,1,2,3) or type(streak) is not int or streak<0:raise ValueError('Invalid saved league achievement state')
            maximum.update({k:1 for k,threshold in (('silver_league',2),('gold_league',1),('platinum_league',0)) if league<=threshold})
            maximum['league_streak']=streak
    update(db,account,maximum=maximum)


MAX_METRICS={'attack_kills','turn_kills','match_kills','miss_streak','critical_streak','dodge_streak'}


def settle_battle(db,account,report,result,*,escaped=False):
    add={k:v for k,v in report['counters'].items() if k not in MAX_METRICS}
    maximum={k:v for k,v in report['counters'].items() if k in MAX_METRICS}
    add['battles']=1
    if result==1 and not escaped:
        add['wins']=1
        prefix={0:'survival',1:'team',4:'wall'}.get(report['mode'])
        if prefix:
            add[prefix+'_wins']=1
            if report['clean']:add[prefix+'_clean']=1
    update(db,account,add=add,maximum=maximum)


@lru_cache(maxsize=1)
def item_definitions():
    return {int(n.get('id')):{v.get('key'):v.get('val') for v in n.findall('value')}
            for n in items_root().iter('item')}


class AchievementStore:
    def __init__(self,path,*,capacity=3000):
        from .warehouse import WarehouseStore
        self.path,self.capacity=path,capacity
        WarehouseStore(path)
        with closing(connect(path)) as db,db:schema(db)

    def handle(self,account,packet,character_name):
        mode,name=decode_request(packet)
        if isinstance(character_name,bytes):character_name=character_name.decode('cp1251')
        if mode!=0:raise ValueError('Недоступный раздел достижений')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            own=db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(account,)).fetchone() if completion.exists(db,'characters') else None
            canonical_name=own[0].decode('cp1251') if own else character_name
            if name.casefold()!=canonical_name.casefold():
                from .social_completion import public_achievements
                target,rows=public_achievements(db,name,account,catalog=catalog())
                return encode_list(mode,target,rows,private=False)
            snapshots(db,account)
            counters=dict(db.execute('SELECT metric,value FROM achievement_counters WHERE account=?',(account,)))
            earned={i:json.loads(body) for i,body in db.execute('SELECT id,body FROM achievement_awards WHERE account=?',(account,))}
            rows=[]
            for current in catalog():
                r=earned.get(current['id'],current)
                rows.append({**r,'earned':int(r['id'] in earned),'counter':min(counters.get(r['metric'],0),r['goal'])})
            return encode_list(mode,canonical_name,rows)

    def flush(self,account):
        """Only called out of battle. Serialize before committing delivery flags."""
        from .warehouse import WarehouseStore
        from .protocol.item_list import ItemRecord,decode_item_list,encode_item_list
        from .protocol.warehouse import encode_private_warehouse_snapshot
        from .protocol.asset_count import AssetCount,encode_asset_count
        from .item_stacking import merge_stacks
        replies=[]
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            # Automatic delivery also runs after reconnect and map arrivals.
            # Non-city locations have no warehouse; keep every receipt pending
            # until the owner reaches a city, on this same authoritative unit.
            if completion.current_town(db, account, required=False) is None:
                return ()
            snapshots(db,account)
            awards=[(json.loads(body),notified) for body,notified in db.execute(
                'SELECT body,notified FROM achievement_awards WHERE account=? ORDER BY id',(account,))]
            pending={(i,p) for i,p in db.execute('SELECT id,position FROM achievement_prizes WHERE account=? AND delivered=0',(account,))}
            if not awards or (not pending and all(notified for _,notified in awards)):return ()
            warehouse_all=WarehouseStore._read(db,account);seen=set(warehouse_all)
            warehouse=completion.read_scope(db,account,warehouse_all,required=True)
            warehouse_before=dict(warehouse)
            assignments={}
            for inv, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(account,)):
                for item in decode_item_list(inv)[1]:
                    if item.instance_id in seen:raise ValueError('Duplicate item identity')
                    seen.add(item.instance_id)
            next_id=next_item_id(db,account,seen)
            changed=False;credits=0;notifications=[]
            for row,notified in awards:
                prizes=list(row['prizes'])
                if row.get('temporary_credits'):prizes.append(dict(kind='credits',value=row['temporary_credits']))
                for n,p in enumerate(prizes):
                    if (row['id'],n) not in pending:continue
                    if p['kind']=='credits':
                        wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(account,)).fetchone()
                        if wallet is None or wallet[0]+credits+p['value']>0xffffffff:continue
                        credits+=p['value']
                    elif p['kind']==0:
                        definition=item_definitions()[p['item_id']];level=p['enhancement']
                        durability=int(definition.get('durability','0'))+65*level
                        additions=[ItemRecord(next_id+j,p['item_id'],bytes(2),1,0,0,(durability,)*3,
                                              bytes((level,0,0,0)),None,bytes((level,0,int(definition.get('special','0')=='1'))))
                                   for j in range(p['count'])]
                        if next_id+p['count']>0xffffffff:continue
                        try:merged,new_assignments=completion.merge_scope(db,account,(*warehouse.values(),*additions),warehouse_before,origin='achievement:'+str(row['id']),limit=self.capacity)
                        except ValueError:continue
                        assignments.update(new_assignments)
                        warehouse={i.instance_id:i for i in merged};next_id+=p['count'];changed=True
                    elif type(p['kind']) is int and p['kind'] in (1,3):
                        # Earned snapshot already drives read-only bonus APIs.
                        # Marking delivery cannot increment rank/rating again.
                        from .achievement_benefits import bonus_value
                        bonus_value(p)
                    else:
                        # Keep unrecovered reward kinds pending without loss.
                        continue
                    db.execute('UPDATE achievement_prizes SET delivered=1 WHERE account=? AND id=? AND position=?',(account,row['id'],n))
                if not notified:notifications.append(row)
            if notifications:
                replies.append(encode_awards(notifications))
                db.executemany('UPDATE achievement_awards SET notified=1 WHERE account=? AND id=?',[(account,r['id']) for r in notifications])
            if changed:
                replies.extend(encode_private_warehouse_snapshot(warehouse.values()))
                completion.persist_scope(db,account,warehouse_before,warehouse.values(),assignments)
                db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(account,next_id))
            if credits:
                db.execute('UPDATE wallets SET credits=credits+? WHERE account=?',(credits,account))
                wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
                replies.append(encode_asset_count(AssetCount(*wallet)))
                update(db,account,maximum={'credits_peak':wallet[0]})
            return tuple(replies)


class BattleAchievements:
    """Transient accepted combat events; settlement persists them once per match."""
    def __init__(self):
        self.counters={};self.streaks={};self.turn_kills={}

    def add(self,owner,key,value=1):
        row=self.counters.setdefault(owner,{})
        row[key]=row.get(key,0)+value

    def maximum(self,owner,key,value):
        row=self.counters.setdefault(owner,{})
        row[key]=max(row.get(key,0),value)

    def attack(self,actor,turn,weapon_id,weapon_type,outcomes):
        # outcomes=(victim, hit, critical, killed, visible), hostile targets only.
        if not outcomes:return
        owner=actor.owner_id;kills=sum(int(x[3]) for x in outcomes)
        key='fist' if weapon_id==300 else weapon_type.lower() if weapon_id!=333 else 'dog'
        self.add(owner,'kills',kills);self.add(owner,key+'_kills',kills)
        self.add(owner,'unseen_kills',sum(int(x[3] and not x[4]) for x in outcomes))
        self.maximum(owner,'attack_kills',kills)
        turn_key=(owner,turn);self.turn_kills[turn_key]=self.turn_kills.get(turn_key,0)+kills
        self.maximum(owner,'turn_kills',self.turn_kills[turn_key])
        self.maximum(owner,'match_kills',self.counters[owner]['kills'])
        for metric,yes in (('miss_streak',not any(x[1] for x in outcomes)),
                           ('critical_streak',weapon_type!='Melee' and weapon_id!=333 and any(x[2] for x in outcomes))):
            k=(actor.actor_id,metric);self.streaks[k]=self.streaks.get(k,0)+1 if yes else 0
            self.maximum(owner,metric,self.streaks[k])
        for victim,hit,_,_,_ in outcomes:
            k=(victim.actor_id,'dodge_streak');self.streaks[k]=0 if hit else self.streaks.get(k,0)+1
            self.maximum(victim.owner_id,'dodge_streak',self.streaks[k])

    def report(self,field,owner,mode):
        return dict(counters=dict(self.counters.get(owner,{})),mode=mode,
                    clean=all(a.health>0 for a in field._actors.values() if field.allied(a.owner_id,owner)))
