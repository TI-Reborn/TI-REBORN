"""City adapter for shared native private stores and persistent SC auction.

Root integration must call handle only for an authenticated selected character,
fence mutations during combat/results, and refresh owned inventories afterwards.
SC uses the reviewed explicit F8 receiver to fill the original native window;
native outgoing BD builders are preserved. Chat commands are optional ordinary
gameplay, never an administrative fixture or privileged wallet change.
"""
import secrets
import hashlib
import time
from pathlib import Path
from contextlib import contextmanager
from .market_operations import market_unit,prepare_market,execute_market
from tio.protocol.private_shops import decode as private_request,encode_traders,encode_goods
from tio.protocol.sc_auction import decode as sc_request
from tio.protocol import sc_auction_view as sc_view
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.warehouse import encode_private_warehouse_snapshot
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore


class PrivateMarketSession:
    def __init__(self,shops,auction,account,*,character_id=1,clock=None):
        if Path(shops.path).resolve()!=Path(auction.path).resolve():raise ValueError('Торговля должна использовать одну базу')
        self.shops,self.auction,self.account,self.character_id=shops,auction,account,character_id
        self.own_id=shops.ensure(account);self.selected=None;self.quotes={};self.query=(0,0);self.next_refresh=0
        self.sc_quotes={};self.sc_claims={};self.sc_bots={};self.sc_open=False
        self.session=secrets.token_hex(16);self.clock=time.time if clock is None else clock

    @contextmanager
    def _action(self):
        snapshots=(dict(self.quotes),dict(self.sc_quotes),dict(self.sc_claims),dict(self.sc_bots))
        try:
            with market_unit(self.shops.path):yield
        except BaseException:
            self.quotes,self.sc_quotes,self.sc_claims,self.sc_bots=snapshots
            raise

    def _execute(self,kind,identity,args,*,allowed,store=None,now=None):
        from tio.db_transaction import current
        command=prepare_market(kind,identity,args)
        return execute_market(command,db=current(),path=self.shops.path,owner=self.account,
            store=self.shops if store is None else store,allowed=allowed,
            now=int(self.clock()) if now is None else now).as_dict()

    def clear_sc(self):
        """Root sends this at authenticated character selection/reconnect."""
        self.sc_quotes.clear();self.sc_claims.clear();self.sc_bots.clear();self.sc_open=False
        self.session=secrets.token_hex(16)
        return (sc_view.encode_clear(),)

    def sc_catalogue(self,*,quote=False,now=None):
        now=int(self.clock() if now is None else now)
        self.auction.tick(now=now);rows=self.auction.catalogue(self.account)
        names=self.auction.public_names(r['bidder'] for r in rows)
        if quote:
            self.sc_quotes={r['id']:r['bids'] for r in rows if r['state']=='active'}
        views=(sc_view.lot_view(row,bidder_name=names.get(row['bidder'],''),
            personal=row['bidder']==self.account,notes=f"SC #{row['id']}",now=now) for row in rows)
        return sc_view.encode_catalogue(views)

    def sc_history(self,lot,page):
        now=int(self.clock());self.auction.tick(now=now);row=self.auction.get(lot)
        events=self.auction.history(lot);names=self.auction.public_names(e['account'] for e in events)
        currency=0 if row['currency']=='credits' else 1
        views=tuple(v for e in events if (v:=sc_view.history_view(e,public_name=names.get(e['account'],''),currency=currency)) is not None)
        count=min(200,self.auction.rules.get('history_page_rows',100));pages=max(1,(len(views)+count-1)//count)
        if not 1<=page<=pages:raise ValueError('Страница истории SC недоступна')
        return sc_view.encode_history(lot,views[(page-1)*count:page*count],page=page,pages=pages,
            remaining_ms=max(0,row['ends']-now)*1000 if row['state']=='active' else 0)

    def sc_bot_view(self,lot,*,quote=False):
        now=int(self.clock());self.auction.tick(now=now);row=self.auction.get(lot)
        if row['state']!='active' or not row['automatic']:raise ValueError('Автобот недоступен для этого лота')
        bot=self.auction.bot(self.account,lot)
        if quote:self.sc_bots[lot]=secrets.token_hex(16)
        return sc_view.encode_bot(lot,row['fee'],bot['from_price'],bot['to_price'],bot['remaining'])

    def _sc_request(self,kind,lot,token,packet):
        return hashlib.sha256(f'{self.session}:{kind}:{lot}:{token}'.encode()+packet).hexdigest()

    def balances(self):
        self.shops.collect_payables(self.account)
        return (encode_asset_count(WalletStore(self.shops.path).ensure(self.account)),*encode_private_warehouse_snapshot(WarehouseStore(self.shops.path).items(self.account)))

    def own(self):
        row=self.shops.get(self.own_id)
        return (encode_goods(row,identity=self.character_id),encode_goods(row,buying=True,identity=self.character_id))

    def listing(self):return encode_traders(self.shops.traders(*self.query))

    def select(self,identity,*,quote=True):
        if identity==self.character_id:identity=self.own_id
        self.selected=identity;shop=self.shops.get(identity)
        if quote:self.quotes[identity]=shop['revision']
        return (encode_goods(shop,buying=bool(self.query[0]),identity=self.character_id if identity==self.own_id else None),)

    def handle(self,packet,*,allow_mutation=True):
        with self._action():return self._handle(packet,allow_mutation=allow_mutation)

    def _handle(self,packet,*,allow_mutation=True):
        op,args=private_request(packet)
        if op==1:
            self.query=args
            return (self.listing(),*self.own())
        if op==3:return self.select(args[0])
        if not allow_mutation:raise ValueError('Торговля доступна после возвращения в город')
        if op==8:self._execute('shop_sales',secrets.token_hex(16),dict(rows=args[1],package=args[0]),allowed=allow_mutation)
        elif op==9:self._execute('shop_orders',secrets.token_hex(16),dict(rows=args[0]),allowed=allow_mutation)
        elif op==10:self._execute('shop_signature',secrets.token_hex(16),dict(signature=args[0]),allowed=allow_mutation)
        elif op in (6,7):
            identity=args[0]
            if identity not in self.quotes:raise ValueError('Сначала откройте актуальную лавку')
            self._execute('shop_sell' if op==7 else 'shop_buy',secrets.token_hex(16),
                dict(shopId=identity,rows=args[1],revision=self.quotes[identity]),allowed=allow_mutation)
            self.quotes.pop(identity,None)
        replies=(*self.balances(),*self.own(),self.listing())
        if self.selected:replies=(*replies,*self.select(self.selected,quote=False))
        return replies

    def command(self,text,*,allow_mutation=True):
        with self._action():return self._command(text,allow_mutation=allow_mutation)

    def _command(self,text,*,allow_mutation=True):
        """Returns public display lines, or None if this is not our command.

        !sc, !sc history ID, !sc cabinet, !sc bid ID, !sc bot ID FROM TO BIDS,
        !sc delete ID, !sc buy ID. All IDs/costs are displayed from server state.
        """
        tokens=text.split()
        if not tokens or tokens[0]!='!sc':return None
        self.auction.tick(now=int(self.clock()))
        if len(tokens)==1 or tokens[1] in ('closed','cabinet'):
            closed=len(tokens)>1 and tokens[1]=='closed';cabinet=len(tokens)>1 and tokens[1]=='cabinet'
            lines=['SC-аукцион: !sc bid ID; !sc bot ID ОТ ДО СТАВОК; !sc delete ID; !sc buy ID; !sc history ID.']
            for row in self.auction.list(self.account,closed=closed,cabinet=cabinet):
                self.sc_quotes[row['id']]=row['bids']
                from tio.protocol.item_list import decode_item_list
                item=decode_item_list(row['item_packet'])[1][0]
                lines.append(f"Лот {row['id']}: предмет {item.template_id}+{item.unknown_bytes_03[0]} x{item.count}; цена {row['price']} {row['currency']}; ставка {row['fee']}; до {row['ends']}; {'авто' if row['automatic'] else 'ручной'}; {row['state']}.")
            return lines
        action=tokens[1]
        if action=='history' and len(tokens)==3:
            events=self.auction.history(int(tokens[2]));names=self.auction.public_names(e['account'] for e in events)
            return [f"{e['occurred']}: {e['action']}, {names.get(e['account']) or 'SC'}, {e['amount']}, {'автобот' if e['automatic'] else 'вручную'}" for e in events] or ['История пуста.']
        if not allow_mutation:raise ValueError('SC-аукцион доступен после возвращения в город')
        if action=='bid' and len(tokens)==3:kind='sc_bid';args=dict(lotId=int(tokens[2]),expectedBids=None)
        elif action=='bot' and len(tokens)==6:
            lot,low,high,count=map(int,tokens[2:]);kind='sc_bot';args=dict(lotId=lot,fromPrice=low,toPrice=high,count=count)
        elif action=='delete' and len(tokens)==3:kind='sc_bot';args=dict(lotId=int(tokens[2]),fromPrice=0,toPrice=0,count=0)
        elif action=='buy' and len(tokens)==3:kind='sc_claim';args=dict(lotId=int(tokens[2]))
        else:raise ValueError('Формат: !sc bid ID; !sc bot ID ОТ ДО СТАВОК; !sc delete ID; !sc buy ID')
        result=self._execute(kind,secrets.token_hex(16),args,allowed=allow_mutation,store=self.auction)
        return [f'SC: {result}']

    def handle_sc(self,packet,*,allow_mutation=True):
        with self._action():return self._handle_sc(packet,allow_mutation=allow_mutation)

    def _handle_sc(self,packet,*,allow_mutation=True):
        """Returns native packet bytes; root sends them, never routes as chat.

        Quotes advance only on an explicit native BD01 query/BD14 bot form open,
        not a passive server push. The old protocol has no client nonce; one
        identical operation against a quote uses one durable receipt. Reopen
        the tab/form to declare a fresh identical intent after a successful bid.
        """
        op,args=sc_request(packet)
        now=int(self.clock())
        if op==1:
            if args[0] not in (0,1,2):raise ValueError('Раздел SC недоступен')
            self.sc_open=True;return (self.sc_catalogue(quote=True,now=now),)
        if op==3:return (self.sc_history(*args),)
        if op==18:return (self.sc_catalogue(now=now),)
        if op==7:
            if not allow_mutation:raise ValueError('SC-аукцион доступен после возвращения в город')
            lot=args[0];self.auction.tick(now=now);row=self.auction.get(lot)
            if row['state']!='won' or row['bidder']!=self.account:raise ValueError('Вы не выиграли этот лот')
            self.sc_claims[lot]=secrets.token_hex(16);wallet=WalletStore(self.shops.path).ensure(self.account)
            currency=0 if row['currency']=='credits' else 1
            return (sc_view.encode_claim(lot,row['price'],currency,row['expires_at'],
                can_pay=(wallet.credits if currency==0 else wallet.gold)>=row['price']),)
        if op==6:
            if not allow_mutation:raise ValueError('SC-аукцион доступен после возвращения в город')
            lot=args[0]
            if lot not in self.sc_quotes:raise ValueError('Сначала обновите вкладку SC-аукциона')
            revision=self.sc_quotes[lot]
            request=self._sc_request('bid',lot,revision,packet)
            self._execute('sc_bid',request,dict(lotId=lot,expectedBids=revision),allowed=allow_mutation,store=self.auction,now=now)
            return (*self.balances(),self.sc_catalogue(now=now))
        if op==20:
            mode,lot,low,high,count=args
            if mode==0:return (self.sc_bot_view(lot,quote=True),)
            if not allow_mutation:raise ValueError('SC-аукцион доступен после возвращения в город')
            if mode==1 and lot not in self.sc_bots:raise ValueError('Сначала откройте настройки автобота')
            if mode==2 and lot not in self.sc_bots and lot not in self.sc_quotes:raise ValueError('Сначала обновите список SC')
            token=self.sc_bots.get(lot,self.sc_quotes.get(lot))
            request=self._sc_request('bot',lot,token,packet)
            self._execute('sc_bot',request,dict(lotId=lot,fromPrice=low,toPrice=high,count=count),allowed=allow_mutation,store=self.auction,now=now)
            # Stock Apply/Delete closes its own form; acknowledge budget and
            # catalogue without reopening a dialog the player just dismissed.
            return (*self.balances(),self.sc_catalogue(now=now))
        if op==9:
            if not allow_mutation:raise ValueError('SC-аукцион доступен после возвращения в город')
            lot,buy=args
            if lot not in self.sc_claims:raise ValueError('Сначала откройте выкуп выигранного лота')
            if buy:
                request=self._sc_request('claim',lot,self.sc_claims[lot],packet)
                self._execute('sc_claim',request,dict(lotId=lot),allowed=allow_mutation,store=self.auction,now=now)
            else:self.sc_claims.pop(lot,None)
            return (sc_view.encode_clear(),*self.balances(),self.sc_catalogue(now=now))
        raise ValueError('Запрос SC недоступен')

    def refresh(self):
        if time.monotonic()<self.next_refresh:return ()
        self.next_refresh=time.monotonic()+2
        self.auction.tick(now=int(self.clock()))
        # Quotes are not silently advanced: stale trades must be explicitly reopened.
        # Both native AE and F8 catalogue receivers show their windows.
        # Local Close sends no request; passive polls must refresh assets only.
        # Explicit AE queries and BD18 refresh still return current catalogues.
        return self.balances()
