"""Manual clan benefits on shared SQLite authority; callers own the transaction.

All mutation APIs require a transaction and join its rollback boundary. No client
provided score is accepted: assault rewards read finalized warfare receipts and
frozen participants. There is deliberately no invented historical wire protocol.
"""
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import struct
import time

from .clans import CREST, ClanRejected, membership, require, record

ROOT = Path(__file__).resolve().parents[1]
base_fund_completion_installed=True
MAX = 0xffffffff
WEEK = 604800
MONDAY = 345600  # 1970-01-05 UTC.


@lru_cache(maxsize=1)
def policy():
    p = json.loads((ROOT/'config/clan_benefits.json').read_text(encoding='utf-8'))
    if (p['version'] != 1 or p['crest'] != dict(width=16,height=16,bits=24,max_bytes=824,credits=1000)
            or p['influence']['experience_divisor'] != 20 or p['influence']['gold_shop_per_gold'] != 1
            or p['base']['max_tax_percent'] != 10 or p['base']['capture_influence'] != 10000
            or p['weekly'] != dict(seconds=WEEK,top_clans=20,rank_per_kill=[[1,5],[5,4],[10,3],[20,2]])):
        raise ValueError('Clan policy changed a recovered manual rule')
    i, a = p['influence'], p['assault']
    if not 20000 <= i['daily_decay_ppm'] <= 30000 or not 1 <= i['max_decay_hours_per_call'] <= 744:
        raise ValueError('Invalid bounded decay policy')
    if (i['level_decay_multipliers'][:2] != ['1','3/2'] or len(i['level_decay_multipliers']) != 3
            or any(Fraction(v) <= 0 or Fraction(v).denominator not in (1,2) for v in i['level_decay_multipliers'])):
        raise ValueError('Invalid clan level decay multipliers')
    if a['top_players_per_side'] != 20 or len(a['medal_multipliers']) != 3 or any(Fraction(v) <= 1 for v in a['medal_multipliers']):
        raise ValueError('Invalid assault prize policy')
    if a['defense_fund_weights'] != [5,3,2] or any(type(v) is not int for v in a['defense_fund_weights']):
        raise ValueError('Invalid defense fund policy')
    if any(type(h) is not int or not 0 <= h <= 23 for h in p['base']['assault_hours_utc']):
        raise ValueError('Invalid base schedule choices')
    if p['base']['city_by_base'] != {'6':2,'7':4,'11':5,'12':8} or p['influence']['premium_kind']!=3 or p['influence']['premium_multiplier']!='3/2':
        raise ValueError('Invalid recovered base mapping or premium multiplier')
    if any(type(a[k]) is not int or not 1<=a[k]<=MAX for k in ('golden_tokens_each','booster_template','booster_count_each')):
        raise ValueError('Invalid positive assault prize count')
    return p


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False)


def integer(value, maximum=MAX):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ClanRejected('Некорректное целое число')
    return value


