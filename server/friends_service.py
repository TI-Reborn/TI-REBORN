"""Authenticated native friend requests and bounded per-recipient confirmations."""
import time
from contextlib import closing
from tio import friends
from tio.db_transaction import connect
from tio.protocol.friends import Friend,decode_request,encode_invite,encode_list
from tio.protocol.system_message import encode_shop_error
from tio.protocol.chat import encode_system_message

def send(hub,session,packet):
    queue=hub.messages.get(session)
    if queue is not None and len(queue)<128:queue.append(packet);return True
    return False

def sync(hub,session,force=False):
    if getattr(session,'database',None) is None or not getattr(session,'owned_pet_probe',False):return
    from .public_profile import read_profile
    rows=[]
    for owner,name,identity in friends.members(session.database,session.account):
        live=next((p for s,(_,p) in hub.players.items() if s.account==owner),None)
        if live:rows.append(Friend(live.identity,name,True,live.level,status=live.status,crest=live.crest))
        else:
            profile=read_profile(session.database,account=owner,include_history=False)
            rows.append(Friend(0x40000000+identity,name,False,profile.level if profile else 1))
    packet=encode_list(rows)
    if force or packet!=getattr(session,'friends_signature',None):
        if send(hub,session,packet):session.friends_signature=packet

def handle(hub,session,packet):
    if packet[:1] not in (b'\xa1',b'\xa2',b'\xa3',b'\xa6'):return False
    with hub.lock:
        try:
            if session not in hub.players or not getattr(session,'owned_pet_probe',False):raise ValueError('Сначала выберите персонажа')
            op,value=decode_request(packet)
            if op==0xa6:sync(hub,session,True);return True
            if not hasattr(hub,'friend_invites'):hub.friend_invites={}
            pending=hub.friend_invites
            if op==0xa1:
                invitation=pending.pop(session,None)
                if not invitation:raise ValueError('Запрос дружбы уже закрыт')
                sender=invitation
                if sender not in hub.players:raise ValueError('Игрок отключился')
                if value:
                    friends.accept(session.database,session.account,sender.account)
                    sync(hub,session,True);sync(hub,sender,True)
                else:send(hub,sender,encode_system_message(1,b'Server','Запрос дружбы отклонён'))
            else:
                with closing(connect(session.database)) as db:other=friends.resolve(db,value)
                if other==session.account:raise ValueError('Нельзя добавить себя в друзья')
                target=next((s for s in hub.players if s.account==other),None)
                if op==0xa2:
                    friends.remove(session.database,session.account,other);sync(hub,session,True)
                    if target:sync(hub,target,True)
                elif friends.linked(session.database,session.account,other):sync(hub,session,True)
                else:
                    if target is None:raise ValueError('Игрок не в сети')
                    if target in pending:
                        if pending[target] is session:return True
                        raise ValueError('Игрок уже отвечает на другой запрос дружбы')
                    now=time.monotonic()
                    if now<getattr(session,'friend_next_invite',0):raise ValueError('Подождите перед следующим запросом дружбы')
                    if not send(hub,target,encode_invite(session.probe_character_name)):raise ValueError('Игрок временно недоступен')
                    pending[target]=session;session.friend_next_invite=now+2
                    send(hub,session,encode_system_message(1,b'Server','Запрос дружбы отправлен'))
        except ValueError as error:send(hub,session,encode_shop_error(str(error)))
    return True

def disconnect(hub,session):
    pending=getattr(hub,'friend_invites',{})
    for target,sender in tuple(pending.items()):
        # A1 carries no sender ID. Keep a disconnected sender's binding until
        # this recipient answers, so a late Yes cannot accept somebody else.
        if target is session:pending.pop(target,None)
