"""Shared currency/securities, physical item marks and real-payment order ledger.

DB helpers require the caller's gameplay transaction. Provider IO happens outside
SQLite locks. No starting Gold, payment success URL or unsigned webhook can mint
Gold. Pending payable preserves an actually paid amount when a wallet is full.
"""
from contextlib import closing
from dataclasses import dataclass,replace
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse,urlencode
from urllib.request import Request,urlopen
from typing import Protocol
import hashlib,hmac,json,os,re,secrets,time,uuid

from .db_transaction import connect,transaction,current
from .protocol.item_list import ItemRecord,decode_item_list,encode_item_list
from .item_ids import next_item_id

ROOT=Path(__file__).resolve().parents[1]
MAX=0xffffffff


class BankRejected(ValueError):pass


@lru_cache(maxsize=1)
def policy():
    p=json.loads((ROOT/'config/bank_economy.json').read_text(encoding='utf-8'))
    if p['version']!=1 or p['gold_to_credits']!=100 or p['marks']['credits_per_day']!=100:raise ValueError('Invalid recovered economy policy')
    if not 1<=p['bonds']['sale_last_day']<p['bonds']['redemption_day']<=28:raise ValueError('Invalid monthly bond calendar')
    for section,keys in (('stocks',('initial_credits','daily_rise_credits','history_points')),('bonds',('credits_each','initial_redemption_credits','monthly_rise_credits','history_points')),('marks',('maximum_days','pin_iterations','pin_failures','pin_lock_seconds'))):
        if any(type(p[section][k]) is not int or not 1<=p[section][k]<=MAX for k in keys):raise ValueError('Invalid bounded economy quantity')
    days=p['marks']['window_days']
    if type(days) is not int or not 1<=days<=p['marks']['maximum_days']:
        raise ValueError('Invalid native mark duration')
    return p


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def integer(value,maximum=MAX,*,positive=False):
    if type(value) is not int or not int(positive)<=value<=maximum:raise BankRejected('Недопустимое количество или сумма')
    return value


def identity(value):
    if not isinstance(value,str) or not 1<=len(value)<=160 or any(ord(c)<32 for c in value):raise BankRejected('Недопустимый идентификатор операции')
    return value


def table(db,name):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(name,)).fetchone())