def key(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160 or any(ord(c)<32 for c in value):
        raise ClanRejected('Некорректный идентификатор операции')
    return value


def exists(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def schema(db):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS clan_benefit_receipts(operation TEXT,identity TEXT,account TEXT,
           request TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(operation,identity,account))''',
        'CREATE TABLE IF NOT EXISTS clan_decay(clan_id INTEGER PRIMARY KEY,last_hour INTEGER NOT NULL,remainder INTEGER NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS clan_crest_blobs(id INTEGER PRIMARY KEY AUTOINCREMENT,
           clan_id INTEGER NOT NULL,digest TEXT NOT NULL,bmp BLOB NOT NULL,UNIQUE(clan_id,digest))''',
        'CREATE TABLE IF NOT EXISTS clan_crests(clan_id INTEGER PRIMARY KEY,crest_id INTEGER NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS clan_base_schedules(location INTEGER,period_start INTEGER,
           owner_clan INTEGER NOT NULL,chosen_start INTEGER NOT NULL,PRIMARY KEY(location,period_start))''',
        '''CREATE TABLE IF NOT EXISTS clan_defense_funds(event_id TEXT PRIMARY KEY,clan_id INTEGER NOT NULL,
           credits INTEGER NOT NULL DEFAULT 0,settled INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS clan_assault_totals(event_id TEXT,clan_id INTEGER,week_start INTEGER,
           units INTEGER NOT NULL,PRIMARY KEY(event_id,clan_id))''',
        '''CREATE TABLE IF NOT EXISTS clan_weekly_badges(week_start INTEGER,clan_id INTEGER,place INTEGER NOT NULL,
           rank_per_kill INTEGER NOT NULL,starts INTEGER NOT NULL,expires INTEGER NOT NULL,PRIMARY KEY(week_start,clan_id))''',
        'CREATE TABLE IF NOT EXISTS clan_weeks(week_start INTEGER PRIMARY KEY,receipt TEXT NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS clan_assault_medals(event_id TEXT,account TEXT,side TEXT,place INTEGER NOT NULL,
           multiplier TEXT NOT NULL,PRIMARY KEY(event_id,account))''',
        '''CREATE TABLE IF NOT EXISTS clan_assault_prizes(event_id TEXT,account TEXT,template INTEGER NOT NULL,
           count INTEGER NOT NULL,delivered INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(event_id,account))''',
    ): db.execute(sql)
    for operation in ('UPDATE','DELETE'):
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS clan_benefit_receipts_no_{operation.lower()}
            BEFORE {operation} ON clan_benefit_receipts BEGIN SELECT RAISE(ABORT,'Clan benefit receipts are immutable'); END''')


def write(db):
    if not db.in_transaction:
        raise RuntimeError('Clan benefit write requires the gameplay transaction')
    schema(db)


def prior(db, operation, identity, account, request):
    row = db.execute('SELECT request,receipt FROM clan_benefit_receipts WHERE operation=? AND identity=? AND account=?',
                     (operation,key(identity),account)).fetchone()
    if row:
        if row[0] != request: raise ClanRejected('Повтор операции отличается от сохранённого запроса')
        return json.loads(row[1])


def receipt(db, operation, identity, account, request, result):
    db.execute('INSERT INTO clan_benefit_receipts VALUES (?,?,?,?,?)',
               (operation,key(identity),account,request,canonical(result)))
    return json.loads(canonical(result))


def add_influence(db, clan_id, amount, *, account=None):
    integer(amount)
    row = db.execute('SELECT influence FROM clans WHERE id=?', (clan_id,)).fetchone()
    if row is None or row[0]+amount > MAX: raise ClanRejected('Переполнение влияния или отсутствующий клан')
    if account is not None:
        own = db.execute('SELECT contribution FROM clan_members WHERE account=? AND clan_id=?', (account,clan_id)).fetchone()
        if own is None or own[0]+amount > MAX: raise ClanRejected('Вклад участника изменился или переполнен')
        db.execute('UPDATE clan_members SET contribution=contribution+? WHERE account=?', (amount,account))
    db.execute('UPDATE clans SET influence=influence+?,revision=revision+1 WHERE id=?', (amount,clan_id))


def influence_multiplier(db, account, *, now=None):
    from .premium import state
    from .achievement_benefits import influence_multiplier as achievement_multiplier
    p=policy(); factor=Fraction(p['influence']['premium_multiplier']) if state(db,account,now)[0]==p['influence']['premium_kind'] else Fraction(1)
    highest=achievement_multiplier(db,account)
    medal=Fraction(1)
    if exists(db,'clan_assault_medals'):
        medal=max((Fraction(row[0]) for row in db.execute('SELECT multiplier FROM clan_assault_medals WHERE account=?',(account,))),default=medal)
    return factor*highest*medal


def settle_experience(db, account, identity, experience, *, city_coefficient=1, now=None):
    """Replace legacy settle_influence; identity is authoritative match/account key."""
    write(db)
    if not isinstance(experience,dict) or any(type(i) is not int or i<=0 for i in experience): raise ClanRejected('Некорректный отчёт опыта')
    values={str(i):integer(v) for i,v in experience.items()}
    if exists(db,'owned_pets') and any(not db.execute('SELECT 1 FROM owned_pets WHERE account=? AND pet_id=?',(account,i)).fetchone() for i in experience):
        raise ClanRejected('Опыт принадлежит чужому или отсутствующему бойцу')
    coefficient=Fraction(str(city_coefficient))
    if not 0 <= coefficient <= 10: raise ClanRejected('Некорректный коэффициент города')
    request=canonical(dict(experience=values,coefficient=str(coefficient)))
    old=prior(db,'xp',identity,account,request)
    if old is not None:return old
    clan=membership(db,account)
    factor=coefficient*influence_multiplier(db,account,now=now)/policy()['influence']['experience_divisor']
    amount=int(sum(values.values())*factor) if clan else 0
    if amount:add_influence(db,clan['id'],amount,account=account)
    return receipt(db,'xp',identity,account,request,dict(clan_id=clan['id'] if clan else None,amount=amount,multiplier=str(factor)))


def premium_gold_spent(db, account, identity, gold):
    """Invoke only after a successful premium ITEM shop debit, in that transaction."""
    write(db);integer(gold);request=canonical(dict(gold=gold));old=prior(db,'gold',identity,account,request)
    if old is not None:return old
    clan=membership(db,account);amount=gold if clan else 0
    if amount:add_influence(db,clan['id'],amount,account=account)
    return receipt(db,'gold',identity,account,request,dict(clan_id=clan['id'] if clan else None,amount=amount))


def decay(db, *, now=None):
    """Bounded catch-up; repeated same-hour calls cannot reduce influence twice."""
    write(db);stamp=integer(int(time.time() if now is None else now),2**53);hour=stamp//3600;p=policy()['influence'];changed={}
    denominator=24*1000000*2
    for clan,level,value in db.execute('SELECT id,level,influence FROM clans ORDER BY id').fetchall():
        row=db.execute('SELECT last_hour,remainder FROM clan_decay WHERE clan_id=?',(clan,)).fetchone()
        if row is None:
            db.execute('INSERT INTO clan_decay VALUES (?,?,0)',(clan,hour));continue
        last,remainder=row;hours=max(0,min(hour-last,p['max_decay_hours_per_call']))
        rate=Fraction(p['daily_decay_ppm'])*Fraction(p['level_decay_multipliers'][level])
        # All policy multipliers have denominator1 or2, retained exactly.
        units=int(rate*2);current=value
        for _ in range(hours):
            charge,remainder=divmod(current*units+remainder,denominator)
            current=max(0,current-charge)
        if hours:
            db.execute('UPDATE clan_decay SET last_hour=?,remainder=? WHERE clan_id=?',(last+hours,remainder,clan))
            if current!=value:
                db.execute('UPDATE clans SET influence=?,revision=revision+1 WHERE id=?',(current,clan));changed[clan]=value-current
    return changed


def validate_crest(bmp):
    p=policy()['crest']
    if not isinstance(bmp,bytes) or not 54<=len(bmp)<=p['max_bytes'] or bmp[:2]!=b'BM':raise ClanRejected('Нужен BMP16×16 24bit не больше824 байт')
    size,reserved,offset=struct.unpack_from('<III',bmp,2)
    dib,width,height,planes,bits,compression,image=struct.unpack_from('<IiiHHII',bmp,14)
    if size!=len(bmp) or reserved or dib!=40 or width!=16 or height!=16 or planes!=1 or bits!=24 or compression!=0:
        raise ClanRejected('Некорректный заголовок эмблемы')
    if offset!=54 or image not in (0,768) or offset+768!=len(bmp):raise ClanRejected('Некорректные пиксели эмблемы')
    return hashlib.sha256(bmp).hexdigest()


def set_crest(db, account, bmp, identity):
    write(db);digest=validate_crest(bmp) if bmp is not None else None;clan=require(db,account,CREST);request=canonical(dict(clan=clan['id'],digest=digest))
    old=prior(db,'crest',identity,account,request)
    if old is not None:return old
    current=db.execute('SELECT b.id,b.digest FROM clan_crests c JOIN clan_crest_blobs b ON b.id=c.crest_id WHERE c.clan_id=?',(clan['id'],)).fetchone()
    if bmp is None:
        if current:
            db.execute('DELETE FROM clan_crests WHERE clan_id=?',(clan['id'],))
            record(db,clan['id'],account,'crest',0)
        return receipt(db,'crest',identity,account,request,dict(crest_id=0,charged=0))
    if current and current[1]==digest:return receipt(db,'crest',identity,account,request,dict(crest_id=current[0],charged=0))
    if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',(1000,account,1000)).rowcount!=1:raise ClanRejected('Недостаточно кредитов для эмблемы')
    db.execute('INSERT OR IGNORE INTO clan_crest_blobs(clan_id,digest,bmp) VALUES (?,?,?)',(clan['id'],digest,bmp))
    crest=db.execute('SELECT id FROM clan_crest_blobs WHERE clan_id=? AND digest=?',(clan['id'],digest)).fetchone()[0];integer(crest)
    db.execute('INSERT INTO clan_crests VALUES (?,?) ON CONFLICT(clan_id) DO UPDATE SET crest_id=excluded.crest_id',(clan['id'],crest))
    record(db,clan['id'],account,'crest',crest)
    return receipt(db,'crest',identity,account,request,dict(crest_id=crest,charged=1000))


def crest_id(db, clan_id):
    if not exists(db,'clan_crests'):return 0
    row=db.execute('SELECT crest_id FROM clan_crests WHERE clan_id=?',(clan_id,)).fetchone();return row[0] if row else 0


def crest_content(db, identity):
    integer(identity)
    row=db.execute('SELECT bmp,digest FROM clan_crest_blobs WHERE id=?',(identity,)).fetchone() if exists(db,'clan_crest_blobs') else None
    if row is None:raise ClanRejected('Эмблема не найдена')
    if validate_crest(bytes(row[0]))!=row[1]:raise ClanRejected('Содержимое эмблемы повреждено')
    return bytes(row[0])


def base_claim(db, town):
    integer(town)
    row=db.execute('SELECT owner_clan,tax_percent,revision FROM territory_claims WHERE location=?',(town,)).fetchone() if exists(db,'territory_claims') else None
    if row is None or row[0] is None:raise ClanRejected('У базы нет владельца')
    audit=db.execute('SELECT owner_clan,tax_percent FROM territory_claim_history WHERE location=? AND revision=?',(town,row[2])).fetchone()
    if audit!=row[:2]:raise ClanRejected('История базы повреждена')
    return row


def set_base_tax(db, account, town, tax, *, expected_revision):
    write(db);integer(tax,10);clan=require(db,account,leader=True);owner,previous,revision=base_claim(db,town)
    if owner!=clan['id'] or revision!=expected_revision:raise ClanRejected('Владелец базы или ревизия изменились')
    if tax==previous:return revision
    if exists(db,'warfare_events') and db.execute('SELECT 1 FROM warfare_events WHERE town=? AND finalized=0',(town,)).fetchone():raise ClanRejected('Налог закреплён до завершения штурма')
    integer(revision+1)
    db.execute('INSERT INTO territory_claim_history VALUES (?,?,?,?,?,?,?)',(town,revision+1,owner,tax,account,'owner tax',time.time()))
    db.execute('UPDATE territory_claims SET tax_percent=?,revision=? WHERE location=? AND revision=?',(tax,revision+1,town,revision))
    record(db,owner,account,'base_tax',canonical(dict(town=town,tax=tax)))
    return revision+1


def sales_quote(db,town,gross,*,premium=False):
    """Read-only quote shared with accepted sale settlement; never credits a safe."""
    integer(town);integer(gross)
    if type(premium) is not bool:raise ClanRejected('Некорректный тип магазина')
    base=next((int(b) for b,c in policy()['base']['city_by_base'].items() if c==town),None)
    claim=base_claim(db,base) if base is not None and exists(db,'territory_claims') and db.execute('SELECT 1 FROM territory_claims WHERE location=? AND owner_clan IS NOT NULL',(base,)).fetchone() else None
    tax=gross*claim[1]//100 if claim and not premium else 0
    return dict(owner_clan=claim[0] if claim else None,tax=tax,net=gross-tax)


def sales_tax(db, account, identity, town, gross, *, premium=False):
    """Returns seller net; caller credits the returned net once in its transaction."""
    write(db);integer(gross)
    if type(premium) is not bool:raise ClanRejected('Некорректный тип магазина')
    request=canonical(dict(town=integer(town),gross=gross,premium=premium));old=prior(db,'tax',identity,account,request)
    if old is not None:return old
    result=sales_quote(db,town,gross,premium=premium);tax=result['tax']
    if tax:
        if db.execute('UPDATE clans SET credits=credits+?,revision=revision+1 WHERE id=? AND credits<=?',(tax,result['owner_clan'],MAX-tax)).rowcount!=1:raise ClanRejected('Клановый сейф переполнен')
        record(db,result['owner_clan'],account,'base_sales_tax',canonical(dict(sale=identity,gross=gross,tax=tax)))
    return receipt(db,'tax',identity,account,request,result)


def schedule_options(default_start):
    stamp=integer(default_start,2**53);day=stamp//86400*86400
    return tuple(day+h*3600 for h in policy()['base']['assault_hours_utc'])


def set_next_assault(db, account, town, default_start, chosen_start, *, now=None):
    write(db);clan=require(db,account,leader=True);owner,_,_=base_claim(db,town)
    if clan['id']!=owner:raise ClanRejected('База принадлежит другому клану')
    territories=json.loads((ROOT/'config/territories.json').read_text(encoding='utf-8'))
    location=next((r for r in territories['territories'] if r['id']==town and r['enabled'] and r['kind']=='base'),None)
    if location is None:raise ClanRejected('Неизвестная действующая база')
    from datetime import datetime
    first=int(datetime.fromisoformat(location['first_start_utc'].replace('Z','+00:00')).timestamp())
    if default_start<first or (default_start-first)%territories['period_seconds']:raise ClanRejected('День проведения штурма закреплён за базой')
    if chosen_start not in schedule_options(default_start) or chosen_start<=int(time.time() if now is None else now):raise ClanRejected('Выберите предложенное будущее время штурма')
    choices=schedule_options(default_start)
    if exists(db,'warfare_events') and db.execute('SELECT 1 FROM warfare_events WHERE town=? AND starts IN ('+','.join('?' for _ in choices)+')',(town,*choices)).fetchone():raise ClanRejected('Следующий штурм уже создан')
    db.execute('INSERT INTO clan_base_schedules VALUES (?,?,?,?) ON CONFLICT(location,period_start) DO UPDATE SET owner_clan=excluded.owner_clan,chosen_start=excluded.chosen_start',(town,default_start,owner,chosen_start))
    record(db,owner,account,'next_assault',chosen_start);return chosen_start


def scheduled_start(db, town, default_start):
    if not exists(db,'clan_base_schedules'):return default_start
    row=db.execute('SELECT owner_clan,chosen_start FROM clan_base_schedules WHERE location=? AND period_start=?',(town,default_start)).fetchone()
    owner=db.execute('SELECT owner_clan FROM territory_claims WHERE location=?',(town,)).fetchone() if exists(db,'territory_claims') else None
    return row[1] if row and owner and row[0]==owner[0] else default_start


def week_start(stamp):return MONDAY+(int(stamp)-MONDAY)//WEEK*WEEK


def fund_defense(db, account, event_id, amount, identity, *, now=None):
    from .base_fund_completion import donate
    return donate(db,account,event_id,amount,identity,now=now)


def settle_assault(db, event_id):
    """Called after authoritative finalization, before its outer transaction commits."""
    write(db);key(event_id);request=canonical(dict(event_id=event_id));old=prior(db,'assault',event_id,'',request)
    if old is not None:return old
    event=db.execute('SELECT ends,claim,finalized,town FROM warfare_events WHERE id=?',(event_id,)).fetchone()
    final=db.execute('SELECT receipt FROM warfare_event_receipts WHERE event_id=?',(event_id,)).fetchone()
    if event is None or not event[2] or final is None:raise ClanRejected('Нет подтверждённого результата штурма')
    final=json.loads(final[0]);claim=json.loads(event[1]);p=policy();scores=list(db.execute('SELECT clan_id,account,ov_units,contested FROM warfare_scores WHERE event_id=? ORDER BY ov_units DESC,account',(event_id,)))
    defense=set()
    for raw, in db.execute('SELECT roster FROM warfare_matches WHERE event_id=?',(event_id,)):
        for group in json.loads(raw):
            if claim['owner_clan'] in group['clan_ids']:defense.update(group['clan_ids'])
    if claim['owner_clan'] is not None:defense.add(claim['owner_clan'])
    totals={}
    for clan,_,units,contested in scores:
        if contested:totals[clan]=totals.get(clan,0)+units
    if {str(c):u for c,u in db.execute('SELECT clan_id,SUM(ov_units) FROM warfare_scores WHERE event_id=? GROUP BY clan_id',(event_id,))}!=final['scores']:
        raise ClanRejected('Очки отличаются от сохранённого результата')
    for clan,units in totals.items():
        db.execute('INSERT INTO clan_assault_totals VALUES (?,?,?,?)',(event_id,clan,week_start(event[0]-1),max(0,units)))
    capture=0
    if final['captured'] and str(event[3]) in p['base']['city_by_base']:
        if (final['claim']['owner_clan']!=final['winner_clan'] or final['winner_clan']==claim['owner_clan']
                or totals.get(final['winner_clan'],0)<=0):raise ClanRejected('Некорректный результат захвата')
        capture=p['base']['capture_influence'];add_influence(db,final['winner_clan'],capture)
    players={};medals={}
    for side in ('attack','defense'):
        eligible=[r for r in scores if bool(r[0] in defense)==(side=='defense') and r[2]>0 and r[3]][:20]
        for place,(clan,account,_,_) in enumerate(eligible,1):
            players[account]=dict(side=side,place=place)
            if place<=3:
                factor=p['assault']['medal_multipliers'][place-1]
                db.execute('INSERT INTO clan_assault_medals VALUES (?,?,?,?,?)',(event_id,account,side,place,factor));medals[account]=factor
            # Same durable currency used by native range entry; no fake item token.
            db.execute('''CREATE TABLE IF NOT EXISTS range_accounts(account TEXT PRIMARY KEY,used_day INTEGER NOT NULL DEFAULT -1,
                golden INTEGER NOT NULL DEFAULT 0 CHECK(golden>=0),credit_day INTEGER NOT NULL DEFAULT -1,credit_visits INTEGER NOT NULL DEFAULT 0)''')
            db.execute('INSERT OR IGNORE INTO range_accounts(account) VALUES (?)',(account,))
            tokens=p['assault']['golden_tokens_each']
            if db.execute('UPDATE range_accounts SET golden=golden+? WHERE account=? AND golden<=?',(tokens,account,MAX-tokens)).rowcount!=1:raise ClanRejected('Переполнение жетонов')
            db.execute('INSERT INTO clan_assault_prizes VALUES (?,?,?,?,0)',(event_id,account,p['assault']['booster_template'],p['assault']['booster_count_each']))
    fund=db.execute('SELECT clan_id,credits,settled FROM clan_defense_funds WHERE event_id=?',(event_id,)).fetchone();payouts={};refunds={}
    if fund and not fund[2]:
        ranked=sorted(((c,n) for c,n in totals.items() if c in defense and n>0),key=lambda v:(-v[1],v[0]))[:3]
        from .base_fund_completion import settle
        payouts,refunds=settle(db,event_id,fund,ranked)
    result=dict(event_id=event_id,capture_influence=capture,players=players,medals=medals,defense_fund=payouts)
    if refunds:result['defense_refunds']=refunds
    return receipt(db,'assault',event_id,'',request,result)


def close_week(db, start, *, now=None):
    write(db);integer(start,2**53)
    if week_start(start)!=start or int(time.time() if now is None else now)<start+WEEK:raise ClanRejected('Неделя ещё не завершена')
    old=db.execute('SELECT receipt FROM clan_weeks WHERE week_start=?',(start,)).fetchone()
    if old:return json.loads(old[0])
    eligible=[]
    if exists(db,'warfare_events'):
        events=list(db.execute('SELECT id,finalized FROM warfare_events WHERE ends>? AND ends<=?',(start,start+WEEK)))
        if any(not done for _,done in events):raise ClanRejected('Ожидаются результаты штурмов недели')
        for event,_ in events:
            final=db.execute('SELECT receipt FROM warfare_event_receipts WHERE event_id=?',(event,)).fetchone()
            if final is None:raise ClanRejected('Нет подтверждённого результата штурма')
            version=json.loads(final[0]).get('benefits_version')
            if type(version) is int and version==1:
                settle_assault(db,event);eligible.append(event)
    rows=list(db.execute('''SELECT s.clan_id,SUM(s.units) score FROM clan_assault_totals s JOIN clans c ON c.id=s.clan_id
        WHERE s.week_start=? AND s.event_id IN ('''+','.join('?' for _ in eligible)+''')
        GROUP BY s.clan_id HAVING score>0 ORDER BY score DESC,s.clan_id LIMIT 20''',(start,*eligible))) if eligible else []
    result=[]
    for place,(clan,score) in enumerate(rows,1):
        bonus=next(b for limit,b in policy()['weekly']['rank_per_kill'] if place<=limit)
        db.execute('INSERT INTO clan_weekly_badges VALUES (?,?,?,?,?,?)',(start,clan,place,bonus,start+WEEK,start+2*WEEK))
        result.append(dict(clan_id=clan,place=place,score=score,rank_per_kill=bonus))
    db.execute('INSERT INTO clan_weeks VALUES (?,?)',(start,canonical(result)));return result


def rank_per_kill(db, account, *, now=None):
    clan=membership(db,account)
    if clan is None or not exists(db,'clan_weekly_badges'):return 0
    stamp=int(time.time() if now is None else now)
    row=db.execute('SELECT rank_per_kill FROM clan_weekly_badges WHERE clan_id=? AND starts<=? AND expires>? ORDER BY starts DESC LIMIT 1',(clan['id'],stamp,stamp)).fetchone()
    return row[0] if row else 0


def deliver_prizes(db, account, *, capacity=3000):
    """City-only caller; full warehouse preserves durable pending boosters."""
    write(db);integer(capacity)
    from .warehouse import WarehouseStore
    from .protocol.item_list import ItemRecord,decode_item_list,encode_item_list
    from .protocol.warehouse import encode_private_warehouse_snapshot
    from .item_stacking import merge_stacks
    import xml.etree.ElementTree as ET
    rows=list(db.execute('SELECT event_id,template,count FROM clan_assault_prizes WHERE account=? AND delivered=0 ORDER BY event_id',(account,)))
    if not rows:return ()
    from . import warehouse_completion as completion
    all_items=WarehouseStore._read(db,account);seen=set(all_items)
    items=completion.read_scope(db,account,all_items,required=True)
    before=dict(items);assignments={}
    for raw, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(account,)):
        for item in decode_item_list(raw)[1]:
            if item.instance_id in seen:raise ClanRejected('Повтор идентификатора предмета')
            seen.add(item.instance_id)
    seq=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(account,)).fetchone();next_id=max(max(seen,default=0)+1,seq[0] if seq else 1)
    definitions={int(n.get('id')):{v.get('key'):v.get('val') for v in n.findall('value')} for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot().iter('item')}
    completed=[]
    for event,template,count in rows:
        definition=definitions[template];durability=int(definition.get('durability','0'))
        if next_id+count>MAX:raise ClanRejected('Исчерпаны идентификаторы предметов')
        additions=[ItemRecord(next_id+n,template,bytes(2),1,0,0,(durability,)*3,bytes(4),None,bytes((0,0,int(definition.get('special','0')=='1')))) for n in range(count)]
        try:merged,new_assignments=completion.merge_scope(db,account,(*items.values(),*additions),before,origin='clan-assault:'+str(event),limit=capacity)
        except ValueError:continue
        assignments.update(new_assignments)
        items={i.instance_id:i for i in merged};next_id+=count;completed.append(event)
    if not completed:return ()
    packets=encode_private_warehouse_snapshot(items.values())
    encoded=[(account,i.instance_id,encode_item_list(0,(i,))) for i in items.values()]
    completion.persist_scope(db,account,before,items.values(),assignments)
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(account,next_id))
    db.executemany('UPDATE clan_assault_prizes SET delivered=1 WHERE event_id=? AND account=?',[(e,account) for e in completed])
    return packets
