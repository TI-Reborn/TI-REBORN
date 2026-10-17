"""Shared mutations for barter, private shops and both auction systems.

No new receipt namespace: each store retains its original replay/version policy.
Adapters own authentication, the hub lock and post-commit packet delivery.
"""
from contextlib import contextmanager,closing
from dataclasses import dataclass,field
from collections.abc import Mapping
from .game_operations import OperationRegistry,OperationSpec,OperationResult,OperationRejected
from tio.db_transaction import transaction,connect,current,key
from tio.protocol.binary import Writer
from tio.protocol.player_auction import decode_create
from tio import market_inventory as inv


@contextmanager
def market_unit(path):
    # A projection failure rolls back this action even if an outer unit catches it.
    with transaction(path),closing(connect(path)) as lease,lease:
        yield current()


@dataclass(frozen=True)
class MarketContext:
    db:object
    path:object
    owner:str
    store:object
    allowed:bool
    now:int
    name:str=''
    session:str=''
    recheck:object=field(default=None,repr=False)

    def check(self):
        if current() is not self.db or not self.db.in_transaction:
            raise RuntimeError('Market operation requires the caller transaction')
        main=next((r[2] for r in self.db.execute('PRAGMA database_list') if r[1]=='main'),None)
        if not main or key(main)!=key(self.path) or key(self.store.path)!=key(self.path):
            raise RuntimeError('Market operation belongs to another database')
        if type(self.allowed) is not bool or type(self.now) is not int or not 0<=self.now<=2**53:
            raise RuntimeError('Market requires server-derived gates and clock')
        if not isinstance(self.owner,str) or not self.owner or not self.db.execute('SELECT 1 FROM wallets WHERE account=?',(self.owner,)).fetchone():
            raise ValueError('Требуется существующий кошелёк участника торговли')
        if not self.allowed:raise ValueError('Торговля доступна только свободным игрокам в городе')
        if self.recheck is not None:
            if not callable(self.recheck):raise RuntimeError('Invalid market gate')
            if self.recheck() is not True:raise ValueError('Условия торговли изменились')


def auction_packet(args):
    w=Writer().u8(0xc8).u8(10).u32(args['request']).u32(len(args['items']))
    for instance,count in args['items']:w.u32(instance).u32(count)
    w.u8(args['hours']).u32(args['price']).u32(args['step'])
    w.data.extend(args['description'].encode('utf-16-le')+b'\0\0')
    w.u8(int(args['buyout'] is not None))
    if args['buyout'] is not None:w.u32(args['buyout'])
    return w.build()


def _rows(value,width,maximum=100):
    if not isinstance(value,tuple) or len(value)>maximum or any(not isinstance(row,tuple) or len(row)!=width for row in value):
        raise OperationRejected('Некорректные строки торговой операции')


def _validate(name,args):
    if name=='auction_create':
        _rows(args['items'],2,30)
        if not isinstance(args['description'],str) or '\0' in args['description']:
            raise OperationRejected('Некорректное описание лота')
        decode_create(auction_packet(args));return
    if name=='trade_commit':
        _rows(args['parties'],2,2)
        if len(args['parties'])!=2 or len({a for a,p in args['parties']})!=2:
            raise OperationRejected('Нужны два разных участника')
        owners={a for a,p in args['parties']}
        for owner,pet in args['parties']:
            if not isinstance(owner,str) or not owner:raise OperationRejected('Некорректный участник')
            inv.unsigned(pet,positive=True)
        for name in ('offers','expected'):
            if not isinstance(args[name],Mapping) or set(args[name])!=owners:
                raise OperationRejected('Некорректный состав обмена')
            for rows in args[name].values():
                if not isinstance(rows,Mapping):raise OperationRejected('Некорректные предложения обмена')
                for ident,value in rows.items():
                    if not ident.isdecimal() or str(int(ident))!=ident:raise OperationRejected('Некорректный ID предмета')
                    inv.unsigned(int(ident),positive=True)
                    if name=='offers':inv.unsigned(value,0x7fffffff,positive=True)
                    elif not isinstance(value,str) or len(value)>131070:
                        raise OperationRejected('Некорректный снимок предмета')
        return
    widths={'shop_sales':3,'shop_orders':4,'shop_buy':2,'shop_sell':3}
    if name in widths:_rows(args['rows'],widths[name])
    for field,value in args.items():
        if field=='rows':continue # Store checks entry-specific prices/counts/types.
        if field=='signature':
            if not isinstance(value,str):raise OperationRejected('Некорректная подпись')
        elif field=='package':
            if type(value) is not bool:raise OperationRejected('Некорректный пакет')
        elif field=='expectedBids' and value is None:continue
        else:inv.unsigned(value,positive=field in ('lotId','shopId','amount') or field=='count' and name!='sc_bot')


def _result(command,context,data,replayed=False,owners=None):
    return OperationResult(command,data,replayed,() if replayed else tuple(dict.fromkeys(owners or (context.owner,))))


