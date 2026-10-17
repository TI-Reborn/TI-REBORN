"""City-session adapter for the shared persistent player auction."""
import secrets
import time
from contextlib import nullcontext
from dataclasses import asdict
from .market_operations import market_unit,prepare_market,execute_market
from tio.protocol.player_auction import decode_create
from tio.protocol.binary import Reader, Writer, PacketError
from tio.protocol.player_auction import decode_list, decode_action, encode_lots, encode_added
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.warehouse import encode_private_warehouse_snapshot
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore


def item_type(item):
    from tio.durability import definitions
    d=definitions().get(item.template_id,{})
    if d.get('weaponType'):
        return {'Melee':9,'Light':10,'Automatic':11,'Distance':12,'Heavy':13,'Throwing':14,'Mine':15}.get(d['weaponType'],0)
    if d.get('itype')=='armor':
        return {'head':6,'body':7,'chest':7,'legs':8,'feet':8}.get(d.get('bodypart'),0)
    if d.get('itype')=='ammo':return 1
    if d.get('itype')=='medkit':return 2
    return 0


class AuctionSession:
    def __init__(self, store, account, name, *, gate=None, lock=None):
        self.store,self.account,self.name=store,account,name
        self.gate,self.lock=gate,lock
        self.session=secrets.token_hex(16)
        self.query=None
        self.seen=store.revision()
        self.next_refresh=0

    def balances(self):
        return (encode_asset_count(WalletStore(self.store.path).ensure(self.account)),
                *encode_private_warehouse_snapshot(WarehouseStore(self.store.path).items(self.account)))

    def listing(self, query):
        kind,request,page,ids,types,enhance,durability,order=query
        lots=self.store.lots(closed=bool(kind))
        def match(item):
            if ids and item.template_id not in ids:return False
            if types and item_type(item) not in types:return False
            if enhance and not enhance[0]<=item.unknown_bytes_03[0]<=enhance[1]:return False
            percent=100*item.unknown_words[0]//max(1,item.unknown_words[1])
            if durability and not durability[0]<=percent<=durability[1]:return False
            return True
        lots=[lot for lot in lots if any(match(item) for item in lot[1])]
        if order and order[1] in (1,2):
            # UI 8fb52e..8fb649: lot, ending time, buyout, current price.
            fields={1:'id',2:'ends',3:'buyout',4:'bid'}
            if order[0] not in fields:raise PacketError('Unknown auction sort field')
            def key(lot):
                row=lot[0];value=row[fields[order[0]]]
                if order[0]==4:value=value or row['price']
                return value or 0,row['id']
            lots.sort(key=key,reverse=order[1]==2)
        # Bound pages even with 30-item lots and long descriptions.
        size=10
        pages=max(1,(len(lots)+size-1)//size)
        # Native 902D9A starts at 1; 907BEA clears the list on page 1.
        # Accept legacy probes' zero as the first page as well.
        page=max(1,page)
        return encode_lots(request,page,pages,lots[(page-1)*size:page*size])

    def handle(self, packet):
        if packet[:2] not in (b'\xc8\x0a',b'\xc8\x0d',b'\xc8\x0e',b'\xc8\x0f'):
            return self._handle(packet)
        with self.lock if self.lock is not None else nullcontext():
            with market_unit(self.store.path):
                return self._handle(packet)

    def _execute(self,kind,identity,args):
        from tio.db_transaction import current
        command=prepare_market(kind,identity,args)
        return execute_market(command,db=current(),path=self.store.path,owner=self.account,
            store=self.store,allowed=True,now=int(time.time()),name=self.name,session=self.session,recheck=self.gate)

    def _handle(self, packet):
        revision_before=self.store.revision()
        if packet[:2]==b'\xc8\x10':
            from tio.protocol.player_auction import write_lot
            r=Reader(packet[2:]);lot=r.u32();r.finish()
            found=self.store.get(lot)
            if found is None:raise ValueError('Лот не найден')
            w=Writer().u8(0xc8).u8(0x11);write_lot(w,*found)
            return (w.build(),)
        if packet[:2]==b'\xc8\x06':
            from tio.protocol.player_auction import boolean
            from contextlib import closing
            r=Reader(packet[2:]);lot=r.u32();page=r.u32() if boolean(r) else 0;r.finish()
            if self.store.get(lot) is None:raise ValueError('Лот не найден')
            with closing(self.store._connection(self.store.path)) as db:
                records=db.execute('SELECT * FROM player_auction_history WHERE lot=? ORDER BY id',(lot,)).fetchall()
                names={}
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='characters'").fetchone():
                    for event in records:
                        character=db.execute('SELECT name FROM characters WHERE account=? ORDER BY slot LIMIT 1',(event['account'],)).fetchone()
                        if character:names[event['account']]=bytes(character[0]).decode('cp1251')
            found=self.store.get(lot)[0]
            names[found['seller']]=found['seller_name']
            if found['bidder']:names[found['bidder']]=found['bidder_name']
            w=Writer().u8(0xc8).u8(7).u32(lot).u32(page).u32(max(1,(len(records)+29)//30))
            records=records[page*30:(page+1)*30];w.u32(len(records))
            actions={'created':1,'cancelled':2,'bid':3,'sold':4,'expired':4,'buyout':5}
            for event in records:
                w.u32(actions[event['action']]).u32(event['amount'])
                w.data.extend(names.get(event['account'],'Игрок').encode('cp1251')+b'\0')
                w.u32(event['occurred'])
            return (w.build(),)
        if packet[:2]==b'\xc8\x08':
            self.query=decode_list(packet)
            return (self.listing(self.query),)
        if packet[:2]==b'\xc8\x0a':
            args=asdict(decode_create(packet))
            outcome=self._execute('auction_create',f'{self.session}:{args["request"]}',args)
            lot=outcome.data['lotId']
            request=int.from_bytes(packet[2:6],'little')
            replies=(b'\xc8\x0c'+request.to_bytes(4,'little'),encode_added((self.store.get(lot),)),*self.balances())
        elif packet[:2] in (b'\xc8\x0d',b'\xc8\x0e',b'\xc8\x0f'):
            op,lot,amount,index=decode_action(packet)
            if op==14:
                self._execute('auction_cancel',f'{self.session}:cancel:{lot}',dict(lotId=lot))
                replies=(b'\xc8\x05'+lot.to_bytes(4,'little'),*self.balances())
            else:
                kind='auction_buyout' if op==15 else 'auction_bid'
                args=dict(lotId=lot) if op==15 else dict(lotId=lot,amount=amount,index=index)
                self._execute(kind,f'{self.session}:{op}:{lot}:{index}:{amount}',args)
                row=self.store.get(lot)[0]
                if op==15:
                    update=b'\xc8\x04'+lot.to_bytes(4,'little')
                else:
                    w=Writer().u8(0xc8).u8(2).u32(lot).u32(row['ends'])
                    w.data.extend(row['bidder_name'].encode('cp1251')+b'\0')
                    update=w.u32(row['bid']).u32(row['bid_index']).build()
                replies=(update,*self.balances())
        else:
            raise PacketError('Unsupported player auction request')
        if self.query:replies=(*replies,self.listing(self.query))
        self.seen=revision_before
        return replies

    def refresh(self):
        if time.monotonic()<self.next_refresh:return ()
        self.next_refresh=time.monotonic()+2
        current=self.store.revision()
        if current==self.seen:return ()
        self.seen=current
        replies=self.balances()
        if self.query:replies=(*replies,self.listing(self.query))
        return replies
