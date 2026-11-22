"""Persistent shared player-auction escrow. No client-supplied owner or prices.

All ownership and currency transitions use a single SQLite write transaction.
This module does not enable the native UI; wire integration is separate.
"""

from .db_transaction import connect, current, key, Lease
from contextlib import closing
from dataclasses import replace
import hashlib
import sqlite3
import time

from .warehouse import WarehouseStore
from . import warehouse_completion as completion
from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.player_auction import decode_create
from .item_ids import next_item_id

MAX_CREDITS = 0xffffffff


class _AuctionLease(Lease):
    """Row-shaped cursors without changing the enclosing connection factory."""
    def execute(self,sql,*args,**kwargs):
        cursor=super().execute(sql,*args,**kwargs)
        cursor.row_factory=sqlite3.Row
        return cursor


class AuctionStore:
    def __init__(self, path, *, pledge_percent):
        if type(pledge_percent) is not int or not 0 <= pledge_percent <= 100:
            raise ValueError('Explicit auction pledge percentage required')
        self.path, self.pledge_percent = path, pledge_percent
        WarehouseStore(path)
        with closing(connect(path)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS player_auction_lots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller TEXT NOT NULL, seller_name TEXT NOT NULL,
                    request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
                    starts INTEGER NOT NULL, ends INTEGER NOT NULL,
                    price INTEGER NOT NULL, step INTEGER NOT NULL, buyout INTEGER,
                    description TEXT NOT NULL, pledge INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active',
                    bidder TEXT, bidder_name TEXT, bid INTEGER NOT NULL DEFAULT 0,
                    bid_index INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(seller,request_key));
                CREATE INDEX IF NOT EXISTS player_auction_expiry ON player_auction_lots(state,ends);
                CREATE TABLE IF NOT EXISTS player_auction_items (
                    lot INTEGER NOT NULL REFERENCES player_auction_lots(id),
                    ordinal INTEGER NOT NULL, item_packet BLOB NOT NULL,
                    PRIMARY KEY(lot,ordinal));
                CREATE TABLE IF NOT EXISTS player_auction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, lot INTEGER NOT NULL,
                    action TEXT NOT NULL, account TEXT NOT NULL, amount INTEGER NOT NULL,
                    occurred INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS player_auction_credit_pending (
                    account TEXT PRIMARY KEY, amount INTEGER NOT NULL CHECK(amount>=0));
            ''')

    @staticmethod
    def _connection(path):
        active=current()
        if active is not None:
            main=next((r[2] for r in active.execute('PRAGMA database_list') if r[1]=='main'),None)
            if main and key(main)==key(path):return _AuctionLease(active)
        db = connect(path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _debit(db, account, amount):
        if amount < 0 or db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',
                                  (amount, account, amount)).rowcount != 1:
            raise ValueError('Недостаточно кредитов')

    @staticmethod
    def _credit(db, account, amount):
        row = db.execute('SELECT credits FROM wallets WHERE account=?', (account,)).fetchone()
        if row is None:
            raise ValueError('Получатель платежа не существует')
        paid = min(amount, MAX_CREDITS-row[0])
        db.execute('UPDATE wallets SET credits=credits+? WHERE account=?', (paid, account))
        if paid < amount:
            # Preserve excess proceeds/refunds rather than wrap a u32 wallet
            # or prevent another account's auction from settling.
            db.execute('INSERT INTO player_auction_credit_pending VALUES (?,?) ON CONFLICT(account) '
                       'DO UPDATE SET amount=amount+excluded.amount', (account, amount-paid))

    @staticmethod
    def _event(db, lot, action, account, amount, now):
        db.execute('INSERT INTO player_auction_history(lot,action,account,amount,occurred) VALUES (?,?,?,?,?)',
                   (lot, action, account, amount, now))

    @staticmethod
    def _items(db, lot):
        return tuple(decode_item_list(r[0])[1][0] for r in db.execute(
            'SELECT item_packet FROM player_auction_items WHERE lot=? ORDER BY ordinal', (lot,)))

    @staticmethod
    def _deliver(db, lot, account):
        # Delivery never drops goods because the destination warehouse is full.
        # The normal warehouse deposit limit still applies to player transfers.
        # Allocate new account-local IDs, preserving ALL other instance fields.
        ids = set(WarehouseStore._read(db, account))
        for packet, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
            ids.update(item.instance_id for item in decode_item_list(packet)[1])
        next_id = next_item_id(db, account, ids)
        items = AuctionStore._items(db, lot)
        if next_id+len(items)-1 > 0xffffffff:
            raise ValueError('Item ID space exhausted')
        for item in items:
            item = replace(item, instance_id=next_id)
            completion.stash(db,account,(item,),origin='player-auction:'+str(lot))
            next_id += 1
        db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE '
                   'SET next_id=excluded.next_id', (account, next_id))

    @classmethod
    def _close(cls, db, row, now, *, cancelled=False):
        if row['state'] != 'active':
            return
        sold = row['bidder'] is not None and not cancelled
        if cancelled and row['bidder'] is not None:
            raise ValueError('Нельзя снять лот, на который уже сделана ставка')
        cls._deliver(db, row['id'], row['bidder'] if sold else row['seller'])
        if sold:
            cls._credit(db, row['seller'], row['bid']+row['pledge'])
        state = 'sold' if sold else 'cancelled' if cancelled else 'expired'
        db.execute('UPDATE player_auction_lots SET state=? WHERE id=?', (state, row['id']))
        cls._event(db, row['id'], state, row['bidder'] if sold else row['seller'], row['bid'], now)

    @classmethod
    def _expire(cls, db, now):
        for row in db.execute("SELECT * FROM player_auction_lots WHERE state='active' AND ends<=? ORDER BY id", (now,)).fetchall():
            cls._close(db, row, now)

    def settle(self, *, now=None):
        now = int(time.time()) if now is None else int(now)
        with closing(self._connection(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._expire(db, now)
            for row in db.execute('SELECT account,amount FROM player_auction_credit_pending WHERE amount>0').fetchall():
                db.execute('DELETE FROM player_auction_credit_pending WHERE account=?', (row[0],))
                self._credit(db, row[0], row[1])

    def create(self, account, name, packet, *, session, now=None):
        request = decode_create(packet)
        if not account or not session or not name or '\0' in name or len(name.encode('cp1251')) > 255:
            raise ValueError('Invalid auction identity')
        now = int(time.time()) if now is None else int(now)
        key = f'{session}:{request.request}'
        digest = hashlib.sha256(packet).hexdigest()
        with closing(self._connection(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id,request_hash FROM player_auction_lots WHERE seller=? AND request_key=?',
                               (account, key)).fetchone()
            if prior:
                if prior[1] != digest:
                    raise ValueError('Auction request ID reused with different contents')
                return prior[0]
            warehouse = completion.read_scope(db, account, required=True)
            selected = []
            for instance, count in request.items:
                item = warehouse.get(instance)
                if item is None or count > item.count:
                    raise ValueError('Предмет отсутствует на личном складе')
                from .item_boosters import nontransferable
                if nontransferable(item.template_id):raise ValueError('Предметный бустер нельзя выставлять на аукцион')
                if any(item.unknown_bytes_02[2:]) or item.optional_u32 is not None:
                    raise ValueError('Помеченные и арендованные предметы нельзя выставлять')
                selected.append(replace(item, unknown_u32_01=count))
            pledge = min(20000, request.price*self.pledge_percent//100)
            self._debit(db, account, pledge)
            lot = db.execute('INSERT INTO player_auction_lots '
                '(seller,seller_name,request_key,request_hash,starts,ends,price,step,buyout,description,pledge) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (account,name,key,digest,now,now+request.hours*3600,request.price,request.step,request.buyout,
                 request.description,pledge)).lastrowid
            if lot > 0x7fffffff:
                raise ValueError('Auction lot ID space exhausted')
            for ordinal, item in enumerate(selected):
                original = warehouse[item.instance_id]
                if item.count == original.count:
                    db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?', (account,item.instance_id))
                else:
                    remainder = replace(original, unknown_u32_01=original.count-item.count)
                    db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=?',
                               (encode_item_list(0,(remainder,)),account,item.instance_id))
                db.execute('INSERT INTO player_auction_items VALUES (?,?,?)', (lot,ordinal,encode_item_list(0,(item,))))
                db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE '
                           'SET next_id=MAX(next_id,excluded.next_id)', (account,item.instance_id+1))
            self._event(db, lot, 'created', account, request.price, now)
            return lot

    def bid(self, account, name, lot, amount, index, *, buyout=False, now=None):
        now = int(time.time()) if now is None else int(now)
        with closing(self._connection(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM player_auction_lots WHERE id=?', (lot,)).fetchone()
            if row is None or row['state'] != 'active' or row['ends'] <= now or row['starts'] > now:
                raise ValueError('Торги по лоту завершены')
            if account == row['seller']:
                raise ValueError('Нельзя покупать собственный лот')
            if buyout:
                if row['buyout'] is None:
                    raise ValueError('Быстрый выкуп не предусмотрен')
                amount = row['buyout']
            else:
                if index != row['bid_index']:
                    raise ValueError('Ставка изменилась, обновите лот')
                minimum = row['bid']+row['step'] if row['bidder'] else row['price']
                if type(amount) is not int or not minimum <= amount <= 0x7fffffff:
                    raise ValueError('Недопустимая ставка')
                if row['buyout'] is not None and amount >= row['buyout']:
                    raise ValueError('Для этой цены используйте быстрый выкуп')
            previous = row['bid'] if row['bidder'] == account else 0
            self._debit(db, account, amount-previous)
            if row['bidder'] and row['bidder'] != account:
                self._credit(db, row['bidder'], row['bid'])
            db.execute('UPDATE player_auction_lots SET bidder=?,bidder_name=?,bid=?,bid_index=bid_index+1 WHERE id=?',
                       (account,name,amount,lot))
            self._event(db, lot, 'buyout' if buyout else 'bid', account, amount, now)
            if buyout:
                self._close(db, db.execute('SELECT * FROM player_auction_lots WHERE id=?',(lot,)).fetchone(), now)

    def cancel(self, account, lot, *, now=None):
        now = int(time.time()) if now is None else int(now)
        with closing(self._connection(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM player_auction_lots WHERE id=?', (lot,)).fetchone()
            if row is None or row['seller'] != account:
                raise ValueError('Лот не принадлежит этому игроку')
            if row['state'] == 'cancelled':
                return
            if row['state'] != 'active' or row['ends'] <= now:
                raise ValueError('Торги по лоту завершены')
            self._close(db, row, now, cancelled=True)

    def get(self, lot):
        with closing(self._connection(self.path)) as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM player_auction_lots WHERE id=?',(lot,)).fetchone()
            return (dict(row), self._items(db,lot)) if row else None

    def revision(self):
        with closing(self._connection(self.path)) as db:
            return db.execute('SELECT COALESCE(MAX(id),0) FROM player_auction_history').fetchone()[0]

    def lots(self, *, closed=False):
        with closing(self._connection(self.path)) as db:
            db.execute('BEGIN')
            return tuple((dict(row),self._items(db,row['id'])) for row in db.execute(
                "SELECT * FROM player_auction_lots WHERE (state<>'active')=? ORDER BY ends,id",(closed,)).fetchall())

    def active_for(self, account: str) -> tuple:
        with closing(self._connection(self.path)) as db:
            db.execute('BEGIN')
            rows = db.execute(
                "SELECT * FROM player_auction_lots AS l WHERE state='active' AND "
                "(seller=? OR bidder=? OR EXISTS (SELECT 1 FROM player_auction_history "
                "WHERE lot=l.id AND account=? AND action='bid')) ORDER BY ends,id",
                (account, account, account),
            )
            return tuple((dict(row), self._items(db, row['id'])) for row in rows)
