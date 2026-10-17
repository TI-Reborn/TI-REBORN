"""Shared native barter; only each session's worker writes its game socket."""
from dataclasses import dataclass,field,replace
import threading,time,uuid
from tio.player_trade import TradeStore
from tio.protocol import player_trade as wire
from tio.protocol.item_list import encode_item_list
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.chat import decode_send,encode_system_message
from tio.protocol.system_message import encode_shop_error
from tio.wallets import WalletStore
from .clan_service import enqueue
from .economy_runtime import city_idle,refresh_inventory
from .market_operations import market_unit,prepare_market,execute_market

@dataclass
class Draft:
    sender:object
    recipient:object
    sender_pet:int
    expires:float
    identity:str=field(default_factory=lambda:uuid.uuid4().hex)
    pets:dict=field(default_factory=dict)
    items:dict=field(default_factory=dict)
    funds:dict=field(default_factory=dict)
    offers:dict=field(default_factory=dict)
    expected:dict=field(default_factory=dict)
    confirmed:set=field(default_factory=set)
    @property
    def sessions(self):return self.sender,self.recipient

class PlayerTrade:
    def __init__(self,router,path,*,clock=time.monotonic):
        self.router=router;self.path=path;self.clock=clock;self.store=TradeStore(path)
        self.lock=threading.RLock();self.by_session={};self.rate={}

    def notice(self,session,text):
        enqueue(self.router.presence,session,encode_system_message(4,b'Trade',text))

    def eligible(self,session):
        presence=self.router.presence
        with presence.lock:online=session in presence.players
        if not online or not getattr(session,'game_authenticated',False) or getattr(session,'stopping',None) and session.stopping.is_set():
            raise ValueError('Игрок недоступен для обмена')
        if not city_idle(session):raise ValueError('Обмен доступен только свободным игрокам в городе')
        return session.locations.current(session.account)

    def pair(self,draft):
        if self.eligible(draft.sender)!=self.eligible(draft.recipient):raise ValueError('Для обмена нужно находиться в одном городе')
        if draft.sender.account==draft.recipient.account:raise ValueError('Нельзя обмениваться с самим собой')

    def closing_packets(self,draft,text):
        result={}
        for session in draft.sessions:
            replies=(wire.done(),encode_system_message(4,b'Trade',text))
            if draft.pets:
                # The native editor optimistically removes offered items from
                # the selected inventory; restore SQL authority on every exit.
                packets=refresh_inventory(session,force=True)
                from tio.weight import city_weight_update
                weights=tuple(city_weight_update(self.path,session.account,p) for p in packets if p[:1]==b'\x30')
                replies+=(*packets,*weights,encode_asset_count(WalletStore(self.path).ensure(session.account)))
            result[session]=replies
        return result

    def close(self,draft,text,*,prepared=None):
        replies=self.closing_packets(draft,text) if prepared is None else prepared
        for session in draft.sessions:
            self.by_session.pop(session,None)
            enqueue(self.router.presence,session,*replies[session])

    def tick(self):
        with self.router.team_arena.lock,self.lock:
            for draft in tuple({d.identity:d for d in self.by_session.values()}.values()):
                try:
                    if self.clock()>=draft.expires:raise ValueError('Время ожидания обмена истекло')
                    self.pair(draft)
                except ValueError as error:self.close(draft,str(error))

    def disconnect(self,session):
        with self.router.team_arena.lock,self.lock:
            self.rate.pop(session,None)
            draft=self.by_session.get(session)
            if draft:self.close(draft,'Обмен отменён: участник отключился')

    def handle(self,session,packet):
        if not packet or packet[0] not in (0x84,0x86,0x88,0x8b):return False
        with self.router.team_arena.lock,self.lock:
            try:
                op,args=wire.decode_request(packet)
                self.tick()
                if op==0x84:self.invite(session,*args)
                elif op==0x86:self.answer(session,*args)
                elif op==0x88:self.offer(session,*args)
                else:self.confirm(session,*args)
            except ValueError as error:
                draft=self.by_session.get(session)
                if draft:self.close(draft,'Обмен отменён: условия сделки изменились')
                else:enqueue(self.router.presence,session,wire.done())
                enqueue(self.router.presence,session,encode_shop_error(str(error)))
        return True

    def guard(self,session,packet):
        """Cancel before any other mutation, so an old confirm cannot pay it."""
        with self.router.team_arena.lock,self.lock:
            draft=self.by_session.get(session)
            if not draft:return
            safe=packet[:1] in (b'\x70',b'\x9e',b'\x2f',b'\x68',b'\x69',b'\xc7',b'\xc5')
            if packet[:1]==b'\x21':
                try:_,text,_=decode_send(packet);safe=not text.lstrip().startswith(('!','/'))
                except ValueError:safe=False
            if not safe and packet[0] not in (0x84,0x86,0x88,0x8b):
                self.close(draft,'Обмен отменён: началось другое действие')

    def invite(self,session,recipient,pet):
        now=self.clock()
        if now<self.rate.get(session,0):raise ValueError('Слишком частые приглашения на обмен')
        self.rate[session]=now+2.5
        self.eligible(session);self.store.available(session.account,pet)
        with self.router.presence.lock:
            target=next((s for s,(_,p) in self.router.presence.players.items() if p.name.lower()==recipient.lower()),None)
        if target is None:raise ValueError('Игрок недоступен для обмена')
        if session in self.by_session or target in self.by_session:raise ValueError('Один из игроков уже участвует в обмене')
        draft=Draft(session,target,pet,now+120);self.pair(draft)
        for s in draft.sessions:self.by_session[s]=draft
        enqueue(self.router.presence,target,wire.invitation(session.probe_character_name))
        self.notice(session,'Приглашение на обмен отправлено')

    def answer(self,session,accepted,pet):
        draft=self.by_session.get(session)
        if draft is None:raise ValueError('Приглашение на обмен недействительно')
        if draft.pets:
            # A repeated answer must not reset the confirmed offers.
            if session is draft.recipient and accepted and draft.pets[session.account]==pet:return
            raise ValueError('Приглашение на обмен недействительно')
        if not accepted:self.close(draft,'Приглашение на обмен отклонено');return
        if session is not draft.recipient:raise ValueError('Приглашение должен принять второй игрок')
        self.pair(draft)
        for s,p in ((draft.sender,draft.sender_pet),(draft.recipient,pet)):
            items,funds=self.store.available(s.account,p)
            draft.pets[s.account]=p;draft.items[s.account]={i.instance_id:i for i in items}
            draft.funds[s.account]=dict(zip(wire.CURRENCIES,funds));draft.offers[s.account]={};draft.expected[s.account]={}
        draft.expires=self.clock()+300
        for s in draft.sessions:
            items=tuple(draft.items[s.account].values())+tuple(wire.money(key,count) for key,count in draft.funds[s.account].items() if count)
            enqueue(self.router.presence,s,wire.start(items))
            self.notice(s,'Выберите вещи и деньги; подтвердить обмен должны оба игрока')

    def active(self,session):
        draft=self.by_session.get(session)
        if draft is None or not draft.pets:raise ValueError('Нет активного обмена')
        self.pair(draft);return draft

    def offer(self,session,key,count):
        draft=self.active(session)
        if draft.confirmed:raise ValueError('После подтверждения состав обмена менять нельзя')
        if not 0<key<=0xffffffff or not 0<count<=0x7fffffff:raise ValueError('Недопустимое количество для обмена')
        account=session.account
        # Native 88 adds a selected quantity; 89/8A replace its cumulative row.
        total=draft.offers[account].get(key,0)+count
        if key in wire.CURRENCIES:
            if total>draft.funds[account][key]:raise ValueError('Недостаточно средств для обмена')
            item=wire.money(key,total)
        else:
            original=draft.items[account].get(key)
            if original is None or total>original.count:raise ValueError('Предмет недоступен для обмена')
            item=replace(original,unknown_u32_01=total)
            draft.expected[account][str(key)]=encode_item_list(draft.pets[account],(original,)).hex()
        draft.offers[account][key]=total
        for s in draft.sessions:enqueue(self.router.presence,s,wire.item_update(item,own=s is session))

    def confirm(self,session,accepted):
        draft=self.by_session.get(session)
        if draft is None:return # Late/duplicate completion is inert.
        if not accepted:self.close(draft,'Обмен отменён');return
        draft=self.active(session)
        if session.account in draft.confirmed:return
        draft.confirmed.add(session.account)
        if len(draft.confirmed)<2:
            for s in draft.sessions:self.notice(s,'Один участник подтвердил обмен; ожидается подтверждение второго')
            return
        parties=tuple((s.account,draft.pets[s.account]) for s in draft.sessions)
        command=prepare_market('trade_commit',draft.identity,dict(parties=parties,
            offers={a:{str(k):v for k,v in rows.items()} for a,rows in draft.offers.items()},
            expected=draft.expected))
        def recheck():
            self.pair(draft)
            return (self.clock()<draft.expires and self.by_session.get(session) is draft and len(draft.confirmed)==2
                    and all(self.by_session.get(peer) is draft for peer in draft.sessions))
        try:
            with market_unit(self.path) as db:
                execute_market(command,db=db,path=self.path,owner=session.account,store=self.store,
                               allowed=True,now=int(time.time()),recheck=recheck)
                packets=self.closing_packets(draft,'Обмен успешно завершён')
        except BaseException:
            draft.confirmed.discard(session.account)
            raise
        self.close(draft,'Обмен успешно завершён',prepared=packets)
