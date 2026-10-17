"""Public social views and accepted clan departures on shared SQLite authority.

No backfill from old clan ledger, no account deletion, and no foreign prize
flush. Clan duration is explicit server policy; alliance three days is manual p20.
"""
import json
import math
from pathlib import Path
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def write(db):
    if not db.in_transaction: raise ValueError('Social completion requires authoritative transaction')


def exists(db, table):
    return bool(db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone())


def clock(now=None):
    stamp = time.time() if now is None else now
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0 <= stamp < 2**53:
        raise ValueError('Invalid authoritative server clock')
    return int(stamp)


def policy():
    p=json.loads((ROOT/'config/social_completion.json').read_text(encoding='utf-8'))
    if p['version']!=1 or type(p['clan_rejoin_seconds']) is not int or not 1 <= p['clan_rejoin_seconds'] <= 7*86400:
        raise ValueError('Invalid bounded social server policy')
    if p['clan_rejoin_reasons']!=['leave','kick','dissolve'] or p['legacy_cooldown_backfill'] is not False:
        raise ValueError('Invalid departure or legacy policy')
    return p


def schema(db):
    write(db)
    db.execute('''CREATE TABLE IF NOT EXISTS clan_player_cooldowns (
        account TEXT PRIMARY KEY,until INTEGER NOT NULL,started INTEGER NOT NULL,
        clan_id INTEGER NOT NULL,reason TEXT NOT NULL,ledger_id INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS social_completion_receipts (
        operation TEXT NOT NULL,identity TEXT NOT NULL,account TEXT NOT NULL,request TEXT NOT NULL,
        result TEXT NOT NULL,PRIMARY KEY(operation,identity,account))''')
    for operation in ('UPDATE','DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS social_receipts_no_{operation.lower()} BEFORE {operation} ON social_completion_receipts BEGIN SELECT RAISE(ABORT,'Social receipts are immutable'); END")


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def prior(db, operation, identity, account, request):
    if not exists(db,'social_completion_receipts'):return None
    row=db.execute('SELECT request,result FROM social_completion_receipts WHERE operation=? AND identity=? AND account=?',(operation,identity,account)).fetchone()
    if row:
        if row[0]!=canonical(request):raise ValueError('Conflicting social operation retry')
        return json.loads(row[1])


def receipt(db, operation, identity, account, request, result):
    schema(db)
    db.execute('INSERT INTO social_completion_receipts VALUES (?,?,?,?,?)',(operation,identity,account,canonical(request),canonical(result)))
    return result


def clan_delay(db, account, *, now=None):
    write(db);stamp=clock(now)
    row=db.execute('SELECT until,started,clan_id,reason FROM clan_player_cooldowns WHERE account=?',(account,)).fetchone() if exists(db,'clan_player_cooldowns') else None
    until=row[0] if row else None
    remaining=max(0,until-stamp) if until is not None else 0
    return dict(version=1,remaining_seconds=remaining,until=until if remaining else None,
                can_join=not remaining,rule='server_policy',duration_seconds=policy()['clan_rejoin_seconds'])


def require_join(db, account, *, now=None):
    delay=clan_delay(db,account,now=now)
    if not delay['can_join']:
        raise ValueError(f"До вступления в клан осталось {math.ceil(delay['remaining_seconds']/3600)} ч.")


def departed(db, account, clan, reason, *, now=None):
    """Called after the accepted native departure/ledger insert, in its same TX."""
    schema(db);stamp=clock(now)
    if reason not in policy()['clan_rejoin_reasons']:raise ValueError('Invalid accepted departure')
    row=db.execute('SELECT id,operation,account,detail FROM clan_ledger WHERE clan_id=? ORDER BY id DESC LIMIT 1',(clan,)).fetchone()
    if row is None or row[1]!=reason or (reason!='dissolve' and row[3]!=account) or (reason=='dissolve' and row[2]!=account):
        raise ValueError('Accepted departure ledger required')
    previous=db.execute('SELECT until,ledger_id FROM clan_player_cooldowns WHERE account=?',(account,)).fetchone()
    if previous and previous[1]==row[0]:return clan_delay(db,account,now=stamp)
    until=max(previous[0] if previous else 0,stamp+policy()['clan_rejoin_seconds'])
    db.execute('INSERT INTO clan_player_cooldowns VALUES (?,?,?,?,?,?) ON CONFLICT(account) DO UPDATE SET until=excluded.until,started=excluded.started,clan_id=excluded.clan_id,reason=excluded.reason,ledger_id=excluded.ledger_id',
               (account,until,stamp,clan,reason,row[0]))
    return clan_delay(db,account,now=stamp)


def joined(db, account, clan, inviter, expiry):
    identity=canonical(dict(clan=clan,inviter=inviter,expiry=expiry))
    return receipt(db,'clan_join',identity,account,dict(clan=clan),dict(clan=clan))


def join_replay(db, account, clan):
    if not exists(db,'social_completion_receipts'):return False
    return any(json.loads(raw)['clan']==clan for raw, in db.execute('SELECT result FROM social_completion_receipts WHERE operation=? AND account=?',('clan_join',account)))


def public_achievements(db, target_name, caller, *, catalog):
    """No snapshots/counter update, private bodies, delivery flags, or flush."""
    write(db)
    if not isinstance(target_name,str) or not target_name or len(target_name)>128 or any(ord(c)<32 for c in target_name):
        raise ValueError('Некорректное имя персонажа')
    row=db.execute('SELECT account,name FROM characters WHERE name_key=?',(unicodedata.normalize('NFKC',target_name).casefold(),)).fetchone() if exists(db,'characters') else None
    if row is None:raise ValueError('Персонаж не найден')
    owner,name=row
    if owner==caller:raise ValueError('Private achievements must use the authenticated owner path')
    from .clans import membership
    clan=membership(db,caller)
    if clan and bytes(clan['name'])==bytes(name):
        raise ValueError('Просмотр этого имени через клиент недоступен; оно совпадает с названием вашего клана')
    earned={identity:json.loads(body) for identity,body in db.execute('SELECT id,body FROM achievement_awards WHERE account=?',(owner,))} if exists(db,'achievement_awards') else {}
    records=tuple(dict(id=(earned.get(r['id']) or r)['id'],level=(earned.get(r['id']) or r)['level'],earned=int(r['id'] in earned)) for r in catalog)
    return name.decode('cp1251'),records


def alliance_status(db, account, *, now=None):
    write(db);stamp=clock(now)
    from .clans import membership
    from .alliances import _row,_clans
    clan=membership(db,account)
    alliance=_row(db,clan['id']) if clan else None
    if not alliance or alliance['state']=='dissolved':return None
    cohort=_clans(db,alliance)
    remaining=max(0,math.ceil(alliance['dissolution_until']-stamp)) if alliance['state']=='dissolving' else 0
    return dict(id=alliance['id'],name=bytes(alliance['name']).decode('cp1251'),state=alliance['state'] if remaining or alliance['state']=='active' else 'expired',
                dissolution_until=math.ceil(alliance['dissolution_until']) if remaining else None,
                remaining_seconds=remaining,can_cancel=bool(remaining and clan['id']==alliance['leading_clan'] and clan['leader']==account),
                clans=[dict(id=c['id'],name=c['name'].decode('cp1251')) for c in cohort])


def alliance_cancel(db, path, account, confirmation, *, now=None):
    """Explicit name-confirmed cancellation; AF0C retries never toggle state."""
    write(db);stamp=clock(now)
    from .clans import require
    from .alliances import AlliancesStore,_row
    clan=require(db,account,leader=True);alliance=_row(db,clan['id'])
    if alliance is None or alliance['leading_clan']!=clan['id']:raise ValueError('Отмена доступна главе ведущего клана альянса')
    if confirmation!=bytes(alliance['name']).decode('cp1251'):raise ValueError('Для отмены укажите полное имя своего альянса')
    row=db.execute("SELECT id FROM alliance_ledger WHERE alliance_id=? AND operation='dissolve' ORDER BY id DESC LIMIT 1",(alliance['id'],)).fetchone()
    if row is None:raise ValueError('Нет подтверждённого решения о роспуске')
    identity=f"{alliance['id']}:{row[0]}";request=dict(alliance=alliance['id'],dissolution=row[0],name=confirmation)
    old=prior(db,'alliance_cancel',identity,account,request)
    if old is not None:return dict(old,replayed=True,status=alliance_status(db,account,now=stamp))
    if alliance['state']!='dissolving' or alliance['dissolution_until']<=stamp:raise ValueError('Трёхдневный срок отмены роспуска истёк или роспуск не назначен')
    store=AlliancesStore(path,clock=lambda:stamp)
    store.restore(account)
    result=receipt(db,'alliance_cancel',identity,account,request,dict(alliance_id=alliance['id'],credits_delta=0,influence_delta=0))
    return dict(result,replayed=False,status=alliance_status(db,account,now=stamp))
