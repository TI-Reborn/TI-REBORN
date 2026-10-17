"""Persistent private-market sales and funded purchase requests (manual pp30-31).

All items and funds are escrowed before publication. Replacing an offer first
returns its remaining escrow in the same transaction. A trade atomically moves
payment, items and a durable receipt. Native requests have no transaction token;
the adapter supplies a quote revision to reject a replay after a changed offer.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
from .db_transaction import transaction
from .warehouse import WarehouseStore
from .wallets import WalletStore
from .protocol.item_list import encode_item_list,decode_item_list
from . import market_inventory as inv


def total(price,count):return (price*count+99)//100


def policy():
    p=json.loads((Path(__file__).resolve().parents[1]/'config/private_shops.json').read_text())
    for key in ('maximum_rows','maximum_traders','maximum_signature_bytes','maximum_price_cents'):inv.unsigned(p[key],2**63-1,positive=True)
    return p


class PrivateShopStore:
    def __init__(self,path):
        self.path=path;self.rules=policy();WarehouseStore(path);WalletStore(path)
        with transaction(path) as db:
            inv.initialise(db)
            db.execute('CREATE TABLE IF NOT EXISTS private_shops (id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT NOT NULL UNIQUE,signature TEXT NOT NULL DEFAULT \'\',package INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS private_shop_sales (shop INTEGER NOT NULL,position INTEGER NOT NULL,item_packet BLOB NOT NULL,price_cents INTEGER NOT NULL,PRIMARY KEY(shop,position))')
            db.execute('CREATE TABLE IF NOT EXISTS private_shop_orders (shop INTEGER NOT NULL,position INTEGER NOT NULL,template INTEGER NOT NULL,quantity INTEGER NOT NULL,price_cents INTEGER NOT NULL,enhance INTEGER,held INTEGER NOT NULL,PRIMARY KEY(shop,position))')
            db.execute('CREATE TABLE IF NOT EXISTS private_shop_receipts (account TEXT NOT NULL,request TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,occurred INTEGER NOT NULL,PRIMARY KEY(account,request))')

    @staticmethod
    def _shop(db,account):
        inv.owner(db,account)
        db.execute('INSERT OR IGNORE INTO private_shops(account) VALUES (?)',(account,))
        return db.execute('SELECT id,account,signature,package,revision FROM private_shops WHERE account=?',(account,)).fetchone()

    def ensure(self,account):
        with transaction(self.path) as db:return self._shop(db,account)[0]+0x40000000

    def collect_payables(self,account):
        with transaction(self.path) as db:
            inv.owner(db,account);inv.collect(db,account)

    @staticmethod
    def _row(db,identity):
        inv.unsigned(identity,positive=True)
        row=db.execute('SELECT id,account,signature,package,revision FROM private_shops WHERE id=?',(identity-0x40000000,)).fetchone()
        if row is None:raise ValueError('Лавка не найдена')
        return row

    @staticmethod
    def _items(db,key):
        return tuple((pos,decode_item_list(raw)[1][0],price) for pos,raw,price in db.execute('SELECT position,item_packet,price_cents FROM private_shop_sales WHERE shop=? ORDER BY position',(key,)))

    @staticmethod
    def _orders(db,key):
        return tuple(db.execute('SELECT position,template,quantity,price_cents,enhance,held FROM private_shop_orders WHERE shop=? ORDER BY position',(key,)))

    def _price(self,value):return inv.unsigned(value,self.rules['maximum_price_cents'],positive=True)

    def signature(self,account,text):
        if not isinstance(text,str) or '\0' in text or len(text.encode('cp1251'))>self.rules['maximum_signature_bytes']:raise ValueError('Недопустимая подпись лавки')
        with transaction(self.path) as db:
            row=self._shop(db,account);db.execute('UPDATE private_shops SET signature=?,revision=revision+1 WHERE id=?',(text,row[0]))

    def publish_sales(self,account,selections,*,package=False):
        selections=tuple(selections)
        if type(package) is not bool or len(selections)>self.rules['maximum_rows']:raise ValueError('Недопустимое объявление')
        if len({key for key,_,_ in selections})!=len(selections):raise ValueError('Предмет повторён')
        with transaction(self.path) as db:
            row=self._shop(db,account)
            inv.restore(db,account,(i for _,i,_ in self._items(db,row[0])))
            db.execute('DELETE FROM private_shop_sales WHERE shop=?',(row[0],))
            for pos,(key,count,price) in enumerate(selections,1):
                price=self._price(price);item=inv.take(db,account,key,count)
                if total(price,count)>inv.MAX:raise ValueError('Слишком дорогой лот')
                db.execute('INSERT INTO private_shop_sales VALUES (?,?,?,?)',(row[0],pos,encode_item_list(0,(item,)),price))
            db.execute('UPDATE private_shops SET package=?,revision=revision+1 WHERE id=?',(int(package),row[0]))
            return row[4]+1

    def publish_orders(self,account,orders):
        orders=tuple(orders)
        if len(orders)>self.rules['maximum_rows']:raise ValueError('Слишком много заявок')
        with transaction(self.path) as db:
            row=self._shop(db,account)
            for *_,held in self._orders(db,row[0]):inv.credit(db,account,held)
            db.execute('DELETE FROM private_shop_orders WHERE shop=?',(row[0],))
            from .durability import definitions
            for pos,(template,count,price,enhance) in enumerate(orders,1):
                inv.unsigned(template,0xffff,positive=True);inv.unsigned(count,0x7fffffff,positive=True);price=self._price(price)
                if template not in definitions() or template>=0xff00:raise ValueError('Предмет не доступен в свободной торговле')
                if enhance is not None:inv.unsigned(enhance,27)
                held=total(price,count);inv.debit(db,account,held)
                db.execute('INSERT INTO private_shop_orders VALUES (?,?,?,?,?,?,?)',(row[0],pos,template,count,price,enhance,held))
            db.execute('UPDATE private_shops SET revision=revision+1 WHERE id=?',(row[0],))
            return row[4]+1

    def get(self,identity):
        with transaction(self.path) as db:
            row=self._row(db,identity)
            return dict(id=identity,account=row[1],name=inv.owner(db,row[1]),signature=row[2],package=bool(row[3]),revision=row[4],sales=self._items(db,row[0]),orders=self._orders(db,row[0]))

    def traders(self,kind=0,template=0):
        if kind not in (0,1):raise ValueError('Неизвестный тип лавки')
        with transaction(self.path) as db:
            result=[]
            for row in db.execute('SELECT id,account,signature,package,revision FROM private_shops ORDER BY id').fetchall():
                entries=self._orders(db,row[0]) if kind else self._items(db,row[0])
                if entries and (not template or any((e[1] if kind else e[1].template_id)==template for e in entries)):
                    result.append(dict(id=row[0]+0x40000000,account=row[1],name=inv.owner(db,row[1]),signature=row[2],package=bool(row[3]),revision=row[4],kind=kind))
                    if len(result)>=self.rules['maximum_traders']:break
            return tuple(result)

    @staticmethod
    def _receipt(db,account,request,payload):
        if not isinstance(request,str) or not 16<=len(request)<=128:raise ValueError('Требуется ID сделки')
        fingerprint=hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest()
        row=db.execute('SELECT fingerprint,result FROM private_shop_receipts WHERE account=? AND request=?',(account,request)).fetchone()
        if row:
            if row[0]!=fingerprint:raise ValueError('ID сделки уже использован иначе')
            return fingerprint,json.loads(row[1])
        return fingerprint,None

    def buy(self,account,identity,selections,*,revision,request,now=None):
        selections=tuple(selections)
        with transaction(self.path) as db:
            finger,prior=self._receipt(db,account,request,['buy',identity,revision,selections])
            if prior is not None:return prior
            row=self._row(db,identity);inv.owner(db,account)
            from .character_identity import auth_account
            if auth_account(self.path,row[1])==auth_account(self.path,account):raise ValueError('Нельзя торговать с собственными персонажами')
            if row[4]!=revision:raise ValueError('Предложение изменилось, обновите лавку')
            sales={pos:(item,price) for pos,item,price in self._items(db,row[0])};selected={}
            for pos,count in selections:
                inv.unsigned(count,0x7fffffff,positive=True)
                if pos in selected or pos not in sales or count>sales[pos][0].count:raise ValueError('Товар недоступен')
                selected[pos]=count
            if not selected or (row[3] and selected!={pos:i.count for pos,(i,_) in sales.items()}):raise ValueError('Пакет продаётся целиком')
            cost=sum(total(sales[pos][1],count) for pos,count in selected.items());inv.debit(db,account,cost)
            inv.credit(db,row[1],cost);items=[]
            for pos,count in selected.items():
                item,price=sales[pos];items.append(replace(item,unknown_u32_01=count))
                if count==item.count:db.execute('DELETE FROM private_shop_sales WHERE shop=? AND position=?',(row[0],pos))
                else:db.execute('UPDATE private_shop_sales SET item_packet=? WHERE shop=? AND position=?',(encode_item_list(0,(replace(item,unknown_u32_01=item.count-count),)),row[0],pos))
            inv.deliver(db,account,items);db.execute('UPDATE private_shops SET revision=revision+1 WHERE id=?',(row[0],))
            result=dict(credits=cost,items=len(items));db.execute('INSERT INTO private_shop_receipts VALUES (?,?,?,?,?)',(account,request,finger,json.dumps(result),int(time.time() if now is None else now)))
            return result

    def sell(self,account,identity,selections,*,revision,request,now=None):
        """Selections are (purchase-request position, owned instance ID, units)."""
        selections=tuple(selections)
        with transaction(self.path) as db:
            finger,prior=self._receipt(db,account,request,['sell',identity,revision,selections])
            if prior is not None:return prior
            row=self._row(db,identity);inv.owner(db,account)
            from .character_identity import auth_account
            if auth_account(self.path,row[1])==auth_account(self.path,account):raise ValueError('Нельзя торговать с собственными персонажами')
            if revision!=row[4]:raise ValueError('Заявки изменились, обновите лавку')
            orders={o[0]:o[1:] for o in self._orders(db,row[0])};seen=set();paid=0;items=[]
            if not selections:raise ValueError('Выберите предметы')
            for pos,key,count in selections:
                if pos in seen or pos not in orders:raise ValueError('Повторная или отсутствующая заявка')
                seen.add(pos);template,left,price,enhance,held=orders[pos];item=inv.take(db,account,key,count)
                if count>left or item.template_id!=template or (enhance is not None and item.unknown_bytes_03[0]!=enhance):raise ValueError('Предмет не соответствует заявке')
                remaining=left-count;newheld=total(price,remaining);amount=held-newheld
                paid+=amount;items.append(item)
                if remaining:db.execute('UPDATE private_shop_orders SET quantity=?,held=? WHERE shop=? AND position=?',(remaining,newheld,row[0],pos))
                else:db.execute('DELETE FROM private_shop_orders WHERE shop=? AND position=?',(row[0],pos))
            inv.credit(db,account,paid);inv.deliver(db,row[1],items);db.execute('UPDATE private_shops SET revision=revision+1 WHERE id=?',(row[0],))
            result=dict(credits=paid,items=len(items));db.execute('INSERT INTO private_shop_receipts VALUES (?,?,?,?,?)',(account,request,finger,json.dumps(result),int(time.time() if now is None else now)))
            return result
