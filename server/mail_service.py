"""Native character mail: quotes are inert, commits use durable escrow tokens."""
from contextlib import closing
from dataclasses import dataclass
import time
import uuid

from tio.db_transaction import connect
from tio.character_identity import owner_for_name
from tio.mail import MailStore,_text
from tio.protocol import mail as wire
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.binary import PacketError
from tio.protocol.system_message import encode_shop_error
from tio.protocol.warehouse import encode_private_warehouse_snapshot
from tio.protocol.warehouse_transfer import decode_warehouse_transfer
from tio.warehouse import WarehouseStore
from tio.wallets import WalletStore
from .clan_service import enqueue

CREDITS_ID=0xffff0001
PAGE_SIZE=20


@dataclass
class Draft:
    recipient:bytes
    subject:str
    body:str
    credits:int
    items:tuple
    token:str
    preview:bytes
    sent:int|None=None


def handles(packet):return packet[:1]==b'\xb7' or packet in (b'\x69\x03',) or packet[:2]==b'\x6b\x03'


def current(session):
    router=getattr(session,'router',None)
    if router is not None:return router.mail_store
    store=getattr(session,'mail_store',None)
    if store is None:session.mail_store=store=MailStore(session.database)
    return store


def post_item(item):
    from tio.protocol.warehouse import warehouse_item_from_inventory
    warehouse_item_from_inventory(item)
    return wire.PostItem(item.instance_id,item.template_id,item.count,item.unknown_words,
        item.unknown_bytes_03[0],item.unknown_bytes_03[1],bool(item.unknown_bytes_03[2]))


def attachments(row):
    values=tuple(post_item(i) for i in row.get('items',()))
    if row['state']=='pending' and row['credits'] and not row.get('money_claimed',False):
        values+=(wire.PostItem(CREDITS_ID,1,row['credits']),)
    return values


def body(row):
    items=attachments(row)
    return wire.encode_body(wire.MailBody(row['id'],row['sender_name'].decode('ascii'),row['subject'],
        row['created_at'],10,False,bool(items),row['body'],0,items))


def listing(store,owner,page=1):
    if page<1:raise ValueError('Недопустимая страница почты')
    rows=store.listing(owner);pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
    if page>pages:raise ValueError('Страница почты не найдена')
    entries=tuple(wire.MailSummary(r['id'],r['sender_name'].decode('ascii'),r['subject'],r['created_at'],
        (r['attachments']+bool(r['credits'] and not r.get('money_claimed',False))) if r['state']=='pending' else 0,not r['read'],0)
        for r in rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE])
    return wire.encode_list(entries,pages=pages,page=page)


def warehouse(store,owner):
    entries=[]
    for row in store.listing(owner):
        if row['state']!='pending':continue
        row=store.read(owner,row['id'],mark_read=False)
        for item in (post_item(i) for i in row['items']):
            entries.append(wire.PostWarehouseItem(row['id'],row['sender_name'].decode('ascii'),
                row['subject'],row['created_at'],item))
    # The native post list is one frame. Refuse oversized state without losing
    # escrow; individual letters remain available through the paged inbox.
    return wire.encode_post_warehouse(entries)


def draft(session,request):
    store=current(session)
    if request.kind!=0:raise ValueError('Этот тип письма не поддерживается')
    subject=_text(request.subject,store.rules['maximum_subject_bytes'])
    text=_text(request.body,store.rules['maximum_body_bytes'])
    money=0;items=[];seen=set()
    for ident,count in request.items:
        if ident in seen or not count:raise ValueError('Недопустимое или повторное вложение')
        seen.add(ident)
        if ident==CREDITS_ID:money=count
        elif ident>=0xffff0000:raise ValueError('По почте можно передавать только кредиты и вещи')
        else:items.append((ident,count))
    fee=store.quote(money,items)
    with closing(connect(session.database)) as db:
        db.execute('BEGIN')
        owner=owner_for_name(db,request.recipient.decode('ascii'))
        if owner is None:raise ValueError('Персонаж получателя не найден')
        if owner==session.account:raise ValueError('Нельзя отправить письмо самому себе')
        from tio.warehouse_completion import read_scope
        values=read_scope(db,session.account,required=True);preview=[]
        for ident,count in items:
            item=values.get(ident)
            if item is None or count>item.count:raise ValueError('Выберите доступные предметы личного склада')
            if item.unknown_bytes_02[2] or item.unknown_bytes_02[3] or item.optional_u32 is not None:
                raise ValueError('Маркированные и арендованные вещи нельзя пересылать')
            from dataclasses import replace
            preview.append(post_item(replace(item,unknown_u32_01=count)))
        recipient=store._name(db,owner)
    if money:preview.append(wire.PostItem(CREDITS_ID,1,money))
    reply=wire.encode_body(wire.MailBody(0,recipient.decode('ascii'),subject,int(time.time()),10,
        False,bool(preview),text,fee,tuple(preview)))
    result=Draft(recipient,subject,text,money,tuple(items),uuid.uuid4().hex,reply)
    session.mail_draft=result
    return result


