"""Atomic offline character mail with credit/item escrow and durable receipts."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from .db_transaction import connect
from .protocol.item_list import encode_item_list,decode_item_list
from .warehouse import WarehouseStore
from .wallets import WalletStore
from .character_identity import owner_for_name

MAX_CREDITS=0xffffffff


def policy():
    data=json.loads((Path(__file__).resolve().parents[1]/'config/mail.json').read_text())
    for key in ('base_credit_fee','money_fee_percent','item_fee_per_stack','expires_seconds',
                'maximum_attachments','maximum_subject_bytes','maximum_body_bytes','maximum_inbox','warehouse_capacity'):
        if type(data[key]) is not int or not 0<data[key]<=MAX_CREDITS:raise ValueError('Invalid mail policy')
    if data['money_fee_percent']>100:raise ValueError('Invalid mail money tariff')
    return data


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS mail_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,sender TEXT NOT NULL,recipient TEXT NOT NULL,
        sender_name BLOB NOT NULL,recipient_name BLOB NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,
        credits INTEGER NOT NULL,fee INTEGER NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','claimed','deleted','expired')),read INTEGER NOT NULL DEFAULT 0)''')
    db.execute('CREATE INDEX IF NOT EXISTS mail_recipient ON mail_messages(recipient,state,id)')
    db.execute('''CREATE TABLE IF NOT EXISTS mail_items (
        message INTEGER NOT NULL,position INTEGER NOT NULL,item_packet BLOB NOT NULL,
        escrow_id INTEGER NOT NULL UNIQUE,
        PRIMARY KEY(message,position))''')
    db.execute('''CREATE TABLE IF NOT EXISTS mail_item_sequence (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),next_id INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS mail_requests (
        sender TEXT NOT NULL,request_id TEXT NOT NULL,request_hash TEXT NOT NULL,message INTEGER NOT NULL,
        PRIMARY KEY(sender,request_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS mail_receipts (
        message INTEGER NOT NULL,action TEXT NOT NULL,owner TEXT NOT NULL,occurred INTEGER NOT NULL,
        payload TEXT NOT NULL,PRIMARY KEY(message,action))''')


def _text(value,maximum):
    if not isinstance(value,str) or '\0' in value:raise ValueError('Недопустимый текст письма')
    try:raw=value.encode('cp1251')
    except UnicodeError as error:raise ValueError('Используйте русский или латинский текст') from error
    if len(raw)>maximum:raise ValueError('Слишком длинный текст письма')
    return value


def _uint(value):
    if type(value) is not int or not 0<=value<=MAX_CREDITS:raise ValueError('Недопустимая сумма или количество')
    return value


def _selections(items,maximum):
    selected={}
    for key,count in items:
        _uint(key);_uint(count)
        if not key or not count or key in selected:raise ValueError('Недопустимый или повторный предмет')
        selected[key]=count
    if len(selected)>maximum:raise ValueError('Слишком много вложений')
    return selected


def _fingerprint(recipient,subject,body,credits,items):
    raw=json.dumps([recipient,subject,body,credits,sorted(items.items())],ensure_ascii=True,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


class MailStore:
    def __init__(self,path):
        self.path=path;self.rules=policy()
        WarehouseStore(path);WalletStore(path)
        with closing(connect(path)) as db,db:schema(db)

    @staticmethod
    def _name(db,owner):
        row=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(owner,)).fetchone()
        if row is None:raise ValueError('Персонаж не найден')
        return row[0]

    @staticmethod
    def _escrow_id(db):
        row=db.execute('SELECT next_id FROM mail_item_sequence WHERE singleton=1').fetchone()
        value=row[0] if row else 1
        # High IDs are native synthetic currency identifiers, never item escrow.
        if not 1<=value<0xffff0000:raise ValueError('Mail item identity space exhausted')
        db.execute('INSERT INTO mail_item_sequence VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET next_id=excluded.next_id',(value+1,))
        return value

    @staticmethod
    def _expire(db,now):
        rows=db.execute("SELECT id,recipient FROM mail_messages WHERE state='pending' AND expires_at<=?",(now,)).fetchall()
        for ident,owner in rows:
            db.execute('DELETE FROM mail_items WHERE message=?',(ident,))
            db.execute("UPDATE mail_messages SET state='expired',body='',subject='' WHERE id=?",(ident,))
            db.execute('INSERT INTO mail_receipts VALUES (?,?,?,?,?)',(ident,'expired',owner,now,'{}'))
        return len(rows)

    def expire(self,*,now=None):
        now=int(time.time() if now is None else now)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');return self._expire(db,now)

    def quote(self,credits=0,items=()):
        _uint(credits);selected=_selections(items,self.rules['maximum_attachments'])
        fee=self.rules['base_credit_fee']+(credits*self.rules['money_fee_percent']+99)//100+len(selected)*self.rules['item_fee_per_stack']
        if fee+credits>MAX_CREDITS:raise ValueError('Сумма письма слишком велика')
        return fee

    def send(self,sender,recipient_name,subject='',body='',*,credits=0,items=(),request_id,now=None):
        """A retransmitted quote token returns the old message without another debit."""
        now=int(time.time() if now is None else now)
        if not isinstance(request_id,str) or not 16<=len(request_id)<=128 or not request_id.isascii():
            raise ValueError('Mail transaction identity required')
        subject=_text(subject,self.rules['maximum_subject_bytes']);body=_text(body,self.rules['maximum_body_bytes'])
        _uint(credits);selected=_selections(items,self.rules['maximum_attachments'])
        fee=self.quote(credits,selected.items())
        name=recipient_name.decode('ascii') if isinstance(recipient_name,bytes) else recipient_name
        if not isinstance(name,str):raise ValueError('Укажите получателя')
        canonical=_fingerprint(name.lower(),subject,body,credits,selected)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now)
            prior=db.execute('SELECT request_hash,message FROM mail_requests WHERE sender=? AND request_id=?',(sender,request_id)).fetchone()
            if prior:
                if prior[0]!=canonical:raise ValueError('Mail request identity was reused with different contents')
                return prior[1]
            recipient=owner_for_name(db,name)
            if recipient is None:raise ValueError('Персонаж получателя не найден')
            if recipient==sender:raise ValueError('Нельзя отправить письмо самому себе')
            sender_name=self._name(db,sender);target_name=self._name(db,recipient)
            if db.execute("SELECT count(*) FROM mail_messages WHERE recipient=? AND state='pending'",(recipient,)).fetchone()[0]>=self.rules['maximum_inbox']:
                raise ValueError('Почтовый ящик получателя заполнен')
            warehouse=WarehouseStore._read(db,sender)
            seen=set(warehouse)
            for raw, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(sender,)):
                for owned in decode_item_list(raw)[1]:
                    if owned.instance_id in seen:raise ValueError('Item ID exists in multiple locations')
                    seen.add(owned.instance_id)
            for key,count in selected.items():
                item=warehouse.get(key)
                if item is None or count>item.count:raise ValueError('Выберите доступные предметы личного склада')
                from .item_boosters import nontransferable
                if nontransferable(item.template_id):raise ValueError('Предметный бустер нельзя пересылать')
                if item.unknown_bytes_02[2] or item.unknown_bytes_02[3] or item.optional_u32 is not None:
                    raise ValueError('Маркированные, арендованные и особые вложения нельзя пересылать')
            if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',(credits+fee,sender,credits+fee)).rowcount!=1:
                raise ValueError('Недостаточно кредитов для отправки')
            cur=db.execute('''INSERT INTO mail_messages(sender,recipient,sender_name,recipient_name,subject,body,credits,fee,created_at,expires_at,state)
                VALUES (?,?,?,?,?,?,?,?,?,?,'pending')''',(sender,recipient,sender_name,target_name,subject,body,credits,fee,now,now+self.rules['expires_seconds']))
            ident=cur.lastrowid
            if ident>MAX_CREDITS:raise ValueError('Mail identity space exhausted')
            for position,(key,count) in enumerate(selected.items()):
                item=warehouse[key]
                escrow=self._escrow_id(db)
                attached=replace(item,instance_id=escrow,unknown_u32_01=count)
                db.execute('INSERT INTO mail_items VALUES (?,?,?,?)',(ident,position,encode_item_list(0,(attached,)),escrow))
                if count==item.count:db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?',(sender,key))
                else:
                    remainder=replace(item,unknown_u32_01=item.count-count)
                    db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=?',(encode_item_list(0,(remainder,)),sender,key))
            db.execute('INSERT INTO mail_requests VALUES (?,?,?,?)',(sender,request_id,canonical,ident))
            db.execute('INSERT INTO mail_receipts VALUES (?,?,?,?,?)',(ident,'sent',sender,now,json.dumps(dict(credits=credits,fee=fee,items=len(selected)),sort_keys=True)))
            return ident

    @staticmethod
    def _row(db,owner,ident,*,sender=False):
        cursor=db.execute('SELECT * FROM mail_messages WHERE id=? AND '+('sender' if sender else 'recipient')+'=?',(ident,owner))
        row=cursor.fetchone()
        if row is None:raise ValueError('Письмо не найдено')
        result=dict(zip((column[0] for column in cursor.description),row))
        result['money_claimed']=bool(not result['credits'] or result['state']=='claimed' or db.execute(
            "SELECT 1 FROM mail_receipts WHERE message=? AND action='money_claimed'",(ident,)).fetchone())
        return result

    @staticmethod
    def _items(db,ident):
        return tuple(decode_item_list(raw)[1][0] for raw, in db.execute('SELECT item_packet FROM mail_items WHERE message=? ORDER BY position',(ident,)))

    def listing(self,owner,*,outbox=False,now=None):
        now=int(time.time() if now is None else now)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now)
            cursor=db.execute("SELECT m.*,(SELECT count(*) FROM mail_items WHERE message=m.id) AS attachments, (m.credits=0 OR m.state='claimed' OR EXISTS(SELECT 1 FROM mail_receipts r WHERE r.message=m.id AND r.action='money_claimed')) AS money_claimed FROM mail_messages m WHERE "+
                ('sender' if outbox else 'recipient')+"=? AND state IN ('pending','claimed') ORDER BY id DESC LIMIT ?",(owner,self.rules['maximum_inbox']))
            columns=tuple(column[0] for column in cursor.description)
            result=tuple(dict(zip(columns,row)) for row in cursor)
            for row in result:row['money_claimed']=bool(row['money_claimed'])
            return result

    def read(self,owner,ident,*,outbox=False,mark_read=True,now=None):
        _uint(ident);now=int(time.time() if now is None else now)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now)
            row=self._row(db,owner,ident,sender=outbox)
            if row['state'] in ('expired','deleted'):raise ValueError('Срок хранения письма истёк или оно удалено')
            if not outbox and mark_read:db.execute('UPDATE mail_messages SET read=1 WHERE id=?',(ident,))
            row['items']=self._items(db,ident);return row

    @staticmethod
    def _take_money(db,row,now):
        if row['money_claimed']:return 0
        wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(row['recipient'],)).fetchone()
        if wallet is None or wallet[0]+row['credits']>MAX_CREDITS:
            raise ValueError('Освободите место для кредитов перед получением')
        db.execute('UPDATE wallets SET credits=credits+? WHERE account=?',(row['credits'],row['recipient']))
        db.execute('INSERT INTO mail_receipts VALUES (?,?,?,?,?)',(row['id'],'money_claimed',row['recipient'],now,json.dumps(dict(credits=row['credits']),sort_keys=True)))
        row['money_claimed']=True
        return row['credits']

    @staticmethod
    def _complete(db,row,now):
        if row['money_claimed'] and not db.execute('SELECT 1 FROM mail_items WHERE message=?',(row['id'],)).fetchone():
            db.execute("UPDATE mail_messages SET state='claimed',read=1 WHERE id=?",(row['id'],))
            db.execute('INSERT OR IGNORE INTO mail_receipts VALUES (?,?,?,?,?)',(row['id'],'claimed',row['recipient'],now,'{}'))
            row['state']='claimed'

    def take_money(self,owner,ident,*,now=None):
        """B70E/1 takes only credits; item escrow remains for native 6B/3."""
        _uint(ident);now=int(time.time() if now is None else now)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);row=self._row(db,owner,ident)
            if row['state']=='claimed':return row
            if row['state']!='pending':raise ValueError('Письмо недоступно')
            self._take_money(db,row,now);self._complete(db,row,now)
            db.execute('UPDATE mail_messages SET read=1 WHERE id=?',(ident,))
            return row

    def withdraw(self,owner,pet_id,*,items=(),now=None):
        """Recipient-authorized post escrow to an owned pet; replay old IDs inert.

        Partial withdrawals retire their escrow ID and assign a fresh ID to the
        remainder. Repeating the old request therefore cannot take more units.
        """
        _uint(pet_id);selected=_selections(items,self.rules['maximum_attachments'])
        if not pet_id or not selected:raise ValueError('Выберите бойца и почтовые вложения')
        now=int(time.time() if now is None else now)
        from .owned_pets import OwnedPetStore
        from .item_stacking import merge_stacks
        from .inventory_capacity import validate_capacity
        from .weight import inventory_weight
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now)
            pet=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(owner,pet_id)).fetchone()
            if pet is None or OwnedPetStore.validate(pet[1],pet[2],bool(pet[0]))!=pet_id:
                raise ValueError('Выберите своего бойца')
            _,before,flag=decode_item_list(pet[2]);available=[];affected=set()
            for escrow,count in selected.items():
                row=db.execute('''SELECT i.message,i.position,i.item_packet,m.state FROM mail_items i
                    JOIN mail_messages m ON m.id=i.message WHERE i.escrow_id=? AND m.recipient=?''',(escrow,owner)).fetchone()
                if row is None:
                    prior=db.execute("SELECT payload FROM mail_receipts WHERE action=? AND owner=?",('items:'+str(escrow),owner)).fetchone()
                    if prior is None:raise ValueError('Почтовое вложение не найдено')
                    previous=json.loads(prior[0])
                    if previous['pet_id']!=pet_id or previous['count']!=count:
                        raise ValueError('Повтор получения вложения изменён')
                    continue
                message,position,raw,state=row
                if state!='pending':raise ValueError('Почтовое вложение недоступно')
                packet_owner,records,_=decode_item_list(raw)
                if packet_owner or len(records)!=1 or records[0].instance_id!=escrow:
                    raise ValueError('Invalid mail escrow item')
                item=records[0]
                if count>item.count:raise ValueError('Недостаточно предметов в письме')
                available.append((escrow,count,message,position,item));affected.add(message)
            if not available:return bytes(pet[2])
            seen=set(WarehouseStore._read(db,owner))
            for human,packet,inventory in db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=?',(owner,)):
                OwnedPetStore.validate(packet,inventory,bool(human))
                for item in decode_item_list(inventory)[1]:
                    if item.instance_id in seen:raise ValueError('Duplicate owned item identity')
                    seen.add(item.instance_id)
            sequence=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(owner,)).fetchone()
            next_id=max(max(seen,default=0)+1,sequence[0] if sequence else 1);delivered=[]
            for escrow,count,message,position,item in available:
                if next_id>MAX_CREDITS:raise ValueError('Item identity space exhausted')
                delivered.append(replace(item,instance_id=next_id,unknown_u32_01=count,unknown_u8_01=0,location_raw=0));next_id+=1
            after=merge_stacks((*before,*delivered));validate_capacity(before,after)
            updated=encode_item_list(pet_id,after,flag);OwnedPetStore.validate(pet[1],updated,bool(pet[0]))
            inventory_weight(updated)
            for (escrow,count,message,position,item),delivery in zip(available,delivered):
                if count==item.count:db.execute('DELETE FROM mail_items WHERE escrow_id=?',(escrow,))
                else:
                    remaining=self._escrow_id(db)
                    packet=encode_item_list(0,(replace(item,instance_id=remaining,unknown_u32_01=item.count-count),))
                    db.execute('UPDATE mail_items SET item_packet=?,escrow_id=? WHERE escrow_id=?',(packet,remaining,escrow))
                receipt=json.dumps(dict(pet_id=pet_id,count=count,delivered_id=delivery.instance_id),sort_keys=True)
                db.execute('INSERT INTO mail_receipts VALUES (?,?,?,?,?)',(message,'items:'+str(escrow),owner,now,receipt))
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(updated,owner,pet_id))
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(owner,next_id))
            for message in affected:self._complete(db,self._row(db,owner,message),now)
            return updated

    def claim(self,owner,ident,*,now=None):
        _uint(ident);now=int(time.time() if now is None else now)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);row=self._row(db,owner,ident)
            if row['state']=='claimed':return row
            if row['state']!='pending':raise ValueError('Письмо недоступно')
            money=0 if row['money_claimed'] else row['credits']
            wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(owner,)).fetchone()
            if wallet is None or wallet[0]+money>MAX_CREDITS:
                raise ValueError('Освободите место для кредитов перед получением')
            warehouse=WarehouseStore._read(db,owner);attachments=self._items(db,ident)
            from .services import power
            if len(warehouse)+len(attachments)>max(len(warehouse),self.rules['warehouse_capacity']+power(db,owner,1)):
                raise ValueError('Освободите место на личном складе')
            seen=set(warehouse)
            for raw, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(owner,)):
                for item in decode_item_list(raw)[1]:
                    if item.instance_id in seen:raise ValueError('Duplicate owned item identity')
                    seen.add(item.instance_id)
            sequence=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(owner,)).fetchone()
            next_id=max(max(seen,default=0)+1,sequence[0] if sequence else 1)
            for item in attachments:
                if next_id>MAX_CREDITS:raise ValueError('Item identity space exhausted')
                delivered=replace(item,instance_id=next_id,unknown_u8_01=0,location_raw=0)
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',(owner,next_id,encode_item_list(0,(delivered,))))
                next_id+=1
            if attachments:
                db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(owner,next_id))
            self._take_money(db,row,now)
            db.execute('DELETE FROM mail_items WHERE message=?',(ident,))
            db.execute("UPDATE mail_messages SET state='claimed',read=1 WHERE id=?",(ident,))
            db.execute('INSERT INTO mail_receipts VALUES (?,?,?,?,?)',(ident,'claimed',owner,now,json.dumps(dict(credits=row['credits'],items=len(attachments)),sort_keys=True)))
            row['state']='claimed';return row

    def delete(self,owner,ident,*,now=None):
        _uint(ident);now=int(time.time() if now is None else now)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE');self._expire(db,now);row=self._row(db,owner,ident)
            if row['state']=='deleted':return
            if row['state']=='expired':raise ValueError('Срок хранения письма истёк')
            db.execute('DELETE FROM mail_items WHERE message=?',(ident,))
            db.execute("UPDATE mail_messages SET state='deleted',body='',subject='' WHERE id=?",(ident,))
            db.execute('INSERT INTO mail_receipts VALUES (?,?,?,?,?)',(ident,'deleted',owner,now,'{}'))
