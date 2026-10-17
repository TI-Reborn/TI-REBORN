"""Private owner commands and shared hourly clan benefits maintenance."""
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import time

from tio import clan_benefits as benefits
from tio.clans import membership,ClanRejected
from tio.protocol.chat import encode_system_message

ROOT=Path(__file__).resolve().parents[1]
REQUEST=re.compile(r'[A-Za-z0-9_-]{16,64}\Z')

def number(text,maximum=0xffffffff):
    if not re.fullmatch('[0-9]{1,10}',text):raise ClanRejected('Нужно целое число без знака')
    return benefits.integer(int(text),maximum)

def next_default(town,now):
    config=json.loads((ROOT/'config/territories.json').read_text())
    row=next((r for r in config['territories'] if r['id']==town and r['enabled'] and r['kind']=='base'),None)
    if row is None:raise ClanRejected('Неизвестная действующая база')
    first=int(datetime.fromisoformat(row['first_start_utc'].replace('Z','+00:00')).timestamp())
    return first+max(0,(now-first)//config['period_seconds'])*config['period_seconds']

def schedule(db,town,now):
    default=next_default(town,now)
    period=json.loads((ROOT/'config/territories.json').read_text())['period_seconds']
    for _ in range(3):
        options=benefits.schedule_options(default)
        born=benefits.exists(db,'warfare_events') and db.execute('SELECT 1 FROM warfare_events WHERE town=? AND starts IN ('+','.join('?' for _ in options)+')',(town,*options)).fetchone()
        if not born and any(n>now for n in options):return default,options
        default+=period
    raise ClanRejected('Следующее окно штурма недоступно')

def command(db,account,text,*,city_idle,now=None):
    tokens=text.split()
    if not tokens or tokens[0]!='!base':return None
    now=int(time.time() if now is None else now)
    clan=membership(db,account)
    if clan is None:raise ClanRejected('Для управления базами нужен клан')
    if not city_idle:raise ClanRejected('Управление базами доступно в городе вне боя и заявок')
    if len(tokens)<=2 and (len(tokens)==1 or tokens[1]=='help'):
        lines=['!base tax BASE PERCENT REVISION; !base time BASE HOUR; !base fund EVENT CREDITS ID',
            'Часы штурма: 12, 15, 18, 21 UTC. Фонд обороны списывается из сейфа клана.']
        if benefits.exists(db,'territory_claims'):
            for town,tax,revision in db.execute('SELECT location,tax_percent,revision FROM territory_claims WHERE owner_clan=? ORDER BY location',(clan['id'],)):
                try:
                    default,options=schedule(db,town,now)
                    date=datetime.fromtimestamp(default,timezone.utc).strftime('%Y-%m-%d')
                    lines.append(f'База {town}: налог {tax}%, ревизия {revision}; следующий день штурма {date} UTC.')
                except ClanRejected:continue
        return tuple(encode_system_message(4,b'Base',line) for line in lines)
    if tokens[1]=='tax' and len(tokens)==5:
        town,tax,revision=number(tokens[2]),number(tokens[3],10),number(tokens[4])
        new=benefits.set_base_tax(db,account,town,tax,expected_revision=revision)
        line=f'База {town}: налог {tax}%, ревизия {new}.'
    elif tokens[1]=='time' and len(tokens)==4:
        town,hour=number(tokens[2]),number(tokens[3],23)
        default,_=schedule(db,town,now);chosen=default//86400*86400+hour*3600
        result=benefits.set_next_assault(db,account,town,default,chosen,now=now)
        line='Штурм назначен на '+datetime.fromtimestamp(result,timezone.utc).strftime('%Y-%m-%d %H:%M UTC')+'.'
    elif tokens[1]=='fund' and len(tokens)==5:
        if REQUEST.fullmatch(tokens[4]) is None:raise ClanRejected('ID операции: 16–64 латинских букв, цифр, _ или -')
        result=benefits.fund_defense(db,account,tokens[2],number(tokens[3]),tokens[4])
        line=f"Фонд обороны: {result['escrow']} кредитов."
    else:raise ClanRejected('Неверная команда управления базой; !base help')
    return (encode_system_message(4,b'Base',line),)

def maintenance(db,*,now=None):
    """Minute poll: actual elapsed hours decay; eligible finished weeks close."""
    now=int(time.time() if now is None else now)
    benefits.decay(db,now=now)
    current=benefits.week_start(now)
    candidates={current-benefits.WEEK}
    if benefits.exists(db,'clan_assault_totals'):
        candidates.update(r[0] for r in db.execute('''SELECT DISTINCT t.week_start FROM clan_assault_totals t
            WHERE t.week_start<? AND NOT EXISTS(SELECT 1 FROM clan_weeks w WHERE w.week_start=t.week_start)
            ORDER BY t.week_start LIMIT 8''',(current,)))
    for week in sorted(candidates)[:8]:
        # Unfinished authoritative events keep their week pending. Isolate a
        # rejected week so partial prize writes cannot leak into another one.
        db.execute('SAVEPOINT clan_week_poll')
        try:benefits.close_week(db,week,now=now)
        except ClanRejected:db.execute('ROLLBACK TO clan_week_poll')
        finally:db.execute('RELEASE clan_week_poll')

def prizes(session):
    from tio.db_transaction import transaction
    from tio.services import power
    from .economy_runtime import city_idle
    if not city_idle(session):return ()
    with session.router.team_arena.lock,transaction(session.database) as db:
        if not city_idle(session):return ()
        return benefits.deliver_prizes(db,session.account,capacity=session.catalogs.warehouse_capacity+power(db,session.account,1))