def mutable(session):
    hub=getattr(getattr(session,'router',None),'team_arena',None)
    if (not getattr(session,'owned_pet_probe',False) or
        (hub and hub.busy(session)) or bool(getattr(session.arena,'_fields',{})) or
        session.survival.searching(session.probe_character_id) or
        any(session.probe_character_id in r.members for r in session.arena.rooms.snapshot()) or
        (session.locations and session.locations.current(session.account) is None)):
        raise ValueError('Отправка и получение вложений доступны в городе вне боя и поиска')


def refresh_assets(presence,session):
    enqueue(presence,session,encode_asset_count(WalletStore(session.database).ensure(session.account)),
        *encode_private_warehouse_snapshot(WarehouseStore(session.database).items(session.account)))


def refresh_post(presence,session):
    try:packet=warehouse(current(session),session.account)
    except PacketError:
        # Receiving an individual letter must succeed independently of the
        # native single-frame aggregate post list. The paged inbox still works.
        return
    enqueue(presence,session,packet)


def finalize(presence,session,value):
    store=current(session)
    ident=store.send(session.account,value.recipient,value.subject,value.body,credits=value.credits,
        items=value.items,request_id=value.token)
    if value.sent is None:
        row=store.read(session.account,ident,outbox=True)
        with presence.lock:
            targets=tuple(s for s in presence.players if s.account==row['recipient'])
        for target in targets:
            enqueue(presence,target,wire.encode_notification(row['sender_name'].decode('ascii'),
                row['subject'],bool(value.items or value.credits)))
    value.sent=ident
    refresh_assets(presence,session)
    enqueue(presence,session,listing(store,session.account))


def handle(presence,session,packet):
    if not handles(packet):return False
    try:
        if not getattr(session,'owned_pet_probe',False) or not session.database:
            raise ValueError('Сначала выберите персонажа')
        store=current(session)
        if packet in (b'\x69\x03',b'\xb7\x0b'):enqueue(presence,session,warehouse(store,session.account))
        elif packet[:2]==b'\x6b\x03':
            mutable(session);request=decode_warehouse_transfer(packet)
            if request.first_items or not request.second_items:
                raise ValueError('Почтовый склад предназначен для получения вложений')
            inventory=store.withdraw(session.account,request.actor_id,items=request.second_items)
            from tio.enhancement_limits import project_owned_inventory
            from tio.clans import project_inventory
            from tio.weight import city_weight_update
            enqueue(presence,session,project_inventory(session.database,session.account,
                project_owned_inventory(session.database,session.account,inventory)),
                city_weight_update(session.database,session.account,inventory),listing(store,session.account))
            refresh_assets(presence,session);refresh_post(presence,session)
        elif packet[:2]==b'\xb7\x0d':enqueue(presence,session,listing(store,session.account,wire.decode_page(packet)))
        elif packet[:2]==b'\xb7\x07':
            mutable(session);value=draft(session,wire.decode_draft(packet));enqueue(presence,session,value.preview)
        elif packet[:2]==b'\xb7\x08':
            mutable(session);calculate,identity=wire.decode_recalculate(packet)
            value=getattr(session,'mail_draft',None)
            if not calculate or identity or value is None:raise ValueError('Сначала создайте черновик письма')
            enqueue(presence,session,value.preview)
        elif packet[:2]==b'\xb7\x09':
            mutable(session);request=wire.decode_money(packet)
            if request.calculate:
                value=draft(session,wire.DraftRequest(0,request.recipient,'','',((CREDITS_ID,request.credits),)))
                enqueue(presence,session,value.preview)
            else:
                value=getattr(session,'mail_draft',None)
                if (value is None or value.items or value.recipient.lower()!=request.recipient.lower() or
                    value.credits!=request.credits):raise ValueError('Сначала рассчитайте стоимость перевода')
                finalize(presence,session,value)
        elif packet[:2]==b'\xb7\x0e':
            request=wire.decode_body_request(packet)
            if request.action==0:
                if not request.identity:raise ValueError('Укажите полученное письмо')
                enqueue(presence,session,body(store.read(session.account,request.identity)))
            else:
                mutable(session)
                if request.action==1 and not request.identity:
                    value=getattr(session,'mail_draft',None)
                    if value is None:raise ValueError('Сначала создайте черновик письма')
                    if request.subject!=value.subject or request.body!=value.body:
                        raise ValueError('Текст изменён: заново рассчитайте стоимость письма')
                    # Echoed assets/durability/price never confer ownership.
                    finalize(presence,session,value)
                elif request.action==1:
                    store.take_money(session.account,request.identity);refresh_assets(presence,session)
                    enqueue(presence,session,body(store.read(session.account,request.identity)),
                        listing(store,session.account))
                    refresh_post(presence,session)
                elif request.action==2:
                    store.delete(session.account,request.identity)
                    enqueue(presence,session,listing(store,session.account))
                    refresh_post(presence,session)
        else:raise ValueError('Эта почтовая операция пока не поддерживается')
    except (ValueError,UnicodeError) as error:
        enqueue(presence,session,encode_shop_error(str(error)[:180] or 'Недопустимое письмо'))
    return True
