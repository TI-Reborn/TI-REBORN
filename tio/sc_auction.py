"""Shared Scandinavian SC auction, paid bids and durable prepaid autobots.

Manual pp32-33 establishes the mechanics, not the historic numerical tariffs.
Config explicitly identifies the server catalogue, charges and clock policy.
Every action (including a timer tick) owns one SQLite transaction. Bots operate
on the authoritative server even when their player is offline. A missed clock
window during downtime closes the lot; no retroactive phantom bids are made.
"""
import hashlib
import json
from pathlib import Path
import secrets
import time
from .db_transaction import transaction
from .warehouse import WarehouseStore
from .wallets import WalletStore
from .protocol.item_list import ItemRecord,encode_item_list,decode_item_list
from . import market_inventory as inv

NATIVE_MAX = 0x7fffffff
NATIVE_SECONDS_MAX = NATIVE_MAX // 1000


def policy():
    p=json.loads((Path(__file__).resolve().parents[1]/'config/sc_auction.json').read_text())
    for k in ('maximum_bot_bids','maximum_rows','maximum_live_lots','claim_expires_seconds','history_page_rows'):inv.unsigned(p[k],positive=True)
    if p['maximum_rows']>200 or p['maximum_live_lots']>p['maximum_rows'] or p['history_page_rows']>200:
        raise ValueError('SC GUI catalogue/history bounds exceeded')
    seen=set()
    for offer in p['offers']:
        if not isinstance(offer['key'],str) or not offer['key'] or offer['key'] in seen:raise ValueError('Invalid SC offer identity')
        seen.add(offer['key'])
        if offer['currency'] != 'credits' or type(offer['automatic']) is not bool:raise ValueError('Invalid SC offer mode')
        for k in ('template','count','start_price','bid_fee','price_step'):
            inv.unsigned(offer[k],NATIVE_MAX,positive=True)
        for k in ('duration','extension'):inv.unsigned(offer[k],NATIVE_SECONDS_MAX,positive=True)
        inv.unsigned(offer['enhance'],27)
    return p


def prize(offer):
    from .durability import definitions
    d=definitions().get(offer['template'])
    if d is None:raise ValueError('Unknown SC prize template')
    durability=int(d.get('durability',1))
    return ItemRecord(1,offer['template'],bytes(2),offer['count'],0,0,(durability,durability,durability),bytes(4),None,bytes((offer['enhance'],0,0)))


def _dict(cursor):
    columns=[c[0] for c in cursor.description]
    return tuple(dict(zip(columns,row)) for row in cursor)