def schema(db):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS bank_economy_receipts(operation TEXT,identity TEXT,account TEXT,
            request TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(operation,identity,account))''',
        'CREATE TABLE IF NOT EXISTS bank_securities(account TEXT PRIMARY KEY,stocks INTEGER NOT NULL DEFAULT 0,bonds INTEGER NOT NULL DEFAULT 0)',
        'CREATE TABLE IF NOT EXISTS bank_quotes(kind TEXT PRIMARY KEY,price INTEGER NOT NULL,period INTEGER NOT NULL)',
        'CREATE TABLE IF NOT EXISTS bank_quote_history(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,observed INTEGER NOT NULL,price INTEGER NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS bank_payment_orders(id TEXT PRIMARY KEY,account TEXT NOT NULL,identity TEXT NOT NULL,
            provider TEXT NOT NULL,gold INTEGER NOT NULL,amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,
            state TEXT NOT NULL,session_id TEXT UNIQUE,url TEXT,created INTEGER NOT NULL,request TEXT NOT NULL,
            UNIQUE(account,identity))''',
        '''CREATE TABLE IF NOT EXISTS bank_payment_events(provider TEXT,event_id TEXT,order_id TEXT NOT NULL,
            request TEXT NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(provider,event_id))''',
        'CREATE TABLE IF NOT EXISTS bank_gold_payables(account TEXT PRIMARY KEY,gold INTEGER NOT NULL CHECK(gold>=0))',
        '''CREATE TABLE IF NOT EXISTS bank_item_marks(id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL,
            original_instance INTEGER NOT NULL,holder TEXT NOT NULL,current_instance INTEGER NOT NULL,template INTEGER NOT NULL,
            expires INTEGER NOT NULL,salt BLOB NOT NULL,pin_hash BLOB NOT NULL,state TEXT NOT NULL,
            failures INTEGER NOT NULL DEFAULT 0,locked_until INTEGER NOT NULL DEFAULT 0)''',
    ):db.execute(sql)
    for target in ('bank_economy_receipts','bank_payment_events'):
        for operation in ('UPDATE','DELETE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS {target}_no_{operation.lower()} BEFORE {operation} ON {target}
                BEGIN SELECT RAISE(ABORT,'Bank audit is immutable'); END''')


def write(db):
    if not db.in_transaction:raise RuntimeError('Bank mutation requires the gameplay transaction')
    schema(db)


def owner(db,account):
    if not isinstance(account,str) or not account:raise BankRejected('Аккаунт не указан')
    row=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
    if row is None or not db.execute('SELECT 1 FROM characters WHERE account=?',(account,)).fetchone():raise BankRejected('Нужен существующий персонаж и кошелёк')
    return row


def prior(db,operation,key,account,request):
    row=db.execute('SELECT request,receipt FROM bank_economy_receipts WHERE operation=? AND identity=? AND account=?',(operation,identity(key),account)).fetchone()
    if row:
        if row[0]!=request:raise BankRejected('Повтор операции отличается от сохранённой')
        return json.loads(row[1])


def receipt(db,operation,key,account,request,result):
    body=canonical(result);db.execute('INSERT INTO bank_economy_receipts VALUES (?,?,?,?,?)',(operation,identity(key),account,request,body));return json.loads(body)


def convert_gold(db,account,gold,key):
    raise BankRejected('Золото выведено из экономики; обмен закрыт')


def _quote(db,kind,now):
    write(db);stamp=integer(int(time.time() if now is None else now),2**53);p=policy()[kind]
    date=datetime.fromtimestamp(stamp,timezone.utc)
    period=stamp//86400 if kind=='stocks' else date.year*12+date.month
    row=db.execute('SELECT price,period FROM bank_quotes WHERE kind=?',(kind,)).fetchone()
    if row is None:
        price=p['initial_credits'] if kind=='stocks' else p['initial_redemption_credits']
        db.execute('INSERT INTO bank_quotes VALUES (?,?,?)',(kind,price,period));changed=True
    else:
        price,previous=row;steps=max(0,period-previous);rise=p['daily_rise_credits'] if kind=='stocks' else p['monthly_rise_credits']
        price=min(MAX,price+steps*rise);changed=bool(steps)
        if steps:db.execute('UPDATE bank_quotes SET price=?,period=? WHERE kind=?',(price,period,kind))
    if changed:
        db.execute('INSERT INTO bank_quote_history(kind,observed,price) VALUES (?,?,?)',(kind,stamp,price))
        db.execute('DELETE FROM bank_quote_history WHERE kind=? AND id NOT IN (SELECT id FROM bank_quote_history WHERE kind=? ORDER BY id DESC LIMIT ?)',(kind,kind,p['history_points']))
    return price,date


def stock_quote(db,*,now=None):
    price,_=_quote(db,'stocks',now);return dict(price=price,currency='credits')


def bond_quote(db,*,now=None):
    price,date=_quote(db,'bonds',now);p=policy()['bonds'];month=date.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    return dict(price_credits=p['credits_each'],redemption_credits=price,sale_open=date.day<=p['sale_last_day'],redemption_open=date.day==p['redemption_day'],
                sale_starts=int(month.timestamp()),sale_ends=int(month.replace(day=p['sale_last_day']+1).timestamp()),redemption_starts=int(month.replace(day=p['redemption_day']).timestamp()),redemption_ends=int(month.replace(day=p['redemption_day']+1).timestamp()))


def securities_trade(db,account,kind,operation,count,key,*,quote,now=None):
    write(db);wallet=owner(db,account);integer(count,positive=True)
    if kind not in ('stocks','bonds') or operation not in ('buy','sell') or kind=='bonds' and operation=='sell' and quote is None:raise BankRejected('Некорректная операция с бумагами')
    integer(quote,positive=True);request=canonical(dict(kind=kind,operation=operation,count=count,quote=quote));old=prior(db,'securities',key,account,request)
    if old is not None:return old
    db.execute('INSERT OR IGNORE INTO bank_securities(account) VALUES (?)',(account,))
    held=db.execute(f'SELECT {kind} FROM bank_securities WHERE account=?',(account,)).fetchone()[0]
    price,_=_quote(db,kind,now)
    if kind=='bonds':
        calendar=bond_quote(db,now=now)
        if not calendar['sale_open' if operation=='buy' else 'redemption_open']:raise BankRejected('Период продажи или погашения векселей закрыт')
        price=calendar['price_credits'] if operation=='buy' else calendar['redemption_credits']
    if quote!=price:raise BankRejected('Котировка изменилась: обновите её')
    amount=count*price
    if operation=='buy':
        currency='credits';balance=wallet[0]
        if held+count>MAX or balance<amount:raise BankRejected('Недостаточно средств или переполнение бумаг')
        db.execute(f'UPDATE wallets SET {currency}={currency}-? WHERE account=?',(amount,account));after=held+count
    else:
        if held<count or wallet[0]+amount>MAX:raise BankRejected('Недостаточно бумаг или переполнение кредитов')
        db.execute('UPDATE wallets SET credits=credits+? WHERE account=?',(amount,account));after=held-count
    db.execute(f'UPDATE bank_securities SET {kind}=? WHERE account=?',(after,account))
    return receipt(db,'securities',key,account,request,dict(kind=kind,operation=operation,count=count,amount=amount,balance=after))


def quote_history(db,kind,*,now=None):
    if kind not in ('stocks','bonds'):raise BankRejected('Неизвестный график')
    _quote(db,kind,now);return tuple(dict(observed=t,price=p) for t,p in db.execute('SELECT observed,price FROM bank_quote_history WHERE kind=? ORDER BY id',(kind,)))


def project_assets(db,account,assets):
    row=db.execute('SELECT bonds,stocks FROM bank_securities WHERE account=?',(account,)).fetchone() if table(db,'bank_securities') else None
    return replace(assets,spectra_bonds=row[0] if row else 0,spectra_stock=row[1] if row else 0)


@dataclass(frozen=True)
class PaymentConfirmation:
    provider:str
    event_id:str
    order_id:str
    session_id:str
    amount_minor:int
    currency:str
    livemode:bool


class PaymentProvider(Protocol):
    name:str
    config:dict
    def status(self)->dict:...
    def create_checkout(self,order:dict)->dict:...
    def verify_callback(self,body:bytes,headers:dict,*,now=None)->PaymentConfirmation|None:...


def https_url(value,*,host=None):
    if not isinstance(value,str):raise BankRejected('Платёжный URL не настроен')
    parsed=urlparse(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or host and parsed.hostname!=host:raise BankRejected('Нужен разрешённый HTTPS платёжный URL')
    return value


class StripeCheckout:
    """Optional Stripe v1 Checkout adapter, selected only by merchant configuration."""
    name='stripe_checkout'
    def __init__(self,configuration=None,*,environ=None,transport=None):
        self.config={**policy()['provider'],**(configuration or {})};self.environ=os.environ if environ is None else environ;self.transport=transport or self._post

    def status(self):
        p=self.config;missing=[]
        if p.get('enabled') is not True or p.get('type')!=self.name:missing.append('provider selection')
        if not isinstance(p.get('currency'),str) or not re.fullmatch('[a-z]{3}',p['currency']):missing.append('currency')
        if type(p.get('minor_units_per_gold')) is not int or not 1<=p['minor_units_per_gold']<=MAX:missing.append('price')
        if type(p.get('require_livemode')) is not bool:missing.append('livemode')
        if type(p.get('maximum_gold')) is not int or not 1<=p['maximum_gold']<=100000:missing.append('maximum_gold')
        minimum=p.get('minimum_gold',1)
        if type(minimum) is not int or not 1<=minimum<=p.get('maximum_gold',0):missing.append('minimum_gold')
        if type(p.get('signature_tolerance_seconds')) is not int or not 1<=p['signature_tolerance_seconds']<=300:missing.append('signature tolerance')
        for field in ('success_url','cancel_url'):
            try:https_url(p.get(field))
            except BankRejected:missing.append(field)
        for field,prefix in (('secret_key_env','sk_live_' if p.get('require_livemode',True) else 'sk_'),('webhook_secret_env','whsec_')):
            if not isinstance(p.get(field),str) or not self.environ.get(p[field],'').startswith(prefix):missing.append(field)
        return dict(configured=not missing,provider=self.name,missing=missing)

    def ready(self):
        if not self.status()['configured']:raise BankRejected('Банк не настроен: нужен платёжный провайдер, цена и ключи')

    def _post(self,fields,order_id):
        p=self.config;data=urlencode(fields).encode();token=self.environ[p['secret_key_env']]
        request=Request('https://api.stripe.com/v1/checkout/sessions',data=data,method='POST',headers={'Authorization':'Bearer '+token,'Content-Type':'application/x-www-form-urlencoded','Idempotency-Key':'tio-gold-'+order_id})
        with urlopen(request,timeout=20) as response:
            raw=response.read(262145)
        if len(raw)>262144:raise BankRejected('Ответ платёжного провайдера слишком велик')
        return json.loads(raw)

    def create_checkout(self,order):
        self.ready();p=self.config
        fields={'mode':'payment','success_url':p['success_url'],'cancel_url':p['cancel_url'],'client_reference_id':order['id'],
            'metadata[tio_order]':order['id'],'line_items[0][quantity]':order['gold'],
            'line_items[0][price_data][currency]':order['currency'],'line_items[0][price_data][unit_amount]':order['amount_minor']//order['gold'],
            'line_items[0][price_data][product_data][name]':'Total Influence Gold'}
        result=self.transport(fields,order['id']);https_url(result.get('url'),host='checkout.stripe.com')
        if result.get('currency')!=order['currency'] or result.get('amount_total')!=order['amount_minor'] or bool(result.get('livemode'))!=p['require_livemode']:raise BankRejected('Провайдер вернул другую сумму, валюту или режим')
        if not isinstance(result.get('id'),str) or not result['id'].startswith('cs_live_' if p['require_livemode'] else 'cs_'):raise BankRejected('Недопустимая платёжная сессия')
        return dict(session_id=result['id'],url=result['url'])

    def verify_callback(self,body,headers,*,now=None):
        self.ready();p=self.config
        if not isinstance(body,bytes) or not 1<=len(body)<=262144:raise BankRejected('Недопустимое тело webhook')
        header=next((v for k,v in headers.items() if k.lower()=='stripe-signature'),'')
        if not isinstance(header,str) or len(header)>4096:raise BankRejected('Недопустимая подпись webhook')
        values={}
        for field in header.split(','):
            if '=' in field:
                k,v=field.split('=',1);values.setdefault(k,[]).append(v)
        try:stamp=int(values['t'][0])
        except (KeyError,ValueError):raise BankRejected('Нет времени подписи webhook')
        if len(values['t'])!=1 or abs(int(time.time() if now is None else now)-stamp)>p['signature_tolerance_seconds']:raise BankRejected('Подпись webhook устарела')
        expected=hmac.new(self.environ[p['webhook_secret_env']].encode(),str(stamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected,s) for s in values.get('v1',[]) if re.fullmatch('[a-f0-9]{64}',s)):raise BankRejected('Подпись webhook не подтверждена')
        try:event=json.loads(body)
        except (ValueError,UnicodeDecodeError) as e:raise BankRejected('Некорректный JSON webhook') from e
        if not isinstance(event,dict):raise BankRejected('Некорректное платёжное событие')
        if event.get('account') or event.get('livemode') is not p['require_livemode']:raise BankRejected('Чужой merchant или другой режим webhook')
        if event.get('type') not in ('checkout.session.completed','checkout.session.async_payment_succeeded'):return None
        try:session=event['data']['object']
        except (KeyError,TypeError) as e:raise BankRejected('Нет Checkout session в webhook') from e
        if not isinstance(session,dict):raise BankRejected('Некорректная Checkout session')
        if session.get('payment_status')!='paid':return None
        try:
            if session.get('object')!='checkout.session' or session.get('mode')!='payment':raise BankRejected('Ожидалась разовая оплата Checkout')
            order_id=identity(session['metadata']['tio_order'])
            if session.get('client_reference_id')!=order_id:raise BankRejected('Ссылка Checkout не совпала с серверным заказом')
            session_id=identity(session['id'])
            if not session_id.startswith('cs_live_' if p['require_livemode'] else 'cs_') or session.get('livemode') is not p['require_livemode']:raise BankRejected('Checkout session другого режима')
            return PaymentConfirmation(self.name,identity(event['id']),order_id,session_id,integer(session['amount_total'],2**53,positive=True),session['currency'],event['livemode'])
        except (KeyError,TypeError) as e:raise BankRejected('Нет обязательных данных paid Checkout session') from e


def collect_paid_gold(db,account):
    return 0  # retired payment receipts cannot mint currency


class BankStore:
    def __init__(self,path,*,provider=None,clock=time.time):
        self.path=Path(path);self.provider=provider if provider is not None else StripeCheckout() if policy()['provider'].get('type')=='stripe_checkout' else None;self.clock=clock
        with closing(connect(self.path)) as db,db:schema(db)

    def status(self):
        return dict(configured=False,provider=None,missing=['currency purchases retired'])

    def _order(self,db,account,order_id):
        row=db.execute('SELECT id,account,provider,gold,amount_minor,currency,state,session_id,url,created FROM bank_payment_orders WHERE id=? AND account=?',(order_id,account)).fetchone()
        if row is None:raise BankRejected('Платёжный заказ другого аккаунта или не найден')
        return dict(zip(('id','account','provider','gold','amount_minor','currency','state','session_id','url','created'),row))

    def create_order(self,account,gold,key):
        raise BankRejected('Покупка игровой валюты за реальные деньги отключена')

    def order(self,account,order_id):
        with closing(connect(self.path)) as db:return self._order(db,account,order_id)

    def callback(self,body,headers):
        raise BankRejected('Покупка игровой валюты за реальные деньги отключена')


def _pin(pin):
    lo,hi=policy()['marks']['pin_digits']
    if not isinstance(pin,str) or not re.fullmatch('[0-9]{'+str(lo)+','+str(hi)+'}',pin):raise BankRejected('PIN должен состоять из 4–12 цифр')
    return pin.encode()


def _hash(pin,salt):return hashlib.pbkdf2_hmac('sha256',_pin(pin),salt,policy()['marks']['pin_iterations'])


def _mark(db,account,mark_id):
    integer(mark_id,positive=True)
    row=db.execute('SELECT id,owner,holder,current_instance,expires,salt,pin_hash,state,failures,locked_until,template FROM bank_item_marks WHERE id=? AND owner=?',(mark_id,account)).fetchone()
    if row is None:raise BankRejected('Метка принадлежит другому аккаунту или не найдена')
    return dict(zip(('id','owner','holder','instance','expires','salt','pin_hash','state','failures','locked_until','template'),row))


def _check_pin(db,mark,pin,now):
    _pin(pin)
    if mark['locked_until']>now:return dict(rejected='PIN временно заблокирован',retry_after=mark['locked_until']-now)
    if not hmac.compare_digest(mark['pin_hash'],_hash(pin,mark['salt'])):
        failures=mark['failures']+1;lock=now+policy()['marks']['pin_lock_seconds'] if failures>=policy()['marks']['pin_failures'] else 0
        db.execute('UPDATE bank_item_marks SET failures=?,locked_until=? WHERE id=?',(0 if lock else failures,lock,mark['id']))
        return dict(rejected='Неверный PIN',retry_after=max(0,lock-now))
    db.execute('UPDATE bank_item_marks SET failures=0,locked_until=0 WHERE id=?',(mark['id'],));return None


def clan_mark_holder(clan_id: int) -> str:
    # NUL is forbidden in account logins, so shared custody cannot alias a player.
    return '\0clan:' + str(integer(clan_id, positive=True))


def _mark_clan(holder: str) -> int | None:
    return int(holder[6:]) if holder.startswith('\0clan:') else None


def _items(db,account):
    clan_id = _mark_clan(account)
    if clan_id is not None:
        from .clans import ClansStore
        return {key: (item, None, 0) for key, item in ClansStore._items(db, clan_id, 1).items()}
    from .market_inventory import owned
    owner(db,account);return owned(db,account)


def _save_item(db,account,item,pet,flag):
    if pet is None:db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=?',(encode_item_list(0,(item,)),account,item.instance_id))
    else:
        raw=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,pet)).fetchone()[0]
        _,items,_=decode_item_list(raw);packet=encode_item_list(pet,tuple(item if i.instance_id==item.instance_id else i for i in items),flag)
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(packet,account,pet))


def mark_item(db,account,instance,days,pin,key,*,now=None,allowed=True):
    write(db);owner(db,account);integer(instance,positive=True);integer(days,policy()['marks']['maximum_days'],positive=True);_pin(pin)
    if not allowed:raise BankRejected('Маркировка доступна в городе вне боя')
    request=canonical(dict(instance=instance,days=days));old=prior(db,'mark',key,account,request);stamp=int(time.time() if now is None else now)
    if old is not None:
        mark=_mark(db,account,old['mark_id']);failed=_check_pin(db,mark,pin,stamp)
        return failed if failed else old
    found=_items(db,account).get(instance)
    if found is None:raise BankRejected('Личный предмет не найден')
    item,pet,flag=found
    from .warehouse_completion import read_scope
    if pet is None and instance not in read_scope(db,account,required=True):raise BankRejected('Предмет находится на складе другого города')
    from .item_boosters import nontransferable
    if item.count!=1 or item.template_id in (1,2,51) or nontransferable(item.template_id) or any(item.unknown_bytes_02[2:]) or item.optional_u32 is not None:raise BankRejected('Стопки, деньги, арендованные и уже меченые предметы нельзя маркировать')
    cost=days*policy()['marks']['credits_per_day']
    if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',(cost,account,cost)).rowcount!=1:raise BankRejected('Недостаточно кредитов для метки')
    salt=secrets.token_bytes(16);digest=_hash(pin,salt);expires=stamp+days*86400
    row=db.execute("INSERT INTO bank_item_marks(owner,original_instance,holder,current_instance,template,expires,salt,pin_hash,state) VALUES (?,?,?,?,?,?,?,?,'active')",(account,instance,account,instance,item.template_id,expires,salt,digest));integer(row.lastrowid)
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',(account,instance+1))
    marked=replace(item,unknown_bytes_02=item.unknown_bytes_02[:2]+b'\x01'+item.unknown_bytes_02[3:])
    _save_item(db,account,marked,pet,flag)
    return receipt(db,'mark',key,account,request,dict(mark_id=row.lastrowid,charged=cost,expires=expires,changed_accounts=[account]))


def _move(db,mark,destination,*,clear=False):
    source=_items(db,mark['holder']);found=source.get(mark['instance'])
    if found is None:
        db.execute("UPDATE bank_item_marks SET state='destroyed' WHERE id=?",(mark['id'],));return None
    item,pet,flag=found
    if item.template_id!=mark['template'] or not item.unknown_bytes_02[2] or item.unknown_bytes_02[3]:raise BankRejected('Состояние меченого предмета изменилось')
    target=_items(db,destination)
    if destination==mark['holder']:
        if clear:_save_item(db,destination,replace(item,unknown_bytes_02=item.unknown_bytes_02[:2]+b'\0'+item.unknown_bytes_02[3:]),pet,flag)
        return item.instance_id
    clan_id = _mark_clan(mark['holder'])
    if clan_id is not None:
        db.execute('DELETE FROM clan_items WHERE clan_id=? AND kind=1 AND instance_id=?', (clan_id,item.instance_id))
        db.execute('UPDATE clans SET revision=revision+1 WHERE id=?', (clan_id,))
    else:
        db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',(mark['holder'],item.instance_id+1))
    if clan_id is None and pet is None:db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?',(mark['holder'],item.instance_id))
    elif clan_id is None:
        raw=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(mark['holder'],pet)).fetchone()[0]
        _,items,_=decode_item_list(raw);packet=encode_item_list(pet,tuple(i for i in items if i.instance_id!=item.instance_id),flag)
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(packet,mark['holder'],pet))
    new=next_item_id(db,destination,target)
    if not 0<new<0xffff0000:raise BankRejected('Исчерпаны идентификаторы предметов')
    received=replace(item,instance_id=new,unknown_u8_01=0,location_raw=0,unknown_bytes_02=item.unknown_bytes_02[:2]+(b'\0' if clear else b'\x01')+item.unknown_bytes_02[3:])
    from .warehouse_completion import stash
    stash(db,destination,(received,),origin='marked-item:'+str(mark['id']))
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(destination,new+1))
    db.execute('UPDATE bank_item_marks SET holder=?,current_instance=? WHERE id=?',(destination,new,mark['id']));return new


def lend_marked(db,account,mark_id,recipient,key,*,now=None,busy=()):
    write(db);mark=_mark(db,account,mark_id);owner(db,recipient);stamp=int(time.time() if now is None else now)
    request=canonical(dict(mark=mark_id,recipient=recipient));old=prior(db,'lend',key,account,request)
    if old is not None:return old
    if mark['state']!='active' or mark['expires']<=stamp or mark['holder']!=account or recipient==account:raise BankRejected('Эта метка недоступна для передачи')
    if account in busy or recipient in busy:raise BankRejected('Оба игрока должны находиться вне боя')
    instance=_move(db,mark,recipient)
    return receipt(db,'lend',key,account,request,dict(mark_id=mark_id,instance=instance,changed_accounts=[account,recipient],destroyed=instance is None))


def reclaim_marked(db,account,mark_id,pin,key,*,remove=False,now=None,busy=()):
    write(db);mark=_mark(db,account,mark_id);stamp=int(time.time() if now is None else now);request=canonical(dict(mark=mark_id,remove=bool(remove)))
    old=prior(db,'reclaim',key,account,request)
    if old is not None:return old
    if mark['state']!='active':raise BankRejected('Метка уже снята или предмет уничтожен')
    if account in busy or mark['holder'] in busy:raise BankRejected('Вернуть вещь можно после выхода обоих игроков из боя')
    failed=_check_pin(db,mark,pin,stamp)
    if failed:return failed  # Caller must commit this ordinary rejection, not raise inside its journal.
    previous=mark['holder'];instance=_move(db,mark,account,clear=remove)
    if remove and instance is not None:db.execute("UPDATE bank_item_marks SET state='removed' WHERE id=?",(mark_id,))
    return receipt(db,'reclaim',key,account,request,dict(mark_id=mark_id,instance=instance,removed=bool(remove),destroyed=instance is None,changed_accounts=sorted({account,previous})))


def expire_marks(db,*,now=None,busy=()):
    write(db);stamp=int(time.time() if now is None else now);changed=set()
    for mark_id,account in db.execute("SELECT id,owner FROM bank_item_marks WHERE state='active' AND expires<=? ORDER BY id",(stamp,)).fetchall():
        mark=_mark(db,account,mark_id)
        if account in busy or mark['holder'] in busy:continue
        previous=mark['holder'];instance=_move(db,mark,account,clear=True)
        if instance is not None:db.execute("UPDATE bank_item_marks SET state='expired' WHERE id=?",(mark_id,))
        changed.update((account,previous))
    return tuple(sorted(changed))


def marked_items(db,account):
    owner(db,account)
    if not table(db,'bank_item_marks'):return ()
    return tuple(dict(id=i,holder=h,instance=n,template=t,expires=e,state=s) for i,h,n,t,e,s in db.execute('SELECT id,holder,current_instance,template,expires,state FROM bank_item_marks WHERE owner=? ORDER BY id DESC LIMIT 100',(account,)))


_MARK_LIST_BIT = 1 << 31


def window_mark_rows(db, account: str, now: int) -> tuple[tuple[int, ItemRecord, int, str], ...]:
    owner(db, account)
    holdings = {}
    names = {}
    rows = []
    for mark_id, holder, instance, template, expires in db.execute(
            "SELECT id,holder,current_instance,template,expires FROM bank_item_marks "
            "WHERE owner=? AND state='active' ORDER BY id", (account,)):
        if holder not in holdings:
            holdings[holder] = _items(db, holder)
            # The native list hides rows whose holder name matches the player.
            names[holder] = ('Клановый склад' if _mark_clan(holder) is not None else
                             bytes(db.execute('SELECT name FROM characters WHERE account=? AND slot=1',
                                              (holder,)).fetchone()[0]).decode('cp1251'))
        found = holdings[holder].get(instance)
        if found is None:
            continue
        item = found[0]
        if item.template_id != template or not item.unknown_bytes_02[2] or item.unknown_bytes_02[3]:
            continue
        # The list references the mark, so a loan can change the physical ID.
        reference = _MARK_LIST_BIT + integer(mark_id, _MARK_LIST_BIT - 2, positive=True)
        rows.append((reference, item, max(0, min(MAX, expires - now)), names[holder]))
    return tuple(rows)


def _window_mark(db, account: str, reference: int) -> dict:
    held = db.execute(
        "SELECT id,owner FROM bank_item_marks WHERE holder=? AND current_instance=? AND state='active'",
        (account, reference)).fetchall()
    listed = db.execute(
        "SELECT id,owner FROM bank_item_marks WHERE id=? AND owner=? AND state='active'",
        (reference - _MARK_LIST_BIT, account)).fetchone() if reference >= _MARK_LIST_BIT else None
    candidates = set(held)
    if listed is not None:
        candidates.add(listed)
    if len(candidates) != 1:
        raise BankRejected('Активная метка не найдена или предмет выбран неоднозначно')
    mark_id, original = candidates.pop()
    return _mark(db, original, mark_id)


def remove_window_mark(db, account: str, reference: int, pin: str, key: str, *,
                       now: int, busy: set[str]) -> dict:
    mark = _window_mark(db, account, reference)
    if mark['owner'] != account:
        raise BankRejected('Только владелец может снять метку')
    return reclaim_marked(db, account, mark['id'], pin, key, remove=True, now=now, busy=busy)


def return_window_mark(db, account: str, reference: int, key: str, *, busy: set[str]) -> dict:
    write(db)
    mark = _window_mark(db, account, reference)
    original, holder = mark['owner'], mark['holder']
    if {original, holder} & busy:
        raise BankRejected('Вернуть вещь можно после выхода обоих игроков из боя')
    if holder == original:
        return dict(changed_accounts=(), destroyed=False)
    instance = _move(db, mark, original)
    return receipt(db, 'native_mark_return', key, account, canonical(dict(mark=mark['id'])),
                   dict(changed_accounts=sorted({original, holder}), destroyed=instance is None))


def assert_item_mutation(db,account,instance,operation):
    if operation in ('equip','use','repair','wear'):return
    if table(db,'bank_item_marks') and db.execute("SELECT 1 FROM bank_item_marks WHERE holder=? AND current_instance=? AND state='active'",(account,instance)).fetchone():raise BankRejected('Меченую вещь нельзя продавать, уничтожать, улучшать или передавать обычным обменом')


def project_marks(db,account,packet,*,now=None):
    if packet[:1] not in (b'\x30',b'\x6a') or not table(db,'bank_item_marks'):return packet
    from .protocol.item_marks import project
    stamp=int(time.time() if now is None else now);metadata={}
    if packet[:1]==b'\x30':
        present={i.instance_id for i in decode_item_list(packet)[1] if i.unknown_bytes_02[2]}
    else:
        from .protocol.warehouse import decode_warehouse_list
        present={i.instance_id for i in decode_warehouse_list(packet)[3] if i.marked}
        if present and int.from_bytes(packet[1:5], 'little') == 1:
            from .clans import require, VIEW_WAREHOUSE
            account = clan_mark_holder(require(db, account, VIEW_WAREHOUSE)['id'])
    for instance,original,expires in db.execute("SELECT current_instance,owner,expires FROM bank_item_marks WHERE holder=? AND state='active'",(account,)):
        if instance not in present:continue  # Temporary tutorial/loot IDs are not owned marks.
        name=db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(original,)).fetchone()
        if name:metadata[instance]=(bytes(name[0]).decode('cp1251'),max(0,min(MAX,expires-stamp)))
    return project(packet,metadata)