def _perform(command,c):
    a=command.arguments;s=c.store;name=command.name;db=c.db
    if name=='trade_commit':
        parties=tuple(tuple(p) for p in a['parties'])
        if c.owner not in {owner for owner,pet in parties}:raise ValueError('Посторонний участник обмена')
        old=db.execute('SELECT 1 FROM player_trade_receipts WHERE id=?',(command.identity,)).fetchone()
        offers={owner:{int(k):v for k,v in rows.items()} for owner,rows in a['offers'].items()}
        expected={owner:dict(rows) for owner,rows in a['expected'].items()}
        result=s.commit(command.identity,parties,offers,expected,c.now)
        if not isinstance(result,Mapping) or set(result)!={owner for owner,pet in parties}:
            raise RuntimeError('Invalid barter result')
        for owner,pet in parties:
            row=result[owner]
            if (not isinstance(row,Mapping) or row.get('pet')!=pet or not isinstance(row.get('inventory'),str)
                    or any(type(row.get(k)) is not int or not 0<=row[k]<=0xffffffff for k in ('credits','gold'))):
                raise RuntimeError('Invalid barter receipt')
        return _result(command,c,result,bool(old),tuple(owner for owner,pet in parties))
    if name.startswith('auction_'):
        old=None
        if name=='auction_create':
            old=db.execute('SELECT id FROM player_auction_lots WHERE seller=? AND request_key=?',(c.owner,f'{c.session}:{a["request"]}')).fetchone()
            lot=s.create(c.owner,c.name,auction_packet(a),session=c.session,now=c.now)
            if type(lot) is not int or lot<=0:raise RuntimeError('Invalid created lot')
            owners=(c.owner,)
        else:
            lot=a['lotId'];prior=s.get(lot)
            owners=tuple(x for x in (c.owner,prior[0]['seller'] if prior else None,prior[0]['bidder'] if prior else None) if x)
            if name=='auction_cancel':
                old=prior and prior[0]['state']=='cancelled'
                s.cancel(c.owner,lot,now=c.now)
            else:s.bid(c.owner,c.name,lot,a.get('amount'),a.get('index'),buyout=name=='auction_buyout',now=c.now)
        row=s.get(lot)
        if row is None:raise RuntimeError('Auction result lost its lot')
        actual=row[0]
        if name in ('auction_create','auction_cancel') and actual['seller']!=c.owner:
            raise RuntimeError('Auction result belongs to another seller')
        if name=='auction_cancel' and actual['state']!='cancelled':
            raise RuntimeError('Auction cancellation was not applied')
        if name in ('auction_bid','auction_buyout') and actual['bidder']!=c.owner:
            raise RuntimeError('Auction result belongs to another bidder')
        if name=='auction_bid' and (actual['bid']!=a['amount'] or actual['bid_index']!=a['index']+1):
            raise RuntimeError('Auction bid result does not match the command')
        if name=='auction_buyout' and actual['state']!='sold':
            raise RuntimeError('Auction buyout was not settled')
        return _result(command,c,dict(lotId=lot,state=row[0]['state']),bool(old),owners)
    if name.startswith('shop_'):
        if name in ('shop_sales','shop_orders'):
            value=(s.publish_sales(c.owner,a['rows'],package=a['package']) if name=='shop_sales' else
                   s.publish_orders(c.owner,a['rows']))
            if type(value) is not int or value<0:raise RuntimeError('Invalid published market revision')
            return _result(command,c,dict(revision=value))
        if name=='shop_signature':s.signature(c.owner,a['signature']);return _result(command,c,dict(updated=True))
        old=db.execute('SELECT 1 FROM private_shop_receipts WHERE account=? AND request=?',(c.owner,command.identity)).fetchone()
        target=s.get(a['shopId'])['account']
        value=(s.buy if name=='shop_buy' else s.sell)(c.owner,a['shopId'],a['rows'],revision=a['revision'],request=command.identity,now=c.now)
        if not isinstance(value,Mapping) or any(type(value.get(k)) is not int or value[k]<0 for k in ('credits','items')):
            raise RuntimeError('Invalid private market result')
        return _result(command,c,value,bool(old),(c.owner,target))
    old=db.execute('SELECT 1 FROM sc_auction_receipts WHERE account=? AND request=?',(c.owner,command.identity)).fetchone()
    if name=='sc_bid':value=s.bid(c.owner,a['lotId'],request=command.identity,expected_bids=a['expectedBids'],now=c.now)
    elif name=='sc_bot':value=s.set_bot(c.owner,a['lotId'],a['fromPrice'],a['toPrice'],a['count'],request=command.identity,now=c.now)
    else:value=s.claim(c.owner,a['lotId'],request=command.identity,now=c.now)
    required={'sc_bid':('price','bids','fee'),'sc_bot':('remaining','held'),'sc_claim':('message','price')}[name]
    if not isinstance(value,Mapping) or any(type(value.get(k)) is not int or value[k]<0 for k in required):
        raise RuntimeError('Invalid SC result')
    return _result(command,c,value,bool(old))


MARKET_OPERATIONS=OperationRegistry(tuple(OperationSpec(name,frozenset(fields),
    lambda args,name=name:_validate(name,args),_perform) for name,fields in (
    ('trade_commit',('parties','offers','expected')),
    ('auction_create',('request','items','hours','price','step','description','buyout')),
    ('auction_bid',('lotId','amount','index')),('auction_cancel',('lotId',)),('auction_buyout',('lotId',)),
    ('shop_sales',('rows','package')),('shop_orders',('rows',)),('shop_signature',('signature',)),
    ('shop_buy',('shopId','rows','revision')),('shop_sell',('shopId','rows','revision')),
    ('sc_bid',('lotId','expectedBids')),('sc_bot',('lotId','fromPrice','toPrice','count')),('sc_claim',('lotId',)),
)))


def prepare_market(name,identity,arguments):
    try:return MARKET_OPERATIONS.prepare(name,identity,arguments)
    except OperationRejected as exc:raise ValueError(str(exc)) from None


def execute_market(command,*,db,path,owner,store,allowed,now,name='',session='',recheck=None):
    try:return MARKET_OPERATIONS.execute(command,MarketContext(db,path,owner,store,allowed,now,name,session,recheck))
    except OperationRejected as exc:raise ValueError(str(exc)) from None