class SCAuctionStore:
    def __init__(self,path,*,rules=None,choose=None):
        self.path=path;self.rules=policy() if rules is None else rules;self.choose=secrets.choice if choose is None else choose
        WarehouseStore(path);WalletStore(path)
        from .mail import MailStore
        MailStore(path)
        with transaction(path) as db:
            inv.initialise(db)
            db.execute('CREATE TABLE IF NOT EXISTS sc_auction_lots (id INTEGER PRIMARY KEY AUTOINCREMENT,offer_key TEXT NOT NULL,generation INTEGER NOT NULL,currency TEXT NOT NULL,start_price INTEGER NOT NULL,price INTEGER NOT NULL,fee INTEGER NOT NULL,step INTEGER NOT NULL,started INTEGER NOT NULL,ends INTEGER NOT NULL,duration INTEGER NOT NULL,extension INTEGER NOT NULL,automatic INTEGER NOT NULL,item_packet BLOB NOT NULL,state TEXT NOT NULL DEFAULT \'active\',bidder TEXT,bids INTEGER NOT NULL DEFAULT 0,message INTEGER,UNIQUE(offer_key,generation))')
            db.execute('CREATE TABLE IF NOT EXISTS sc_auction_bots (lot INTEGER NOT NULL,account TEXT NOT NULL,from_price INTEGER NOT NULL,to_price INTEGER NOT NULL,remaining INTEGER NOT NULL,held INTEGER NOT NULL,PRIMARY KEY(lot,account))')
            db.execute('CREATE TABLE IF NOT EXISTS sc_auction_history (id INTEGER PRIMARY KEY AUTOINCREMENT,lot INTEGER NOT NULL,account TEXT NOT NULL,action TEXT NOT NULL,amount INTEGER NOT NULL,occurred INTEGER NOT NULL,automatic INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS sc_auction_receipts (account TEXT NOT NULL,request TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,occurred INTEGER NOT NULL,PRIMARY KEY(account,request))')
            if 'expires_at' not in {r[1] for r in db.execute('PRAGMA table_info(sc_auction_lots)')}:
                db.execute('ALTER TABLE sc_auction_lots ADD COLUMN expires_at INTEGER')
            # Migrate existing unclaimed wins from their real durable closing
            # event, falling back to recorded ends only for a missing old event.
            db.execute("UPDATE sc_auction_lots SET expires_at=COALESCE((SELECT MIN(occurred) FROM sc_auction_history WHERE lot=sc_auction_lots.id AND action='closed'),ends)+? WHERE state='won' AND expires_at IS NULL",
                       (self.rules.get('claim_expires_seconds',604800),))

    @staticmethod
    def _lot(db,key):
        inv.unsigned(key,positive=True)
        rows=_dict(db.execute('SELECT * FROM sc_auction_lots WHERE id=?',(key,)))
        if not rows:raise ValueError('Лот SC не найден')
        return rows[0]

    @staticmethod
    def _event(db,lot,account,action,amount,now,automatic=False):
        db.execute('INSERT INTO sc_auction_history(lot,account,action,amount,occurred,automatic) VALUES (?,?,?,?,?,?)',(lot,account,action,amount,now,int(automatic)))

    @staticmethod
    def _receipt(db,account,request,payload):
        if not isinstance(request,str) or not 16<=len(request)<=128:raise ValueError('Требуется ID операции SC')
        fingerprint=hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest()
        row=db.execute('SELECT fingerprint,result FROM sc_auction_receipts WHERE account=? AND request=?',(account,request)).fetchone()
        if row:
            if row[0]!=fingerprint:raise ValueError('ID операции уже использован иначе')
            return fingerprint,json.loads(row[1])
        return fingerprint,None

    @staticmethod
    def _save(db,account,request,fingerprint,result,now):
        db.execute('INSERT INTO sc_auction_receipts VALUES (?,?,?,?,?)',(account,request,fingerprint,json.dumps(result),now))
        return result

    @staticmethod
    def _refund_bots(db,lot,now):
        for account,held in db.execute('SELECT account,held FROM sc_auction_bots WHERE lot=?',(lot['id'],)).fetchall():
            inv.credit(db,account,held,lot['currency']);SCAuctionStore._event(db,lot['id'],account,'bot_refund',held,now)
        db.execute('DELETE FROM sc_auction_bots WHERE lot=?',(lot['id'],))

    def _tick(self,db,now):
        changed=0
        for lot in _dict(db.execute("SELECT * FROM sc_auction_lots WHERE state='active' ORDER BY id")):
            if now>=lot['ends']:
                db.execute('UPDATE sc_auction_lots SET state=?,expires_at=? WHERE id=?',
                    ('won' if lot['bidder'] else 'unsold',now+self.rules.get('claim_expires_seconds',604800) if lot['bidder'] else None,lot['id']))
                self._refund_bots(db,lot,now);self._event(db,lot['id'],lot['bidder'] or '', 'closed',lot['price'],now);changed+=1
            elif lot['automatic'] and now>=lot['ends']-1:
                eligible=[]
                from .character_identity import auth_account
                leader=auth_account(self.path,lot['bidder']) if lot['bidder'] else None
                for account,lo,hi,remaining,held in db.execute('SELECT account,from_price,to_price,remaining,held FROM sc_auction_bots WHERE lot=? ORDER BY account',(lot['id'],)):
                    if (remaining and held>=lot['fee'] and auth_account(self.path,account)!=leader
                            and lot['price']+lot['step']<=NATIVE_MAX
                            and lot['ends']+lot['extension']-now<=NATIVE_SECONDS_MAX
                            and (not lo or lot['price']>=lo) and (not hi or lot['price']+lot['step']<=hi)):eligible.append(account)
                if eligible:
                    account=self.choose(tuple(eligible))
                    if account not in eligible:raise ValueError('Invalid authoritative random choice')
                    db.execute('UPDATE sc_auction_bots SET remaining=remaining-1,held=held-? WHERE lot=? AND account=?',(lot['fee'],lot['id'],account))
                    self._bid(db,lot,account,now,automatic=True);changed+=1
        for lot in _dict(db.execute("SELECT * FROM sc_auction_lots WHERE state='won' AND expires_at<=? ORDER BY id",(now,))):
            # No final-price hold exists. Spent bid fees stay spent; unused bot
            # escrow was refunded at close. The system-owned prize is withdrawn.
            db.execute("UPDATE sc_auction_lots SET state='expired' WHERE id=?",(lot['id'],))
            self._event(db,lot['id'],lot['bidder'],'expired',0,now);changed+=1
        return changed

    def tick(self,*,now=None,replenish=True):
        now=int(time.time() if now is None else now)
        with transaction(self.path) as db:
            changed=self._tick(db,now)
            if replenish:
                for offer in self.rules['offers']:
                    live=db.execute("SELECT count(*) FROM sc_auction_lots WHERE state IN ('active','won')").fetchone()[0]
                    if live>=self.rules.get('maximum_live_lots',200):break
                    if db.execute("SELECT 1 FROM sc_auction_lots WHERE offer_key=? AND state='active'",(offer['key'],)).fetchone():continue
                    generation=db.execute('SELECT COALESCE(MAX(generation),0)+1 FROM sc_auction_lots WHERE offer_key=?',(offer['key'],)).fetchone()[0]
                    cur=db.execute('INSERT INTO sc_auction_lots(offer_key,generation,currency,start_price,price,fee,step,started,ends,duration,extension,automatic,item_packet) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                   (offer['key'],generation,offer['currency'],offer['start_price'],offer['start_price'],offer['bid_fee'],offer['price_step'],now,now+offer['duration'],offer['duration'],offer['extension'],int(offer['automatic']),encode_item_list(0,(prize(offer),))))
                    self._event(db,cur.lastrowid,'','created',offer['start_price'],now);changed+=1
            return changed

    def list(self,account=None,*,closed=False,cabinet=False):
        with transaction(self.path) as db:
            if cabinet:
                inv.owner(db,account)
                query="SELECT * FROM sc_auction_lots WHERE bidder=? AND state IN ('won','delivered') ORDER BY id DESC LIMIT ?";args=(account,self.rules['maximum_rows'])
            else:
                query='SELECT * FROM sc_auction_lots WHERE '+("state!='active'" if closed else "state='active'")+' ORDER BY id DESC LIMIT ?';args=(self.rules['maximum_rows'],)
            return _dict(db.execute(query,args))

    def get(self,lot):
        with transaction(self.path) as db:return self._lot(db,lot)

    def catalogue(self,account):
        """One authoritative bounded union; every unclaimed win remains visible.

        Live-lot creation cap ensures active+won never exceed the GUI bound.
        Past delivered/unsold/expired lots fill remaining archive positions.
        Names are projected separately, never expose the private save-owner key.
        """
        with transaction(self.path) as db:
            inv.owner(db,account)
            maximum=min(200,self.rules['maximum_rows'])
            live=_dict(db.execute("SELECT * FROM sc_auction_lots WHERE state IN ('active','won') ORDER BY CASE WHEN bidder=? AND state='won' THEN 0 ELSE 1 END,id DESC",(account,)))
            if len(live)>maximum:raise ValueError('Число незавершённых SC-лотов превышает настроенный предел')
            closed=_dict(db.execute("SELECT * FROM sc_auction_lots WHERE state NOT IN ('active','won') ORDER BY CASE WHEN bidder=? THEN 0 ELSE 1 END,id DESC LIMIT ?",(account,maximum-len(live))))
            return (*live,*closed)

    def public_names(self,accounts):
        with transaction(self.path) as db:
            result={}
            for account in set(accounts):
                if not account:result[account]='';continue
                row=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
                result[account]=bytes(row[0]).decode('cp1251') if row else ''
            return result

    def history(self,lot):
        with transaction(self.path) as db:
            self._lot(db,lot)
            return _dict(db.execute('SELECT * FROM sc_auction_history WHERE lot=? ORDER BY id',(lot,)))

    @staticmethod
    def _bid(db,lot,account,now,*,automatic=False):
        # Original GUI formats these fields as signed Delphi Integer. Reject
        # before any successful transaction can create an unrenderable quote.
        if lot['price']+lot['step']>NATIVE_MAX:raise ValueError('Достигнут предел цены лота')
        if lot['ends']+lot['extension']-now>NATIVE_SECONDS_MAX:raise ValueError('Достигнут предел времени лота')
        db.execute('UPDATE sc_auction_lots SET price=price+step,bidder=?,bids=bids+1,ends=ends+extension WHERE id=?',(account,lot['id']))
        SCAuctionStore._event(db,lot['id'],account,'bid',lot['fee'],now,automatic)

    def bid(self,account,lot,*,request,expected_bids=None,now=None):
        now=int(time.time() if now is None else now)
        with transaction(self.path) as db:
            finger,prior=self._receipt(db,account,request,['bid',lot,expected_bids])
            if prior is not None:return prior
            self._tick(db,now);row=self._lot(db,lot);inv.owner(db,account)
            from .character_identity import auth_account
            if row['state']!='active' or now<row['started']:raise ValueError('Лот закрыт')
            if expected_bids is not None and expected_bids!=row['bids']:raise ValueError('Ставка изменилась, обновите лот')
            if row['bidder'] and auth_account(self.path,row['bidder'])==auth_account(self.path,account):raise ValueError('Ваша ставка уже последняя')
            inv.debit(db,account,row['fee'],row['currency']);self._bid(db,row,account,now)
            return self._save(db,account,request,finger,dict(price=row['price']+row['step'],bids=row['bids']+1,fee=row['fee']),now)

    def set_bot(self,account,lot,from_price,to_price,count,*,request,now=None):
        now=int(time.time() if now is None else now)
        for value in (from_price,to_price):inv.unsigned(value,NATIVE_MAX)
        inv.unsigned(count,self.rules['maximum_bot_bids'])
        if to_price and from_price>to_price:raise ValueError('Недопустимый диапазон автобота')
        with transaction(self.path) as db:
            finger,prior=self._receipt(db,account,request,['bot',lot,from_price,to_price,count])
            if prior is not None:return prior
            self._tick(db,now);row=self._lot(db,lot);inv.owner(db,account)
            if row['state']!='active' or not row['automatic']:raise ValueError('Автобот недоступен для этого лота')
            old=db.execute('SELECT held FROM sc_auction_bots WHERE lot=? AND account=?',(lot,account)).fetchone()
            if old:inv.credit(db,account,old[0],row['currency'])
            db.execute('DELETE FROM sc_auction_bots WHERE lot=? AND account=?',(lot,account))
            held=count*row['fee'];inv.debit(db,account,held,row['currency'])
            if count:db.execute('INSERT INTO sc_auction_bots VALUES (?,?,?,?,?,?)',(lot,account,from_price,to_price,count,held))
            self._event(db,lot,account,'bot_set' if count else 'bot_delete',held,now)
            return self._save(db,account,request,finger,dict(remaining=count,held=held),now)

    def bot(self,account,lot):
        with transaction(self.path) as db:
            inv.owner(db,account);row=db.execute('SELECT from_price,to_price,remaining,held FROM sc_auction_bots WHERE lot=? AND account=?',(lot,account)).fetchone()
            return dict(zip(('from_price','to_price','remaining','held'),row or (0,0,0,0)))

    def claim(self,account,lot,*,request,now=None):
        now=int(time.time() if now is None else now)
        with transaction(self.path) as db:
            finger,prior=self._receipt(db,account,request,['claim',lot])
            if prior is not None:return prior
            self._tick(db,now);row=self._lot(db,lot);name=inv.owner(db,account)
            if row['bidder']!=account or row['state'] not in ('won','delivered'):raise ValueError('Вы не выиграли этот лот')
            if row['message'] is not None:return self._save(db,account,request,finger,dict(message=row['message'],price=row['price']),now)
            from .mail import MailStore,policy as mail_policy
            rules=mail_policy()
            if db.execute("SELECT count(*) FROM mail_messages WHERE recipient=? AND state='pending'",(account,)).fetchone()[0]>=rules['maximum_inbox']:raise ValueError('Почтовый ящик заполнен; выигрыш сохранён в кабинете')
            inv.debit(db,account,row['price'],row['currency'])
            cur=db.execute("INSERT INTO mail_messages(sender,recipient,sender_name,recipient_name,subject,body,credits,fee,created_at,expires_at,state) VALUES (?,?,?,?,?,?,?,?,?,?,'pending')",('@system:sc-auction',account,b'SC Auction',name.encode('cp1251'),'Выигрыш SC-аукциона',f'Лот {lot}',0,0,now,now+rules['expires_seconds']))
            message=cur.lastrowid;inv.unsigned(message,positive=True)
            escrow=MailStore._escrow_id(db);item=decode_item_list(row['item_packet'])[1][0]
            from dataclasses import replace
            db.execute('INSERT INTO mail_items VALUES (?,?,?,?)',(message,0,encode_item_list(0,(replace(item,instance_id=escrow),)),escrow))
            db.execute('INSERT INTO mail_receipts VALUES (?,?,?,?,?)',(message,'sent','@system:sc-auction',now,json.dumps(dict(sc_lot=lot,items=1,fee=0))))
            db.execute("UPDATE sc_auction_lots SET state='delivered',message=? WHERE id=?",(message,lot));self._event(db,lot,account,'claim',row['price'],now)
            return self._save(db,account,request,finger,dict(message=message,price=row['price']),now)
