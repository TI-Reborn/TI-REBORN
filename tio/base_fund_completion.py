"""Personal defender-fund contributions; callers own shared lock and SQLite TX.

Manual printed86 confirms any willing player and50/30/20. Registration cutoff,
fewer winners, integer rounding and no-winner refunds remain explicit policy.
Legacy clan-funded escrow and accepted receipts keep their original payer.
"""
import json
import math
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
MAX=0xffffffff


def benefits():
    from . import clan_benefits
    return clan_benefits


def write(db):
    if not db.in_transaction:raise RuntimeError('Defender fund requires authoritative transaction')


def clock(now=None):
    stamp=time.time() if now is None else now
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=stamp<2**53:
        raise benefits().ClanRejected('Некорректные серверные часы')
    return int(stamp)


def schema(db):
    write(db)
    db.execute('''CREATE TABLE IF NOT EXISTS base_fund_personal_contributions(
        account TEXT NOT NULL,identity TEXT NOT NULL,event_id TEXT NOT NULL,
        amount INTEGER NOT NULL CHECK(amount BETWEEN 1 AND 4294967295),created INTEGER NOT NULL,
        PRIMARY KEY(account,identity))''')
    db.execute('''CREATE TABLE IF NOT EXISTS base_fund_refund_escrow(
        event_id TEXT NOT NULL,account TEXT NOT NULL,amount INTEGER NOT NULL CHECK(amount BETWEEN 1 AND 4294967295),
        claimed INTEGER NOT NULL DEFAULT 0 CHECK(claimed IN (0,1)),PRIMARY KEY(event_id,account))''')
    for verb in ('UPDATE','DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS base_fund_personal_no_{verb.lower()} BEFORE {verb} ON base_fund_personal_contributions BEGIN SELECT RAISE(ABORT,'Accepted defender donations are immutable'); END")
    db.execute("CREATE TRIGGER IF NOT EXISTS base_fund_refund_no_rewrite BEFORE UPDATE ON base_fund_refund_escrow WHEN NEW.event_id<>OLD.event_id OR NEW.account<>OLD.account OR NEW.amount<>OLD.amount OR NEW.claimed<>1 OR OLD.claimed<>0 BEGIN SELECT RAISE(ABORT,'Refund escrow may only be claimed once'); END")
    db.execute("CREATE TRIGGER IF NOT EXISTS base_fund_refund_no_delete BEFORE DELETE ON base_fund_refund_escrow BEGIN SELECT RAISE(ABORT,'Refund escrow is durable'); END")


def owner_city(db,account):
    b=benefits();write(db)
    if not isinstance(account,str) or not account or not b.exists(db,'characters') or not db.execute('SELECT 1 FROM characters WHERE account=? AND slot=1',(account,)).fetchone():raise b.ClanRejected('Нет сохранённого персонажа')
    wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(account,)).fetchone() if b.exists(db,'wallets') else None
    if wallet is None:raise b.ClanRejected('Нет личного кошелька')
    from .cities import CITIES
    town=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone() if b.exists(db,'character_locations') else None
    if town is None or town[0] not in CITIES:raise b.ClanRejected('Взносы доступны в городе')
    for table in ('map_journeys','battle_checkpoint_members','battle_settlement_jobs'):
        if b.exists(db,table) and db.execute(f'SELECT 1 FROM {table} WHERE account=?',(account,)).fetchone():raise b.ClanRejected('Завершите путь или бой')
    if b.exists(db,'world_prison') and db.execute('SELECT 1 FROM world_prison WHERE account=? AND remaining>0',(account,)).fetchone():raise b.ClanRejected('Взносы недоступны в тюрьме')
    return wallet[0]


def eligible_event(db,event_id,*,now=None):
    """Readonly authoritative eligibility; no clan membership is required."""
    b=benefits();write(db);b.key(event_id);stamp=clock(now)
    row=db.execute('SELECT town,phase,starts,claim,finalized FROM warfare_events WHERE id=?',(event_id,)).fetchone() if b.exists(db,'warfare_events') else None
    if row is None or row[1]!='REGISTRATION' or row[2]<=stamp or row[4]:return None
    supported=json.loads((ROOT/'config/territories.json').read_text(encoding='utf-8'))['territories']
    if not any(r['id']==row[0] and r['enabled'] and r['kind']=='base' for r in supported):return None
    frozen=json.loads(row[3]);clan=frozen.get('owner_clan')
    if type(clan) is not int or not 0<clan<=MAX or frozen.get('location')!=row[0] or not db.execute('SELECT 1 FROM clans WHERE id=?',(clan,)).fetchone():return None
    claim=db.execute('SELECT owner_clan,revision FROM territory_claims WHERE location=?',(row[0],)).fetchone() if b.exists(db,'territory_claims') else None
    if claim is None or claim!=(clan,frozen.get('revision')):return None
    fund=db.execute('SELECT clan_id,credits,settled FROM clan_defense_funds WHERE event_id=?',(event_id,)).fetchone() if b.exists(db,'clan_defense_funds') else None
    if fund and (fund[0]!=clan or fund[2] or fund[1]>=MAX):return None
    return dict(owner_clan=clan,town=row[0],starts=row[2],held=fund[1] if fund else 0)


def donate(db,account,event_id,amount,identity,*,now=None):
    b=benefits();b.write(db);b.integer(amount);b.key(event_id);b.key(identity)
    request=b.canonical(dict(event=event_id,amount=amount));old=b.prior(db,'fund',identity,account,request)
    if old is not None:return old  # Accepted legacy receipts keep their payer.
    owner_city(db,account);event=eligible_event(db,event_id,now=now)
    if event is None:raise b.ClanRejected('Взнос доступен до начала штурма действующей базы')
    if not amount or event['held']+amount>MAX:raise b.ClanRejected('Фонд должен быть положительным и не переполняться')
    schema(db)
    if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',(amount,account,amount)).rowcount!=1:raise b.ClanRejected('Недостаточно личных кредитов')
    db.execute('INSERT INTO clan_defense_funds VALUES (?,?,?,0) ON CONFLICT(event_id) DO UPDATE SET credits=credits+excluded.credits',(event_id,event['owner_clan'],amount))
    db.execute('INSERT INTO base_fund_personal_contributions VALUES (?,?,?,?,?)',(account,identity,event_id,amount,clock(now)))
    b.record(db,event['owner_clan'],account,'defense_fund_personal',amount)
    return b.receipt(db,'fund',identity,account,request,dict(event_id=event_id,escrow=amount,payer='player_credits',charged_credits=amount))


def refund_balance(db,account):
    b=benefits();write(db)
    return db.execute('SELECT COALESCE(SUM(amount),0) FROM base_fund_refund_escrow WHERE account=? AND claimed=0',(account,)).fetchone()[0] if b.exists(db,'base_fund_refund_escrow') else 0


def claim_refunds(db,account,*,city_required=True):
    """Durable wallet-overflow refunds: no partial claim or duplicate credit."""
    write(db)
    if city_required:owner_city(db,account)
    b=benefits();paid=0
    if b.exists(db,'base_fund_refund_escrow'):
        for event,amount in db.execute('SELECT event_id,amount FROM base_fund_refund_escrow WHERE account=? AND claimed=0 ORDER BY event_id LIMIT 100',(account,)).fetchall():
            if db.execute('UPDATE wallets SET credits=credits+? WHERE account=? AND credits<=?',(amount,account,MAX-amount)).rowcount!=1:continue
            if db.execute('UPDATE base_fund_refund_escrow SET claimed=1 WHERE event_id=? AND account=? AND claimed=0',(event,account)).rowcount!=1:raise b.ClanRejected('Квитанция возврата изменилась')
            paid+=amount
    return dict(credited=paid,pending=refund_balance(db,account))


def settle(db,event_id,fund,ranked):
    """Called only after actual finalized score validation, inside its same TX."""
    b=benefits();write(db);schema(db);payouts={};refunds={}
    if ranked:
        weights=[5,3,2][:len(ranked)];total=sum(weights)
        payouts={clan:fund[1]*weight//total for (clan,_),weight in zip(ranked,weights)}
        for clan,_ in ranked[:fund[1]-sum(payouts.values())]:payouts[clan]+=1
    else:
        for account,identity,amount in db.execute('SELECT account,identity,amount FROM base_fund_personal_contributions WHERE event_id=?',(event_id,)):
            accepted=b.prior(db,'fund',identity,account,b.canonical(dict(event=event_id,amount=amount)))
            if not accepted or accepted.get('payer')!='player_credits' or accepted.get('charged_credits')!=amount or accepted.get('escrow')!=amount:
                raise b.ClanRejected('Нет подтверждённой квитанции личного взноса')
        personal=dict(db.execute('SELECT account,SUM(amount) FROM base_fund_personal_contributions WHERE event_id=? GROUP BY account',(event_id,)))
        legacy=fund[1]-sum(personal.values())
        if legacy<0:raise b.ClanRejected('Сумма личных вкладов превышает сохранённый фонд')
        if legacy:payouts[fund[0]]=legacy
        for account,amount in personal.items():
            db.execute('INSERT INTO base_fund_refund_escrow VALUES (?,?,?,0)',(event_id,account,amount))
            refunds[account]=amount
            # The accepted finalization returns escrow to the original payer.
            # Wallet overflow remains pending; live actions claim under city gate.
            claim_refunds(db,account,city_required=False)
    for clan,amount in payouts.items():
        if db.execute('UPDATE clans SET credits=credits+?,revision=revision+1 WHERE id=? AND credits<=?',(amount,clan,MAX-amount)).rowcount!=1:raise b.ClanRejected('Сейф получателя фонда переполнен')
    db.execute('UPDATE clan_defense_funds SET settled=1 WHERE event_id=? AND settled=0',(event_id,))
    return payouts,refunds
